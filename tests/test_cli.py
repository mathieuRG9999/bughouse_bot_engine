import chess

from bughouse2v2 import Game, ManualTime, Seat, TimeControl
from bughouse2v2.cli import handle, parse_seat

A, B = 0, 1


def new_game():
    clock = ManualTime()
    g = Game(TimeControl(180, 0), now=clock)
    g.start()
    return g, clock


def test_uci_and_san_moves():
    g, _ = new_game()
    msg, quit_ = handle(g, "a e2e4")
    assert "AW joue e4" in msg and not quit_
    handle(g, "a e5")  # SAN
    assert g.boards[A].piece_at(chess.E5) == chess.Piece(chess.PAWN, chess.BLACK)
    handle(g, "b Nf3")
    assert g.boards[B].piece_at(chess.F3) == chess.Piece(chess.KNIGHT, chess.WHITE)


def test_capture_then_drop_via_cli():
    g, _ = new_game()
    for line in ("a e4", "a d5", "a exd5", "b e4"):
        handle(g, line)
    assert g.pocket(B, chess.BLACK) == {chess.PAWN: 1}
    msg, _ = handle(g, "b P@e5")
    assert "erreur" not in msg
    assert g.pocket(B, chess.BLACK) == {}
    assert g.boards[B].piece_at(chess.E5) == chess.Piece(chess.PAWN, chess.BLACK)


def test_errors_do_not_crash():
    g, _ = new_game()
    assert "erreur" in handle(g, "a e2e5")[0]
    assert "erreur" in handle(g, "a P@e4")[0]  # poche vide
    assert "usage" in handle(g, "a")[0]
    assert "inconnue" in handle(g, "zzz")[0]
    assert handle(g, "")[0] == ""
    assert len(g.history) == 0


def test_undo_and_moves_listing():
    g, _ = new_game()
    assert "rien" in handle(g, "undo")[0]
    handle(g, "a e4")
    assert "annulé" in handle(g, "u")[0]
    assert g.boards[A].fen() == Game(now=ManualTime()).boards[A].fen()
    assert "20 coups" in handle(g, "moves a")[0]


def test_resign_pause_quit():
    g, _ = new_game()
    handle(g, "pause")
    assert "erreur" in handle(g, "a e4")[0]
    handle(g, "resume")
    handle(g, "resign bb")
    assert g.result is not None and g.result.loser == Seat(B, chess.BLACK)
    assert handle(g, "quit")[1] is True


def test_parse_seat():
    assert parse_seat("aw") == Seat(A, chess.WHITE)
    assert parse_seat("BB") == Seat(B, chess.BLACK)
