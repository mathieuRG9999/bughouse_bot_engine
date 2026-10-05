"""Interface des joueurs/bots + un joueur aléatoire (le point de départ de ton bot)."""
from __future__ import annotations

import random
from typing import Protocol

import chess

from .game import Game


class Player(Protocol):
    name: str

    def choose_move(self, game: Game, board: int) -> chess.Move:
        """Appelé quand ce joueur est au trait sur ``board`` et a au moins un coup légal.

        Le bot peut lire tout l'état : ``game.boards``, ``game.pocket(...)``,
        ``game.time_left(...)``, ``game.history``.
        """
        ...


class RandomPlayer:
    def __init__(self, name: str = "random", seed: int | None = None) -> None:
        self.name = name
        self._rng = random.Random(seed)

    def choose_move(self, game: Game, board: int) -> chess.Move:
        return self._rng.choice(game.legal_moves(board))
