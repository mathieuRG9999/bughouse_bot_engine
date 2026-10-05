"""Machine à états des clics de l'interface graphique (aucune dépendance à tkinter).

Séparée de la vue pour pouvoir être testée sans écran. Deux façons de construire un coup :
  - clic sur une de ses pièces, puis clic sur la case d'arrivée ;
  - clic sur une pièce de sa poche (drop), puis clic sur une case libre.
Les méthodes ``click_*`` renvoient la liste des coups légaux correspondants :
vide = rien à jouer, 1 coup = à jouer, plusieurs = promotion (la vue demande le choix).
"""
from __future__ import annotations

import chess

from .game import Game


class Interaction:
    def __init__(self, game: Game) -> None:
        self.game = game
        self.clear()

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self.board: int | None = None
        self.from_sq: int | None = None
        self.drop: int | None = None  # type de pièce de la poche sélectionnée
        self.color: chess.Color | None = None  # camp au trait au moment de la sélection

    def _own(self, board: int, sq: int) -> bool:
        piece = self.game.boards[board].piece_at(sq)
        return piece is not None and piece.color == self.game.turn(board)

    # ------------------------------------------------------------------
    def click_square(self, board: int, sq: int) -> list[chess.Move]:
        g = self.game
        if g.is_over:
            self.clear()
            return []
        if self.board is not None and self.board != board:
            self.clear()  # on change de planche : on repart de zéro
        legal = g.legal_moves(board)

        if self.drop is not None:
            moves = [m for m in legal if m.drop == self.drop and m.to_square == sq]
            if moves:
                self.clear()
                return moves
            self.clear()
            if not self._own(board, sq):
                return []  # clic dans le vide : annule la sélection
            # sinon : clic sur une de ses pièces -> on bascule sur la sélection de cette pièce

        elif self.from_sq is not None:
            if sq == self.from_sq:
                self.clear()
                return []
            moves = [m for m in legal if m.drop is None and m.from_square == self.from_sq and m.to_square == sq]
            if moves:
                self.clear()
                return moves
            self.clear()

        if self._own(board, sq):
            self.board, self.from_sq, self.color = board, sq, g.turn(board)
        return []

    def click_pocket(self, board: int, color: chess.Color, piece_type: int) -> None:
        g = self.game
        if g.is_over or color != g.turn(board) or not g.pocket(board, color).get(piece_type):
            self.clear()
            return
        if self.board == board and self.drop == piece_type:
            self.clear()  # re-clic : désélectionne
            return
        self.clear()
        self.board, self.drop, self.color = board, piece_type, color

    # ------------------------------------------------------------------
    def targets(self) -> set[int]:
        """Cases d'arrivée possibles pour la sélection courante (pour les afficher)."""
        if self.board is None:
            return set()
        legal = self.game.legal_moves(self.board)
        if self.from_sq is not None:
            return {m.to_square for m in legal if m.drop is None and m.from_square == self.from_sq}
        if self.drop is not None:
            return {m.to_square for m in legal if m.drop == self.drop}
        return set()

    def validate(self) -> None:
        """Annule une sélection devenue obsolète (coup joué, undo, bot, fin de partie...)."""
        if self.board is None:
            return
        g = self.game
        if g.is_over or g.turn(self.board) != self.color:
            self.clear()
        elif self.from_sq is not None and not self._own(self.board, self.from_sq):
            self.clear()
        elif self.drop is not None and not g.pocket(self.board, self.color).get(self.drop):
            self.clear()
