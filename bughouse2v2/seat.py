"""Identification d'un joueur : une place = (planche, couleur)."""
from __future__ import annotations

from typing import NamedTuple

import chess

BOARD_A, BOARD_B = 0, 1


class Seat(NamedTuple):
    board: int  # 0 = planche A, 1 = planche B
    color: chess.Color  # chess.WHITE / chess.BLACK

    @property
    def team(self) -> int:
        """Équipe 0 = Blancs de A + Noirs de B ; équipe 1 = Noirs de A + Blancs de B."""
        return 0 if (self.board == BOARD_A) == (self.color == chess.WHITE) else 1

    @property
    def partner(self) -> "Seat":
        """Le coéquipier est sur l'autre planche, avec la couleur opposée."""
        return Seat(1 - self.board, not self.color)

    def __str__(self) -> str:
        return f"{'AB'[self.board]}{'W' if self.color == chess.WHITE else 'B'}"


ALL_SEATS: tuple[Seat, ...] = tuple(
    Seat(b, c) for b in (BOARD_A, BOARD_B) for c in (chess.WHITE, chess.BLACK)
)
