"""Bot minimax (négamax + élagage alpha-bêta + approfondissement itératif).

Règles de valeur voulues :
  - un cheval vaut 2 fois un fou (KNIGHT = 2 * BISHOP) ;
  - jouer vite est récompensé, de trois façons :
      1. un gain obtenu 1 coup plus tard vaut GAMMA fois moins (0.9) -> le bot préfère
         capturer / mater tout de suite plutôt que « plus tard peut-être » ;
      2. conséquence : un mat en 1 vaut plus qu'un mat en 3 ;
      3. le bot réfléchit peu : son budget par coup est une petite fraction de son horloge
         (temps restant / MOVES_TO_GO + incrément), donc il garde de l'avance au temps.

Spécificité bughouse : une pièce que je capture part chez mon COÉQUIPIER (pas dans ma poche).
Dans la recherche je la retire donc de ma poche, et je compte tout de même un bonus
(HAND_BONUS) car elle servira à mon équipe ; inversement quand l'adversaire me capture.
"""
from __future__ import annotations

import math
import random
import time

import chess

from .game import Game
from .seat import Seat

PAWN_V, BISHOP_V = 100, 150
KNIGHT_V = 2 * BISHOP_V  # <- la règle : cheval = 2 fous
VALUES = {
    chess.PAWN: PAWN_V,
    chess.BISHOP: BISHOP_V,
    chess.KNIGHT: KNIGHT_V,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}
MATE = 100_000.0


class _Timeout(Exception):
    pass


def _victim(board: chess.Board, move: chess.Move) -> int | None:
    """Type de la pièce capturée par ``move`` (une pièce promue redevient un pion)."""
    if move.drop:
        return None
    if board.is_en_passant(move):
        return chess.PAWN
    piece = board.piece_at(move.to_square)
    if piece is None:
        return None
    return chess.PAWN if board.promoted & chess.BB_SQUARES[move.to_square] else piece.piece_type


class MinimaxPlayer:
    def __init__(
        self,
        name: str = "minimax",
        seed: int | None = None,
        *,
        max_depth: int = 6,
        gamma: float = 0.9,  # valeur d'un gain obtenu un coup plus tard (1.0 = pas de récompense de la vitesse)
        hand_bonus: float = 0.5,  # une pièce capturée vaut (1 + hand_bonus) fois sa valeur : elle part chez le coéquipier
        moves_to_go: int = 40,  # budget par coup = temps restant / moves_to_go + 0.8 * incrément
        min_time: float = 0.05,
        max_time: float = 1.0,
        f_pawn_weight: float = 40.0,  # poids de la protection du pion f2/f7 (100 = un pion)
    ) -> None:
        self.name = name
        self.max_depth, self.gamma, self.hand_bonus = max_depth, gamma, hand_bonus
        self.moves_to_go, self.min_time, self.max_time = moves_to_go, min_time, max_time
        self._rng = random.Random(seed)
        self.last_depth = 0  # profondeur atteinte au dernier coup (pour le debug)
        self.last_score = 0.0
        self.nodes = 0
        self.f_pawn_weight = f_pawn_weight
    # ------------------------------------------------------------------
    # Interface Player
    # ------------------------------------------------------------------
    def choose_move(self, game: Game, board: int) -> chess.Move:
        seat = Seat(board, game.turn(board))
        b = game.boards[board].copy(stack=False)  # copie jetable : on ne touche pas à la vraie partie
        legal = list(b.legal_moves)
        if len(legal) == 1:
            return legal[0]

        budget = self.time_budget(game, seat)
        start = time.perf_counter()
        self._deadline = math.inf
        self.nodes = 0
        best, self.last_depth = self._rng.choice(legal), 0
        for depth in range(1, self.max_depth + 1):
            if depth > 1:
                self._deadline = start + budget
            try:
                best, self.last_score = self._root(b, depth, best)
            except _Timeout:
                break
            self.last_depth = depth
            if abs(self.last_score) > MATE / 2 or time.perf_counter() - start > budget / 2:
                break  # mat trouvé, ou l'itération suivante ne tiendrait pas dans le budget
        return best

    def time_budget(self, game: Game, seat: Seat) -> float:
        """Réfléchir peu : une petite fraction de l'horloge restante."""
        raw = game.time_left(seat) / self.moves_to_go + 0.8 * game.time_control.increment
        return max(self.min_time, min(self.max_time, raw))

    # ------------------------------------------------------------------
    # Recherche
    # ------------------------------------------------------------------
    def _f_pawn_safety(self, board: chess.Board, color: chess.Color) -> float:
        """Protection de f2/f7, neutralisée en configuration de roque.

        La position des pièces suffit : aucun historique de roque n'est requis,
        ce qui fonctionne aussi sur les copies de recherche sans pile de coups.
        """
        rank = 0 if color == chess.WHITE else 7
        king_square = board.king(color)
        for king_file, rook_file in ((6, 5), (2, 3)):
            if king_square == chess.square(king_file, rank):
                rook = board.piece_at(chess.square(rook_file, rank))
                if rook is not None and rook.piece_type == chess.ROOK and rook.color == color:
                    return 0.0

        sq = chess.F2 if color == chess.WHITE else chess.F7
        p = board.piece_at(sq)
        if p is None or p.piece_type != chess.PAWN or p.color != color:
            return -self.f_pawn_weight
        defenders = len(board.attackers(color, sq))
        attackers = len(board.attackers(not color, sq))
        return self.f_pawn_weight * (min(defenders, 3) - attackers)

    def _center_score(self, board: chess.Board, color: chess.Color) -> float:
        """Occupation et contrôle géométrique de d4/e4/d5/e5."""
        score = 0.0
        for square in (chess.D4, chess.E4, chess.D5, chess.E5):
            piece = board.piece_at(square)
            if piece is not None and piece.color == color:
                if piece.piece_type == chess.PAWN:
                    score += 20
                elif piece.piece_type in (chess.KNIGHT, chess.BISHOP):
                    score += 12
            for origin in board.attackers(color, square):
                attacker = board.piece_at(origin)
                if attacker.piece_type == chess.PAWN:
                    score += 8
                elif attacker.piece_type in (chess.KNIGHT, chess.BISHOP):
                    score += 5
                elif attacker.piece_type in (chess.ROOK, chess.QUEEN):
                    score += 2
        return score

    def _eval(self, board: chess.Board) -> float:
        """Évaluation à l'horizon, du point de vue du camp au trait (négamax)."""
        me = board.turn
        king_safety = self._f_pawn_safety(board, me) - self._f_pawn_safety(board, not me)
        center = self._center_score(board, me) - self._center_score(board, not me)
        return 2 * king_safety + center

    def _gain(self, move: chess.Move, victim: int | None) -> float:
        g = VALUES[victim] * (1 + self.hand_bonus) if victim else 0.0
        if move.promotion:
            g += VALUES[move.promotion] - PAWN_V
        return g

    @staticmethod
    def _push(board: chess.Board, move: chess.Move, victim: int | None) -> None:
        mover = board.turn
        board.push(move)
        if victim is not None:  # python-chess crédite le preneur ; en bughouse la pièce part chez le coéquipier
            board.pockets[mover].remove(victim)

    def _ordered(self, board: chess.Board, first: chess.Move | None = None, shuffle: bool = False):
        out = []
        for m in board.legal_moves:
            v = _victim(board, m)
            if m == first:
                score = 10**9
            elif v:
                score = 10_000 + 10 * VALUES[v] - VALUES[board.piece_at(m.from_square).piece_type]
            elif m.promotion:
                score = 5_000 + VALUES[m.promotion]
            else:
                score = 0
            out.append((-score, self._rng.random() if shuffle else 0.0, m, v))
        out.sort(key=lambda t: (t[0], t[1]))
        return [(m, v) for _, _, m, v in out]

    def _root(self, board: chess.Board, depth: int, first: chess.Move) -> tuple[chess.Move, float]:
        g, alpha = self.gamma, -math.inf
        best_move, best_val = first, -math.inf
        for move, victim in self._ordered(board, first, shuffle=True):
            gain = self._gain(move, victim)
            self._push(board, move, victim)
            c = self._search(board, depth - 1, (gain - math.inf) / g, (gain - alpha) / g)
            board.pop()
            v = gain - g * c
            if v > best_val:
                best_move, best_val = move, v
            alpha = max(alpha, v)
        return best_move, best_val

    def _search(self, board: chess.Board, depth: int, alpha: float, beta: float) -> float:
        """Valeur du point de vue du camp au trait. Gain d'un coup = prise (x bonus) + promotion ;
        la valeur d'un nœud = max(gain - gamma * valeur_enfant) -> les gains tardifs comptent moins."""
        self.nodes += 1
        if self.nodes & 255 == 0 and time.perf_counter() > self._deadline:
            raise _Timeout
        if depth == 0:
            if board.is_check() and not any(board.legal_moves):
                return -MATE
            return self._eval(board)
        moves = self._ordered(board)
        if not moves:  # mat (ou pat : en bughouse on attend simplement une pièce, pas de nulle)
            return -MATE if board.is_check() else 0.0
        g, best = self.gamma, -math.inf
        for move, victim in moves:
            gain = self._gain(move, victim)
            self._push(board, move, victim)
            c = self._search(board, depth - 1, (gain - beta) / g, (gain - alpha) / g)
            board.pop()
            v = gain - g * c
            if v > best:
                best = v
                if best > alpha:
                    alpha = best
                    if alpha >= beta:
                        break
        return best
