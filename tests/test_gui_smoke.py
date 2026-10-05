"""Test de fumée de la vraie fenêtre tkinter. Ignoré s'il n'y a ni tkinter ni écran
(sous Linux sans affichage : xvfb-run -a python -m pytest)."""
import chess
import chess.variant
import pytest

tk = pytest.importorskip("tkinter")

from bughouse2v2 import Seat, TimeControl  # noqa: E402
from bughouse2v2.gui import App  # noqa: E402

A, B = 0, 1
S = chess.parse_square


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("pas d'écran disponible")
    root.withdraw()
    a = App(root, TimeControl(60, 0))
    yield a
    root.destroy()


def click(app, board, sq):
    app.on_square(board, S(sq))
    app.root.update()


def test_play_undo_and_drop_with_clicks(app):
    click(app, A, "e2"), click(app, A, "e4")
    assert [e.san for e in app.game.history] == ["e4"]
    click(app, A, "d7"), click(app, A, "d5")
    click(app, A, "e4"), click(app, A, "d5")  # capture -> pion pour BB
    assert app.game.pocket(B, chess.BLACK) == {chess.PAWN: 1}
    click(app, B, "e2"), click(app, B, "e4")
    app.on_pocket(B, chess.BLACK, chess.PAWN)
    click(app, B, "e5")
    assert app.game.history[-1].san == "@e5"
    assert app.game.pocket(B, chess.BLACK) == {}
    for _ in range(6):
        app.undo()
    assert app.game.history == []
    assert app.game.boards[A].fen() == chess.variant.CrazyhouseBoard().fen()


def test_promotion_dialog_choice_is_used(app):
    app.game.boards[A].set_fen("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    app.ask_promotion = lambda board, moves: next(m for m in moves if m.promotion == chess.KNIGHT)
    click(app, A, "a7"), click(app, A, "a8")
    assert app.game.history[-1].san.startswith("a8=N")


def test_bots_play_and_pause_stops_them(app):
    app.delay_var.set(0.0)
    for v in app.bot_vars.values():
        v.set(True)
    for _ in range(30):
        app.run_bots()
    n = len(app.game.history)
    assert n > 0
    app.toggle_pause()
    for _ in range(10):
        app.run_bots()
    assert len(app.game.history) == n
    click(app, A, "e2")  # clic ignoré : c'est le tour d'un bot
    assert app.inter.board is None


def test_new_game_resets_and_invalid_time_is_rejected(app):
    click(app, A, "e2"), click(app, A, "e4")
    app.base_var.set("abc")
    app.new_game()
    assert app.game.time_control.base == 60 and app.game.history == []
    app.base_var.set("30")
    app.new_game()
    assert app.game.time_control.base == 30


def test_resign_shows_result(app):
    app.resign(Seat(A, chess.WHITE))
    assert "TERMINÉE" in app.state_var.get()
    click(app, A, "e7")
    assert app.inter.board is None
