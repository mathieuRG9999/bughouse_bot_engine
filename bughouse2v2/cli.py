"""Jeu manuel en ligne de commande, en temps réel.

    python -m bughouse2v2                      # tu joues les 4 places (hotseat)
    python -m bughouse2v2 --bots BW,BB         # les places BW et BB sont jouées par des bots aléatoires
    python -m bughouse2v2 --base 60 --increment 1

Places : AW = Blancs de A, AB = Noirs de A, BW = Blancs de B, BB = Noirs de B.
Les deux planches vont en parallèle : tu peux jouer sur A ou B à tout moment, dès
que c'est le tour du joueur concerné (le ``>`` dans l'affichage marque les horloges
qui tournent).
"""
from __future__ import annotations

if __package__ in (None, ""):  # lancé comme un simple script (python cli.py, bouton « Run » d'un IDE)
    import os
    import runpy
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        runpy.run_module("bughouse2v2", run_name="__main__")
    except ImportError as exc:
        if getattr(exc, "name", None) == "chess":
            raise SystemExit("Il manque la bibliothèque chess : pip install -r requirements.txt")
        if "bughouse2v2" in str(exc):
            raise SystemExit("Les fichiers doivent rester dans un dossier nommé bughouse2v2/ (avec __init__.py).")
        raise
    raise SystemExit

import argparse
import queue
import random
import sys
import threading
import time
from typing import Callable, TextIO

import chess

from .clock import TimeControl, monotonic
from .game import BughouseError, Game, IllegalMoveError
from .players import Player, RandomPlayer
from .minimax import MinimaxPlayer
from .seat import ALL_SEATS, Seat

HELP = """\
Commandes :
  a <coup>        joue sur la planche A   (ex. : a e2e4, a Nf3, a P@e5, a O-O)
  b <coup>        joue sur la planche B   (même syntaxe)
  moves a|b       liste les coups légaux de la planche
  undo  (u)       annule le dernier coup (toutes planches confondues)
  pause / resume  fige / relance les horloges
  resign AW|AB|BW|BB   la place indiquée abandonne (son équipe perd)
  show  (s)       réaffiche les planches
  help  (h)       cette aide
  quit  (q)       quitte
Un coup s'écrit en UCI (e2e4, drop P@e5) ou en notation SAN (e4, Nf3, N@f3, exd5)."""


def parse_seat(text: str) -> Seat:
    t = text.strip().upper()
    if len(t) != 2 or t[0] not in "AB" or t[1] not in "WB":
        raise ValueError(f"place invalide : {text!r} (attendu AW, AB, BW ou BB)")
    return Seat("AB".index(t[0]), chess.WHITE if t[1] == "W" else chess.BLACK)


def parse_move(game: Game, board: int, text: str) -> chess.Move:
    b = game.boards[board]
    try:
        move = chess.Move.from_uci(text)
        if move in b.legal_moves:
            return move
    except ValueError:
        pass
    try:
        return b.parse_san(text)
    except ValueError as exc:  # coup invalide / illégal / ambigu
        raise IllegalMoveError(f"coup non reconnu ou illégal sur {'AB'[board]} : {text!r}") from exc


def handle(game: Game, line: str) -> tuple[str, bool]:
    """Exécute une commande. Renvoie (message à afficher, True si on quitte)."""
    parts = line.strip().split()
    if not parts:
        return "", False
    cmd, args = parts[0].lower(), parts[1:]
    try:
        if cmd in ("a", "b"):
            if len(args) != 1:
                return f"usage : {cmd} <coup>", False
            board = "ab".index(cmd)
            entry = game.push(board, parse_move(game, board, args[0]))
            extra = f"  (pièce envoyée à {entry.seat.partner})" if entry.captured else ""
            return f"{entry.seat} joue {entry.san}{extra}\n{game.render()}", False
        if cmd in ("undo", "u"):
            entry = game.undo()
            if entry is None:
                return "rien à annuler", False
            return f"annulé : {entry.seat} {entry.san}\n{game.render()}", False
        if cmd == "moves":
            if len(args) != 1 or args[0].lower() not in ("a", "b"):
                return "usage : moves a|b", False
            board = "ab".index(args[0].lower())
            b = game.boards[board]
            sans = sorted(b.san(m) for m in b.legal_moves)
            return f"Planche {args[0].upper()} ({len(sans)} coups) : " + " ".join(sans), False
        if cmd == "pause":
            game.pause()
            return "partie en pause", False
        if cmd == "resume":
            game.resume()
            return "partie relancée", False
        if cmd == "resign":
            if len(args) != 1:
                return "usage : resign AW|AB|BW|BB", False
            game.resign(parse_seat(args[0]))
            return game.render(), False
        if cmd in ("show", "s"):
            return game.render(), False
        if cmd in ("help", "h", "?"):
            return HELP, False
        if cmd in ("quit", "q", "exit"):
            return "au revoir", True
        return f"commande inconnue : {cmd!r} (help pour l'aide)", False
    except (BughouseError, ValueError) as exc:
        return f"erreur : {exc}", False


def run(
    game: Game,
    bots: dict[Seat, Player] | None = None,
    *,
    bot_delay: float = 1.0,
    inp: TextIO = sys.stdin,
    out: Callable[[str], None] = lambda s: print(s, flush=True),
) -> None:
    bots = bots or {}
    lines: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        for line in inp:
            lines.put(line)
        lines.put(None)  # fin de l'entrée

    threading.Thread(target=reader, daemon=True).start()

    game.start()
    out(HELP + "\n")
    out(game.render())
    rng = random.Random()
    ready: dict[int, float | None] = {0: None, 1: None}
    announced = False

    while True:
        try:
            line: str | None | bool = lines.get(timeout=0.05)
        except queue.Empty:
            line = False  # pas d'entrée ce tour-ci

        if line is None:
            return
        if line is not False:
            msg, quit_ = handle(game, line)  # type: ignore[arg-type]
            if msg:
                out(msg)
            if quit_:
                return
            ready = {0: None, 1: None}  # un coup ou un undo peut avoir changé qui est au trait

        if not game.is_over and game.check_time() is not None:
            out(game.render())

        now = monotonic()
        for b in (0, 1):
            seat = Seat(b, game.turn(b))
            if game.is_over or seat not in bots or game.clocks.paused or game.is_blocked(b):
                ready[b] = None
                continue
            if ready[b] is None:
                ready[b] = now + bot_delay * rng.uniform(0.5, 1.5)
            elif now >= ready[b]:
                try:
                    entry = game.push(b, bots[seat].choose_move(game, b))
                except BughouseError:
                    ready[b] = None
                    continue
                ready[b] = None
                out(f"[bot] {entry.seat} joue {entry.san}\n{game.render()}")

        if game.is_over and not announced:
            announced = True
            out("Partie terminée. (undo pour revenir en arrière, quit pour quitter)")
        elif not game.is_over:
            announced = False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Bughouse 2v2 en ligne de commande")
    ap.add_argument("--base", type=float, default=180.0, help="secondes par joueur (défaut 180)")
    ap.add_argument("--increment", type=float, default=0.0, help="incrément par coup (défaut 0)")
    ap.add_argument("--bots", default="", help="places jouées par des bots, ex. BW,BB (défaut : aucune)")
    ap.add_argument("--bot-delay", type=float, default=1.0, help="délai moyen d'un bot (s)")
    ap.add_argument("--bot-type", choices=["random", "minimax"], default="random")
    args = ap.parse_args(argv)

    seats = [parse_seat(s) for s in args.bots.split(",") if s.strip()]
    make = MinimaxPlayer if args.bot_type == "minimax" else RandomPlayer
    bots: dict[Seat, Player] = {s: make(f"bot-{s}") for s in seats if s in ALL_SEATS}    
    game = Game(TimeControl(args.base, args.increment), now=monotonic)
    try:
        run(game, bots, bot_delay=args.bot_delay)
    except KeyboardInterrupt:
        print("\ninterrompu")


if __name__ == "__main__":
    main()
