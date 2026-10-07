"""Calcul concurrent des bots : les deux planches réfléchissent en même temps.

Chaque décision est calculée dans un processus séparé (``ProcessPoolExecutor``) à partir d'une
copie figée de la partie. La fenêtre / la boucle CLI n'est jamais bloquée : elle appelle
``poll()`` à intervalles réguliers, qui lance les calculs, récupère les résultats terminés et
joue les coups.

Pourquoi des processus et pas des threads : la recherche est du calcul pur Python, et le GIL
empêche deux threads de calculer vraiment en même temps.

Pendant qu'un bot réfléchit, son horloge tourne (vraie partie) et les autres joueurs peuvent
jouer. Si, pendant le calcul, une pièce arrive dans sa poche (capture du coéquipier), la
décision a été prise sans elle ; le coup reste légal (une poche ne fait que grossir), il est
joué tel quel.

``workers=0`` : mode synchrone, sans processus (calcul dans ``poll()``). C'est le comportement
historique ; il sert aux tests et au lancement direct d'un fichier du paquet.
"""
from __future__ import annotations

import concurrent.futures as cf
import copy
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Callable

import chess

from .clock import ManualTime
from .game import BughouseError, Game, HistoryEntry, IllegalMoveError
from .players import Player
from .seat import Seat


def snapshot(game: Game) -> Game:
    """Copie figée et légère de la partie, envoyée au processus qui calcule.

    Le temps est gelé à l'instant de la copie : ``time_left`` donne ce que l'horloge
    affichait à ce moment-là. La copie est superficielle : un attribut ajouté plus tard à
    ``Game`` est transmis tel quel (il doit alors être « picklable »).
    """
    snap = copy.copy(game)
    snap.boards = tuple(b.copy(stack=False) for b in game.boards)
    snap.history = list(game.history)
    snap.clocks = copy.copy(game.clocks)
    snap.clocks.remaining = dict(game.clocks.remaining)
    snap.clocks.running = set(game.clocks.running)
    snap._now = ManualTime(game._now())  # un objet, pas une lambda : il doit être picklable
    return snap


def _think(player: Player, snap: Game, board: int) -> tuple[chess.Move, Player, float]:
    """Exécuté dans le processus de calcul. Renvoie le coup, le bot (avec son état à jour : générateur
    aléatoire, statistiques de debug) et la durée du calcul."""
    t0 = time.perf_counter()
    move = player.choose_move(snap, board)
    return move, player, time.perf_counter() - t0


def _warmup() -> None:
    import bughouse2v2.minimax  # noqa: F401  (charge chess et le bot avant la première vraie décision)

    time.sleep(0.3)  # pour que les deux processus démarrent bien en même temps


def _spawn_safe() -> bool:
    """Faux si le programme a été lancé en exécutant directement un fichier du paquet
    (``python bughouse2v2/gui.py``) : les processus enfants ne sauraient pas le réimporter."""
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    if getattr(main, "__spec__", None) is not None or not path:
        return True
    return os.path.dirname(os.path.abspath(path)) != os.path.dirname(os.path.abspath(__file__))


@dataclass
class _Job:
    future: cf.Future
    key: tuple
    seat: Seat
    player: Player
    started: float


class AsyncBots:
    def __init__(self, workers: int = 2, *, warmup: bool = True) -> None:
        self.fallback_reason: str | None = None
        if workers > 0 and not _spawn_safe():
            self.fallback_reason = (
                "lancé directement depuis un fichier du paquet : calcul parallèle désactivé "
                "(utilise play_gui.py ou python -m bughouse2v2)"
            )
            workers = 0
        self.workers = workers
        self._pool: cf.ProcessPoolExecutor | None = None
        self._jobs: dict[int, _Job] = {}  # planche -> calcul en cours
        self._ready_at: dict[int, float | None] = {0: None, 1: None}
        self._gen = 0
        if workers > 0:
            self._start_pool(warmup)

    # ------------------------------------------------------------------
    def _start_pool(self, warmup: bool = True) -> None:
        # « spawn » partout : seul mode disponible sous Windows, et sûr avec tkinter ailleurs.
        self._pool = cf.ProcessPoolExecutor(max_workers=self.workers, mp_context=mp.get_context("spawn"))
        if warmup:
            for _ in range(self.workers):
                self._pool.submit(_warmup)

    def shutdown(self) -> None:
        for b in list(self._jobs):
            self._drop(b)
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """À appeler quand la partie change sous les pieds des bots (annulation, nouvelle partie) :
        les calculs en cours portent sur une position qui n'existe plus."""
        self._gen += 1
        for b in list(self._jobs):
            self._drop(b)
        self._ready_at = {0: None, 1: None}

    def is_thinking(self, seat: Seat) -> bool:
        job = self._jobs.get(seat.board)
        return job is not None and job.seat == seat

    def _drop(self, board: int) -> None:
        job = self._jobs.pop(board, None)
        if job is not None:
            job.future.cancel()  # sans effet s'il tourne déjà : son résultat sera simplement ignoré
        self._ready_at[board] = None

    def _key(self, game: Game, board: int, seat: Seat) -> tuple:
        # Dans une même « génération » (sans annulation), le nombre de coups joués sur la planche
        # identifie la position de cette planche.
        return (self._gen, board, len(game.boards[board].move_stack), seat)

    def _submit(self, game: Game, player: Player, board: int) -> cf.Future:
        if self._pool is None:  # mode synchrone : on calcule ici, sur la vraie partie
            fut: cf.Future = cf.Future()
            try:
                fut.set_result(_think(player, game, board))
            except Exception as exc:  # noqa: BLE001 - remonté par poll()
                fut.set_exception(exc)
            return fut
        return self._pool.submit(_think, player, snapshot(game), board)

    # ------------------------------------------------------------------
    def poll(
        self,
        game: Game,
        players: dict[Seat, Player],
        *,
        enabled: Callable[[Seat], bool],
        delay: Callable[[], float] = lambda: 0.0,
        on_error: Callable[[str], None] | None = None,
    ) -> list[HistoryEntry]:
        """Un pas de la boucle : lance les calculs des places-bots au trait, joue les coups terminés.

        ``players`` est mis à jour : le bot revient du calcul avec son état (générateur aléatoire...).
        Renvoie les coups joués pendant cet appel.
        """
        played: list[HistoryEntry] = []
        now = time.monotonic()
        for b in (0, 1):
            seat = Seat(b, game.turn(b))
            job = self._jobs.get(b)

            if game.is_over or not enabled(seat) or game.is_blocked(b):
                self._drop(b)
                continue
            if job is not None and (job.key != self._key(game, b, seat) or job.player is not players[seat]):
                self._drop(b)  # position périmée ou bot remplacé
                job = None
            if game.clocks.paused:
                continue

            if job is None:
                ready = self._ready_at[b]
                if ready is None:
                    self._ready_at[b] = now + max(0.0, delay())
                    ready = self._ready_at[b]
                if now < ready:
                    continue
                self._ready_at[b] = None
                player = players[seat]
                job = self._jobs[b] = _Job(
                    self._submit(game, player, b), self._key(game, b, seat), seat, player, time.monotonic()
                )

            if not job.future.done():
                continue
            del self._jobs[b]
            try:
                move, new_player, _seconds = job.future.result()
            except BrokenProcessPool:
                if on_error:
                    on_error("un processus de calcul est mort : relance du pool")
                self._start_pool(warmup=False)
                continue
            except Exception as exc:  # noqa: BLE001 - une erreur de bot ne doit pas tuer l'interface
                if on_error:
                    on_error(f"erreur du bot {seat} : {exc!r}")
                continue
            if players.get(seat) is job.player:
                players[seat] = new_player
            try:
                played.append(game.push(b, move))
            except IllegalMoveError:
                if on_error:
                    on_error(f"le bot {seat} a renvoyé un coup illégal : {move.uci()}")
            except BughouseError:
                pass  # partie finie ou drapeau tombé pendant le calcul
        return played