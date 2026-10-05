import time

import chess
import chess.variant

from bughouse2v2 import Game, ManualTime, MinimaxPlayer, Seat, TimeControl
from bughouse2v2.minimax import BISHOP_V, KNIGHT_V, VALUES

A, B = 0, 1
START = chess.STARTING_FEN


def game_from(fen_a, fen_b=START, base=180.0, inc=0.0):
    g = Game(TimeControl(base, inc), now=ManualTime(), fens=(fen_a, fen_b))
    g.start()
    return g


def bot(**kw):
    kw.setdefault("seed", 0)
    kw.setdefault("max_time", 0.3)
    return MinimaxPlayer(**kw)


def test_knight_is_worth_twice_a_bishop():
    assert VALUES[chess.KNIGHT] == 2 * VALUES[chess.BISHOP] == KNIGHT_V == 2 * BISHOP_V


def test_takes_the_more_valuable_piece_knight_over_bishop():
    # le pion e4 peut prendre le cheval d5 ou le fou f5 : il doit prendre le cheval
    g = game_from("4k3/8/8/3n1b2/4P3/8/8/4K3 w - - 0 1")
    assert bot().choose_move(g, A) == chess.Move.from_uci("e4d5")


def test_takes_free_queen():
    g = game_from("4k3/8/8/8/3q4/8/8/3RK3 w - - 0 1")
    assert bot().choose_move(g, A) == chess.Move.from_uci("d1d4")


def test_prefers_fastest_mate():
    # Ra8# est un mat en 1 ; il doit le jouer plutôt que tout mat plus lent
    g = game_from("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
    p = bot(max_depth=5)
    assert p.choose_move(g, A) == chess.Move.from_uci("a1a8")
    assert p.last_score > 50_000


def test_avoids_hanging_queen():
    # la dame ne doit pas aller sur d5 où le pion c6 la prend
    g = game_from("4k3/8/2p5/8/8/8/3Q4/4K3 w - - 0 1")
    p = bot(max_depth=3)
    for _ in range(5):
        assert p.choose_move(g, A) != chess.Move.from_uci("d2d5")


def test_captured_piece_is_not_kept_in_own_pocket_during_search():
    # Après Cxd5 le cheval blanc ne doit pas pouvoir « se redéposer » : la pièce prise part chez le coéquipier.
    g = game_from("4k3/8/8/3p4/8/2N5/8/4K3 w - - 0 1")
    before = g.boards[A].fen()
    bot(max_depth=4).choose_move(g, A)
    assert g.boards[A].fen() == before  # la vraie partie n'a pas bougé
    assert g.pocket(A, chess.WHITE) == {} and g.pocket(A, chess.BLACK) == {}


def test_finds_mate_by_dropping_a_pocket_piece():
    # roi blanc f7, roi noir h8, dame en poche : plusieurs drops matent (Q@g7, Q@h5...), il doit en jouer un
    g = game_from("7k/5K2/8/8/8/8/8/8[Q] w - - 0 1")
    p = bot(max_depth=3)
    move = p.choose_move(g, A)
    assert move.drop == chess.QUEEN
    after = g.boards[A].copy()
    after.push(move)
    assert after.is_checkmate()
    assert p.last_score > 50_000


def test_returns_only_legal_moves_on_both_boards_and_never_mutates_game():
    g = Game(TimeControl(180, 0), now=ManualTime())
    g.start()
    p = bot(max_depth=3, max_time=0.1)
    for _ in range(12):
        for board in (A, B):
            fen = g.boards[board].fen()
            m = p.choose_move(g, board)
            assert g.boards[board].fen() == fen
            assert m in g.boards[board].legal_moves
            g.push(board, m)


def test_respects_time_budget_and_plays_faster_with_less_clock():
    g = Game(TimeControl(180, 0), now=ManualTime())
    g.start()
    p = bot(max_depth=8, max_time=0.2)
    t = time.perf_counter()
    p.choose_move(g, A)
    assert time.perf_counter() - t < 0.8
    seat = Seat(A, chess.WHITE)
    big = p.time_budget(g, seat)
    low = Game(TimeControl(4, 0), now=ManualTime())
    low.start()
    assert p.time_budget(low, seat) < big
    assert p.time_budget(low, seat) >= p.min_time


def test_minimax_team_beats_random_team():
    from bughouse2v2.players import RandomPlayer
    from bughouse2v2.sim import simulate

    wins = 0
    for seed in range(4):
        # équipe 0 = AW + BB (minimax), équipe 1 = AB + BW (aléatoire)
        players = {
            Seat(A, chess.WHITE): bot(seed=seed, max_depth=3, max_time=0.05),
            Seat(B, chess.BLACK): bot(seed=seed + 100, max_depth=3, max_time=0.05),
            Seat(A, chess.BLACK): RandomPlayer("r1", seed=seed),
            Seat(B, chess.WHITE): RandomPlayer("r2", seed=seed + 1),
        }
        game = simulate(players, control=TimeControl(60, 0), seed=seed)
        wins += game.result is not None and game.result.winner == 0
    assert wins >= 3
