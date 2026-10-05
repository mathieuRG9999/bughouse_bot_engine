import chess
import pytest

from bughouse2v2 import (
    Game,
    GameStateError,
    IllegalMoveError,
    ManualTime,
    Seat,
    Termination,
    TimeControl,
)
from bughouse2v2.sim import simulate

A, B = 0, 1
W, K = chess.WHITE, chess.BLACK  # K = noir (black)


def new_game(base=180.0, inc=0.0, **kw):
    clock = ManualTime()
    game = Game(TimeControl(base, inc), now=clock, **kw)
    game.start()
    return game, clock


def test_teams():
    assert Seat(A, W).team == Seat(B, K).team == 0
    assert Seat(A, K).team == Seat(B, W).team == 1
    assert Seat(A, W).partner == Seat(B, K)


def test_capture_feeds_partner_pocket():
    g, _ = new_game()
    for m in ("e2e4", "d7d5", "e4d5"):
        g.push(A, m)
    assert g.pocket(A, W) == {}  # pas dans la poche du preneur
    assert g.pocket(B, K) == {chess.PAWN: 1}  # mais chez le coéquipier (Noirs de B)


def test_partner_can_drop_received_piece():
    g, _ = new_game()
    for m in ("e2e4", "d7d5", "e4d5"):
        g.push(A, m)
    g.push(B, "e2e4")
    g.push(B, "P@e5")
    assert g.pocket(B, K) == {}
    assert g.boards[B].piece_at(chess.E5) == chess.Piece(chess.PAWN, chess.BLACK)


def test_cannot_drop_without_piece():
    g, _ = new_game()
    with pytest.raises(IllegalMoveError):
        g.push(A, "P@e4")


def test_promoted_piece_goes_back_as_pawn():
    fens = ("q~3k3/8/8/8/8/8/8/R3K3 w - - 0 1", chess.STARTING_FEN)
    g, _ = new_game(fens=fens)
    g.push(A, "a1a8")  # capture d'une dame promue
    assert g.pocket(B, K) == {chess.PAWN: 1}


def test_clocks_run_in_parallel_on_both_boards():
    g, clock = new_game(base=100)
    clock.advance(5)
    g.push(A, "e2e4")
    assert g.time_left(Seat(A, W)) == 95
    assert g.time_left(Seat(B, W)) == 95  # l'horloge des Blancs de B tourne toujours
    clock.advance(3)
    assert g.time_left(Seat(A, K)) == 97
    assert g.time_left(Seat(B, W)) == 92
    assert g.time_left(Seat(A, W)) == 95  # à l'arrêt


def test_increment():
    g, clock = new_game(base=100, inc=2)
    clock.advance(5)
    g.push(A, "e2e4")
    assert g.time_left(Seat(A, W)) == 97


def test_timeout_ends_game():
    g, clock = new_game(base=10)
    clock.advance(4)
    g.push(A, "e2e4")
    clock.advance(7)  # Blancs de B : 10 - 11 = -1
    res = g.check_time()
    assert res.reason is Termination.TIMEOUT
    assert res.loser == Seat(B, W)
    assert res.winner == 0  # Blancs de B sont dans l'équipe 1
    with pytest.raises(GameStateError):
        g.push(B, "e2e4")


def test_push_after_flag_is_rejected():
    g, clock = new_game(base=10)
    clock.advance(11)
    with pytest.raises(GameStateError):
        g.push(A, "e2e4")
    assert g.is_over


def test_checkmate_and_undo_reopens_game():
    g, _ = new_game()
    for m in ("f2f3", "e7e5", "g2g4", "d8h4"):
        g.push(A, m)
    assert g.result.reason is Termination.CHECKMATE
    assert g.result.winner == Seat(A, K).team == 1
    assert g.undo().san == "Qh4#"
    assert g.result is None
    g.push(A, "a7a6")  # la partie peut reprendre


def test_undo_restores_positions_pockets_and_clocks():
    g, clock = new_game(base=100, inc=1)
    plan = [(A, "e2e4"), (A, "d7d5"), (A, "e4d5"), (B, "e2e4"), (B, "P@e5"), (A, "d8d5")]
    states = []
    for board, move in plan:
        clock.advance(2)
        states.append(
            (
                g.boards[A].fen(),
                g.boards[B].fen(),
                {s: g.time_left(s) for s in (Seat(a, c) for a in (A, B) for c in (W, K))},
            )
        )
        g.push(board, move)
    for expected in reversed(states):
        assert g.undo() is not None
        got = (
            g.boards[A].fen(),
            g.boards[B].fen(),
            {s: g.time_left(s) for s in expected[2]},
        )
        assert got == expected
    assert g.undo() is None


def test_pause_freezes_clocks_and_blocks_moves():
    g, clock = new_game(base=100)
    g.pause()
    clock.advance(50)
    assert g.time_left(Seat(A, W)) == 100
    with pytest.raises(GameStateError):
        g.push(A, "e2e4")
    g.resume()
    clock.advance(1)
    assert g.time_left(Seat(A, W)) == 99


def test_resign():
    g, _ = new_game()
    res = g.resign(Seat(A, W))
    assert res.reason is Termination.RESIGNATION and res.winner == 1


@pytest.mark.parametrize("seed", range(5))
def test_random_game_then_undo_everything(seed):
    start = Game(now=ManualTime())
    g = simulate(seed=seed)
    assert g.is_over and g.history
    # l'undo rembobine les horloges à l'instant du 1er coup (temps de réflexion déjà écoulé)
    first_clocks = g.history[0].clocks_before.remaining
    while g.undo():
        pass
    assert g.result is None
    assert g.boards[A].fen() == start.boards[A].fen()
    assert g.boards[B].fen() == start.boards[B].fen()
    assert {s: g.time_left(s) for s in first_clocks} == first_clocks
    assert all(0 < t <= 180 for t in first_clocks.values())
