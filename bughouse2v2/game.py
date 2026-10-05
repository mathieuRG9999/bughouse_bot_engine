"""Moteur de bughouse 2v2 au-dessus de python-chess.

Chaque planche est une ``CrazyhouseBoard`` (drops, promotions qui redeviennent pions
à la capture, légalité des coups). La règle propre au bughouse est gérée ici : une
pièce capturée va dans la poche du *coéquipier* (autre planche, couleur opposée),
pas dans la poche de celui qui capture.

Annulation : chaque coup stocke un instantané des poches et des horloges, ce qui
rend ``undo()`` exact, y compris pour les transferts de pièces entre planches.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import chess
import chess.variant

from .clock import ClockSet, ClockSnapshot, TimeControl, TimeSource, monotonic
from .seat import BOARD_A, BOARD_B, Seat

Pockets = list[list[chess.variant.CrazyhousePocket]]  # [planche][couleur]


class BughouseError(Exception):
    pass


class IllegalMoveError(BughouseError):
    pass


class GameStateError(BughouseError):
    """Partie non démarrée, terminée ou en pause."""


class Termination(Enum):
    CHECKMATE = "mat"
    TIMEOUT = "temps"
    RESIGNATION = "abandon"


@dataclass(frozen=True)
class Result:
    winner: int  # numéro d'équipe gagnante (voir Seat.team)
    reason: Termination
    loser: Seat  # joueur maté / tombé au temps / qui abandonne


@dataclass(frozen=True)
class HistoryEntry:
    ply: int  # numéro global du coup (les deux planches confondues), à partir de 1
    seat: Seat
    move: chess.Move
    san: str
    captured: int | None  # type de pièce envoyée au coéquipier
    elapsed: float  # secondes depuis le début de la partie
    pockets_before: Pockets
    clocks_before: ClockSnapshot


class Game:
    def __init__(
        self,
        time_control: TimeControl = TimeControl(),
        *,
        now: TimeSource = monotonic,
        fens: tuple[str, str] | None = None,
    ) -> None:
        if fens is None:
            self.boards = (chess.variant.CrazyhouseBoard(), chess.variant.CrazyhouseBoard())
        else:
            self.boards = (
                chess.variant.CrazyhouseBoard(fens[0]),
                chess.variant.CrazyhouseBoard(fens[1]),
            )
        self.time_control = time_control
        self.clocks = ClockSet(time_control)
        self.history: list[HistoryEntry] = []
        self.result: Result | None = None
        self.started = False
        self._now = now
        self._t0 = 0.0

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------
    @property
    def is_over(self) -> bool:
        return self.result is not None

    @property
    def active_seats(self) -> set[Seat]:
        """Les joueurs dont l'horloge tourne actuellement."""
        return set(self.clocks.running)

    def turn(self, board: int) -> chess.Color:
        return self.boards[board].turn

    def legal_moves(self, board: int) -> list[chess.Move]:
        return list(self.boards[board].legal_moves)

    def is_blocked(self, board: int) -> bool:
        """Le joueur au trait n'a aucun coup (ex. pat) : il attend une pièce du partenaire."""
        return not self.boards[board].legal_moves

    def pocket(self, board: int, color: chess.Color) -> dict[int, int]:
        pocket = self.boards[board].pockets[color]
        return {pt: pocket.count(pt) for pt in chess.PIECE_TYPES if pocket.count(pt)}

    def time_left(self, seat: Seat) -> float:
        return self.clocks.time_left(seat, self._now())

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self.started:
            raise GameStateError("la partie a déjà démarré")
        now = self._now()
        self._t0 = now
        self.clocks.start({Seat(i, b.turn) for i, b in enumerate(self.boards)}, now)
        self.started = True

    def pause(self) -> None:
        self._require_active()
        self.clocks.pause(self._now())

    def resume(self) -> None:
        self._require_active(allow_paused=True)
        self.clocks.resume(self._now())

    def resign(self, seat: Seat) -> Result:
        self._require_active(allow_paused=True)
        return self._finish(Result(1 - seat.team, Termination.RESIGNATION, seat))

    def check_time(self) -> Result | None:
        """À appeler régulièrement (boucle UI/bot) : termine la partie si un drapeau est tombé."""
        if not self.started or self.result is not None:
            return self.result
        self.clocks.sync(self._now())
        flagged = self.clocks.flagged()
        if flagged is not None:
            return self._finish(Result(1 - flagged.team, Termination.TIMEOUT, flagged))
        return None

    # ------------------------------------------------------------------
    # Coups
    # ------------------------------------------------------------------
    def push(self, board: int, move: chess.Move | str) -> HistoryEntry:
        """Joue ``move`` (objet Move ou UCI, ex. "e2e4" ou "P@e5") sur la planche ``board``."""
        self._require_active()
        if self.check_time() is not None:
            raise GameStateError("temps écoulé")
        now = self._now()

        b = self.boards[board]
        if isinstance(move, str):
            try:
                move = chess.Move.from_uci(move)
            except ValueError as exc:
                raise IllegalMoveError(f"coup UCI invalide : {move!r}") from exc
        if move not in b.legal_moves:
            raise IllegalMoveError(f"coup illégal sur la planche {'AB'[board]} : {move.uci()}")

        mover = b.turn
        seat = Seat(board, mover)
        san = b.san(move)
        pockets_before = self._pockets()
        clocks_before = self.clocks.snapshot()

        b.push(move)

        # python-chess crédite le preneur ; en bughouse la pièce va au coéquipier.
        prev = pockets_before[board][mover]
        captured = next(
            (pt for pt in chess.PIECE_TYPES if b.pockets[mover].count(pt) > prev.count(pt)),
            None,
        )
        if captured is not None:
            b.pockets[mover].remove(captured)
            self.boards[1 - board].pockets[not mover].add(captured)

        self.clocks.press(seat, now)

        entry = HistoryEntry(
            ply=len(self.history) + 1,
            seat=seat,
            move=move,
            san=san,
            captured=captured,
            elapsed=now - self._t0,
            pockets_before=pockets_before,
            clocks_before=clocks_before,
        )
        self.history.append(entry)

        if b.is_checkmate():
            self._finish(Result(seat.team, Termination.CHECKMATE, Seat(board, not mover)))
        return entry

    def undo(self) -> HistoryEntry | None:
        """Annule le dernier coup joué (toutes planches confondues). Rend aussi ses temps."""
        if not self.history:
            return None
        entry = self.history.pop()
        self.boards[entry.seat.board].pop()
        self._restore_pockets(entry.pockets_before)
        self.clocks.restore(entry.clocks_before, self._now())
        self.result = None
        return entry

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------
    def render(self) -> str:
        lines: list[str] = []
        for i, b in enumerate(self.boards):
            lines.append(f"=== Planche {'AB'[i]} ===")
            lines.append(self._side_line(i, chess.BLACK))
            for rank in range(7, -1, -1):
                row = " ".join(
                    (p.symbol() if (p := b.piece_at(chess.square(f, rank))) else ".")
                    for f in range(8)
                )
                lines.append(f"  {rank + 1}  {row}")
            lines.append("     a b c d e f g h")
            lines.append(self._side_line(i, chess.WHITE))
            lines.append("")
        if self.result:
            r = self.result
            lines.append(f"Résultat : équipe {r.winner} gagne ({r.reason.value}, perdant : {r.loser})")
        return "\n".join(lines)

    def _side_line(self, board: int, color: chess.Color) -> str:
        seat = Seat(board, color)
        name = "Blancs" if color == chess.WHITE else "Noirs "
        trait = ">" if seat in self.clocks.running else " "
        pocket = str(self.boards[board].pockets[color]) or "-"
        return f"{trait} {name} {seat}  {self._fmt_time(seat)}   poche : {pocket}"

    def _fmt_time(self, seat: Seat) -> str:
        tenths = max(0, round(self.time_left(seat) * 10))
        minutes, tenths = divmod(tenths, 600)
        return f"{minutes}:{tenths / 10:04.1f}"

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------
    def _require_active(self, allow_paused: bool = False) -> None:
        if not self.started:
            raise GameStateError("la partie n'a pas démarré (appeler start())")
        if self.result is not None:
            raise GameStateError("la partie est terminée")
        if self.clocks.paused and not allow_paused:
            raise GameStateError("la partie est en pause")

    def _finish(self, result: Result) -> Result:
        self.clocks.stop(self._now())
        self.result = result
        return result

    def _pockets(self) -> Pockets:
        return [[p.copy() for p in b.pockets] for b in self.boards]

    def _restore_pockets(self, snap: Pockets) -> None:
        for b, pockets in zip(self.boards, snap):
            for i, p in enumerate(pockets):
                b.pockets[i] = p.copy()
