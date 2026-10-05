import chess

from bughouse2v2 import Game, ManualTime, Seat, TimeControl
from bughouse2v2.interaction import Interaction

A, B = 0, 1
W, K = chess.WHITE, chess.BLACK
S = chess.parse_square


def new(fens=None):
    g = Game(TimeControl(180, 0), now=ManualTime(), fens=fens)
    g.start()
    return g, Interaction(g)


def test_select_then_move():
    g, it = new()
    assert it.click_square(A, S("e2")) == []
    assert it.from_sq == S("e2")
    assert it.targets() == {S("e3"), S("e4")}
    assert it.click_square(A, S("e4")) == [chess.Move.from_uci("e2e4")]
    assert it.board is None  # sélection effacée


def test_cannot_select_opponent_piece_or_empty_square():
    _, it = new()
    it.click_square(A, S("e7"))  # pièce noire, trait aux Blancs
    assert it.board is None
    it.click_square(A, S("e4"))  # case vide
    assert it.board is None


def test_click_same_square_deselects_and_other_own_piece_reselects():
    _, it = new()
    it.click_square(A, S("e2"))
    it.click_square(A, S("e2"))
    assert it.board is None
    it.click_square(A, S("e2"))
    assert it.click_square(A, S("g1")) == []  # clic sur une autre pièce à soi : re-sélection
    assert it.from_sq == S("g1")


def test_illegal_destination_clears_selection():
    _, it = new()
    it.click_square(A, S("e2"))
    assert it.click_square(A, S("e5")) == []
    assert it.board is None


def test_switching_board_resets_selection():
    _, it = new()
    it.click_square(A, S("e2"))
    it.click_square(B, S("d2"))
    assert (it.board, it.from_sq) == (B, S("d2"))


def test_promotion_returns_four_choices():
    fens = ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", chess.STARTING_FEN)
    _, it = new(fens)
    it.click_square(A, S("a7"))
    moves = it.click_square(A, S("a8"))
    assert sorted(m.promotion for m in moves) == [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]


def test_castling_by_clicking_king_then_g1():
    fens = ("4k3/8/8/8/8/8/8/4K2R w K - 0 1", chess.STARTING_FEN)
    _, it = new(fens)
    it.click_square(A, S("e1"))
    assert S("g1") in it.targets()
    assert it.click_square(A, S("g1")) == [chess.Move.from_uci("e1g1")]


def prepare_pawn_in_pocket():
    g, it = new()
    for m in ("e2e4", "d7d5", "e4d5"):
        g.push(A, m)
    g.push(B, "e2e4")  # c'est maintenant aux Noirs de B, qui ont reçu un pion
    return g, it


def test_drop_from_pocket():
    g, it = prepare_pawn_in_pocket()
    it.click_pocket(B, K, chess.PAWN)
    assert it.drop == chess.PAWN
    t = it.targets()
    assert S("e5") in t and S("e4") not in t  # pas sur une case occupée
    assert not any(chess.square_rank(sq) in (0, 7) for sq in t)  # pas de pion en 1re/8e rangée
    assert it.click_square(B, S("e5")) == [chess.Move.from_uci("P@e5")]


def test_pocket_click_rejected_for_wrong_side_or_empty():
    g, it = prepare_pawn_in_pocket()
    it.click_pocket(B, W, chess.PAWN)  # mauvais camp
    assert it.board is None
    it.click_pocket(B, K, chess.QUEEN)  # pièce absente de la poche
    assert it.board is None
    it.click_pocket(B, K, chess.PAWN)
    it.click_pocket(B, K, chess.PAWN)  # re-clic : désélection
    assert it.board is None


def test_click_on_empty_square_cancels_drop_but_own_piece_switches():
    g, it = prepare_pawn_in_pocket()
    it.click_pocket(B, K, chess.PAWN)
    assert it.click_square(B, S("a1")) == []  # case non légale pour un drop, pièce adverse
    assert it.board is None
    it.click_pocket(B, K, chess.PAWN)
    it.click_square(B, S("b8"))  # propre cavalier : bascule en sélection de pièce
    assert (it.from_sq, it.drop) == (S("b8"), None)


def test_validate_drops_stale_selection():
    g, it = new()
    it.click_square(A, S("e2"))
    g.push(A, "d2d4")  # le trait change (via un autre clic/bot)
    it.validate()
    assert it.board is None


def test_nothing_selectable_when_game_over():
    g, it = new()
    g.resign(Seat(A, W))
    assert it.click_square(A, S("e7")) == []
    it.click_pocket(A, W, chess.PAWN)
    assert it.board is None
