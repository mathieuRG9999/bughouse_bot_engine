"""Interface graphique tkinter : les deux planches, les poches, les 4 horloges, undo, bots.

    python play_gui.py
    python play_gui.py --bots BW,BB --base 120 --increment 1

Jouer : clic sur une de tes pièces puis sur la case d'arrivée (les coups possibles sont
marqués). Pour poser une pièce de ta poche : clic sur la pièce dans la poche, puis sur une
case libre. Ctrl+Z annule le dernier coup. Cocher « Bot » à côté d'une place la fait jouer
par ``RandomPlayer`` (ou par le joueur que tu passes à ``App(players=...)``).
"""
from __future__ import annotations
import os

if __package__ in (None, ""):  # lancé comme un simple script (python gui.py, bouton « Run » d'un IDE)
    import os
    import runpy
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        runpy.run_module("bughouse2v2.gui", run_name="__main__")
    except ImportError as exc:
        if getattr(exc, "name", None) == "chess":
            raise SystemExit("Il manque la bibliothèque chess : pip install -r requirements.txt")
        if "bughouse2v2" in str(exc):
            raise SystemExit("Les fichiers doivent rester dans un dossier nommé bughouse2v2/ (avec __init__.py).")
        raise
    raise SystemExit

import argparse
import platform
import random

try:
    import tkinter as tk
except ImportError:  # tkinter est une option d'installation de Python sous Linux
    raise SystemExit(
        "tkinter est introuvable. Linux : sudo apt install python3-tk. "
        "Windows/macOS : réinstalle Python depuis python.org en gardant « tcl/tk » coché."
    )

import chess


from .clock import TimeControl, monotonic
from .game import BughouseError, Game, HistoryEntry
from .interaction import Interaction
from .players import Player, RandomPlayer
from .minimax import MinimaxPlayer
from .seat import ALL_SEATS, Seat

SQUARE = 56  # taille d'une case en pixels
LIGHT, DARK = "#f0d9b5", "#b58863"
SELECT_COLOR, CHECK_COLOR = "#f6f669", "#e8575a"
LAST_LIGHT, LAST_DARK = "#cdd26a", "#aaa23a"
TARGET_COLOR = "#4f6f3a"
CLOCK_ON, CLOCK_OFF, CLOCK_LOW = "#ffe08a", "#eeeeee", "#ff9b9b"

PIECE_FONT = {"Windows": "Segoe UI Symbol", "Darwin": "Apple Symbols"}.get(platform.system(), "DejaVu Sans")
GLYPH_FILLED = {chess.PAWN: "♟", chess.KNIGHT: "♞", chess.BISHOP: "♝", chess.ROOK: "♜", chess.QUEEN: "♛", chess.KING: "♚"}
GLYPH_HOLLOW = {chess.PAWN: "♙", chess.KNIGHT: "♘", chess.BISHOP: "♗", chess.ROOK: "♖", chess.QUEEN: "♕", chess.KING: "♔"}
POCKET_ORDER = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN)
BOT_TYPES = {"Aléatoire": RandomPlayer, "Minimax": MinimaxPlayer}


def format_time(t: float) -> str:
    tenths = max(0, round(t * 10))
    minutes, tenths = divmod(tenths, 600)
    return f"{minutes}:{tenths / 10:04.1f}"


def team_name(team: int) -> str:
    return "AW+BB" if team == 0 else "AB+BW"


def describe(entry: HistoryEntry) -> str:
    extra = f"  (envoie {GLYPH_HOLLOW[entry.captured]} à {entry.seat.partner})" if entry.captured else ""
    return f"{entry.seat} {entry.san}{extra}"


class SeatBar:
    """Bandeau d'un joueur : nom, horloge et poche cliquable."""

    def __init__(self, app: "App", parent: tk.Widget, seat: Seat) -> None:
        self.app, self.seat = app, seat
        self.frame = tk.Frame(parent, bd=1, relief=tk.SOLID, padx=4, pady=2)
        self.title = tk.Label(self.frame, anchor="w", font=("TkDefaultFont", 10, "bold"))
        self.clock = tk.Label(self.frame, width=7, font=("Courier", 16, "bold"))
        self.pocket = tk.Frame(self.frame)
        self.title.pack(side=tk.LEFT)
        self.clock.pack(side=tk.LEFT, padx=8)
        self.pocket.pack(side=tk.LEFT)
        self._sig: object = None

    def update(self) -> None:
        app, g, seat = self.app, self.app.game, self.seat
        t = g.time_left(seat)
        running = seat in g.active_seats and not g.clocks.paused
        self.clock.config(
            text=format_time(t),
            bg=(CLOCK_LOW if t < 10 and running else CLOCK_ON if running else CLOCK_OFF),
        )
        name = "Blancs" if seat.color == chess.WHITE else "Noirs"
        bot = " [bot]" if app.bot_vars[seat].get() else ""
        blocked = " — bloqué, attend une pièce" if running and g.is_blocked(seat.board) else ""
        self.title.config(text=f"{seat} {name}{bot}{blocked}")

        pocket = g.pocket(seat.board, seat.color)
        inter = app.inter
        picked = inter.drop if (inter.board == seat.board and inter.color == seat.color) else None
        can_drop = (not g.is_over) and g.turn(seat.board) == seat.color
        sig = (tuple(sorted(pocket.items())), picked, can_drop)
        if sig == self._sig:
            return
        self._sig = sig
        for w in self.pocket.winfo_children():
            w.destroy()
        for pt in POCKET_ORDER:
            n = pocket.get(pt)
            if not n:
                continue
            glyph = GLYPH_FILLED[pt] if seat.color == chess.BLACK else GLYPH_HOLLOW[pt]
            tk.Button(
                self.pocket,
                text=f"{glyph}{n}",
                font=(PIECE_FONT, 16),
                padx=3,
                pady=0,
                state=tk.NORMAL if can_drop else tk.DISABLED,
                bg=SELECT_COLOR if pt == picked else "#f4f4f4",
                relief=tk.SUNKEN if pt == picked else tk.RAISED,
                command=lambda pt=pt: app.on_pocket(seat.board, seat.color, pt),
            ).pack(side=tk.LEFT, padx=1)


class BoardView:
    def __init__(self, app: "App", parent: tk.Widget, idx: int, flipped: bool) -> None:
        self.app, self.idx, self.flipped = app, idx, flipped
        self.frame = tk.Frame(parent, padx=6, pady=4)
        head = tk.Frame(self.frame)
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text=f"Planche {'AB'[idx]}", font=("TkDefaultFont", 11, "bold")).pack(side=tk.LEFT)
        tk.Button(head, text="⟲ retourner", command=self.flip).pack(side=tk.RIGHT)
        self.bars = {c: SeatBar(app, self.frame, Seat(idx, c)) for c in (chess.WHITE, chess.BLACK)}
        side = 8 * SQUARE
        self.canvas = tk.Canvas(self.frame, width=side, height=side, highlightthickness=0)
        self.canvas.grid(row=2, column=0, pady=3)
        self.canvas.bind("<Button-1>", self.on_click)
        self._sig: object = None
        self.place_bars()

    def place_bars(self) -> None:
        top = chess.WHITE if self.flipped else chess.BLACK
        self.bars[top].frame.grid(row=1, column=0, sticky="ew")
        self.bars[not top].frame.grid(row=3, column=0, sticky="ew")

    def flip(self) -> None:
        self.flipped = not self.flipped
        self.place_bars()
        self._sig = None
        self.update()

    # --- géométrie -----------------------------------------------------
    def xy(self, sq: int) -> tuple[int, int]:
        f, r = chess.square_file(sq), chess.square_rank(sq)
        return ((7 - f) * SQUARE, r * SQUARE) if self.flipped else (f * SQUARE, (7 - r) * SQUARE)

    def on_click(self, ev: tk.Event) -> None:
        col, row = ev.x // SQUARE, ev.y // SQUARE
        if not (0 <= col < 8 and 0 <= row < 8):
            return
        f, r = (7 - col, row) if self.flipped else (col, 7 - row)
        self.app.on_square(self.idx, chess.square(f, r))

    # --- dessin --------------------------------------------------------
    def update(self) -> None:
        for bar in self.bars.values():
            bar.update()
        g, inter = self.app.game, self.app.inter
        board = g.boards[self.idx]
        mine = inter.board == self.idx
        sig = (board.fen(), len(g.history), (inter.from_sq, inter.drop) if mine else None, self.flipped, g.is_over)
        if sig == self._sig:
            return
        self._sig = sig
        self.draw(mine)

    def draw(self, mine: bool) -> None:
        g, inter = self.app.game, self.app.inter
        board, c = g.boards[self.idx], self.canvas
        c.delete("all")
        targets = inter.targets() if mine else set()
        selected = inter.from_sq if mine else None
        last = next((e for e in reversed(g.history) if e.seat.board == self.idx), None)
        last_sqs = set() if last is None else {last.move.to_square} | (
            set() if last.move.drop else {last.move.from_square}
        )
        king_in_check = board.king(board.turn) if board.is_check() else None

        for sq in chess.SQUARES:
            x, y = self.xy(sq)
            light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
            color = LIGHT if light else DARK
            if sq in last_sqs:
                color = LAST_LIGHT if light else LAST_DARK
            if sq == selected:
                color = SELECT_COLOR
            if sq == king_in_check:
                color = CHECK_COLOR
            c.create_rectangle(x, y, x + SQUARE, y + SQUARE, fill=color, outline=color)
            piece = board.piece_at(sq)
            if piece:
                self._piece(x, y, piece)
            if sq in targets:
                m, r = SQUARE // 2, SQUARE // 7
                if piece:
                    c.create_oval(x + 3, y + 3, x + SQUARE - 3, y + SQUARE - 3, outline=TARGET_COLOR, width=4)
                else:
                    c.create_oval(x + m - r, y + m - r, x + m + r, y + m + r, fill=TARGET_COLOR, outline="")
            tint = DARK if light else LIGHT
            if (self.flipped and chess.square_rank(sq) == 7) or (not self.flipped and chess.square_rank(sq) == 0):
                c.create_text(x + SQUARE - 7, y + SQUARE - 8, text="abcdefgh"[chess.square_file(sq)], fill=tint, font=("TkDefaultFont", 8, "bold"))
            if (self.flipped and chess.square_file(sq) == 7) or (not self.flipped and chess.square_file(sq) == 0):
                c.create_text(x + 7, y + 8, text=str(chess.square_rank(sq) + 1), fill=tint, font=("TkDefaultFont", 8, "bold"))

    def _piece(self, x: int, y: int, piece: chess.Piece) -> None:
        cx, cy = x + SQUARE // 2, y + SQUARE // 2 + 1
        font = (PIECE_FONT, -int(SQUARE * 0.78))
        glyph = GLYPH_FILLED[piece.piece_type]
        fill, edge = ("#ffffff", "#1a1a1a") if piece.color == chess.WHITE else ("#161616", "#e8e8e8")
        for dx, dy in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            self.canvas.create_text(cx + dx, cy + dy, text=glyph, font=font, fill=edge)
        self.canvas.create_text(cx, cy, text=glyph, font=font, fill=fill)


class App:
    TICK_MS = 100

    def __init__(
        self,
        root: tk.Tk,
        control: TimeControl = TimeControl(180.0, 0.0),
        *,
        bots: set[Seat] | frozenset[Seat] = frozenset(),
        bot_type: str = "Aléatoire",
    ) -> None:
        self.root = root
        self.bot_type = {s: tk.StringVar(value=bot_type) for s in ALL_SEATS}
        self.players: dict[Seat, Player] = {s: BOT_TYPES[bot_type](f"bot-{s}") for s in ALL_SEATS}
        self.bot_vars = {s: tk.BooleanVar(value=s in bots) for s in ALL_SEATS}
        self.base_var = tk.StringVar(value=f"{control.base:g}")
        self.inc_var = tk.StringVar(value=f"{control.increment:g}")
        self.delay_var = tk.DoubleVar(value=0.8)
        self.msg_var = tk.StringVar(value="")
        self.state_var = tk.StringVar(value="")
        self.ready: dict[int, float | None] = {0: None, 1: None}
        self._log_sig: object = None
        self.game = Game(control, now=monotonic)
        self.inter = Interaction(self.game)

        root.title("Bughouse 2v2")
        self._build()
        self.new_game()
        root.bind("<Control-z>", lambda _e: self.undo())
        self._tick()

    # ------------------------------------------------------------------
    # Construction de la fenêtre
    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = self.root
        bar = tk.Frame(root)
        bar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(6, 0))
        tk.Label(bar, text="Base (s)").pack(side=tk.LEFT)
        tk.Entry(bar, textvariable=self.base_var, width=5).pack(side=tk.LEFT, padx=(2, 8))
        tk.Label(bar, text="Incr. (s)").pack(side=tk.LEFT)
        tk.Entry(bar, textvariable=self.inc_var, width=4).pack(side=tk.LEFT, padx=(2, 8))
        tk.Button(bar, text="Nouvelle partie", command=self.new_game).pack(side=tk.LEFT, padx=2)
        tk.Button(bar, text="↶ Annuler (Ctrl+Z)", command=self.undo).pack(side=tk.LEFT, padx=2)
        self.pause_btn = tk.Button(bar, text="⏸ Pause", width=10, command=self.toggle_pause)
        self.pause_btn.pack(side=tk.LEFT, padx=2)
        mb = tk.Menubutton(bar, text="Abandon ▾", relief=tk.RAISED)
        menu = tk.Menu(mb, tearoff=0)
        for seat in ALL_SEATS:
            menu.add_command(label=f"{seat} abandonne", command=lambda s=seat: self.resign(s))
        mb.config(menu=menu)
        mb.pack(side=tk.LEFT, padx=2)

        bots = tk.Frame(root)
        bots.pack(side=tk.TOP, fill=tk.X, padx=6)
        for seat in ALL_SEATS:
            tk.Checkbutton(bots, text=f"Bot {seat}", variable=self.bot_vars[seat], command=self._bots_changed).pack(side=tk.LEFT)
            tk.OptionMenu(
                bots, self.bot_type[seat], *BOT_TYPES,
                command=lambda _v, s=seat: self._bot_type_changed(s),
            ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(bots, text="  délai bots (s)").pack(side=tk.LEFT)
        tk.Scale(bots, variable=self.delay_var, from_=0.0, to=3.0, resolution=0.1, orient=tk.HORIZONTAL, length=120).pack(side=tk.LEFT)
        tk.Label(bots, text="   Équipes : AW+BB  contre  AB+BW", fg="#555555").pack(side=tk.LEFT)

        mid = tk.Frame(root)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.boards = [BoardView(self, mid, 0, flipped=False), BoardView(self, mid, 1, flipped=True)]
        for bv in self.boards:
            bv.frame.pack(side=tk.LEFT, anchor="n")

        side = tk.Frame(mid, padx=4, pady=8)
        side.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(side, text="Coups", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        box = tk.Frame(side)
        box.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(box, width=30, height=24, state=tk.DISABLED, font=("Courier", 10), wrap="none")
        scroll = tk.Scrollbar(box, command=self.log.yview)
        self.log.config(yscrollcommand=scroll.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.LEFT, fill=tk.Y)

        status = tk.Frame(root, bd=1, relief=tk.SUNKEN)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Label(status, textvariable=self.state_var, anchor="w", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=6)
        tk.Label(status, textvariable=self.msg_var, anchor="w").pack(side=tk.LEFT, padx=6)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def say(self, text: str) -> None:
        self.msg_var.set(text)

    def new_game(self) -> None:
        try:
            control = TimeControl(float(self.base_var.get()), float(self.inc_var.get()))
            if control.base <= 0 or control.increment < 0:
                raise ValueError
        except ValueError:
            self.say("durée invalide (base > 0, incrément ≥ 0) — ancienne cadence conservée")
            control = self.game.time_control
        self.game = Game(control, now=monotonic)
        self.game.start()
        self.inter = Interaction(self.game)
        self.ready = {0: None, 1: None}
        self._log_sig = None
        for bv in self.boards:
            bv._sig = None
            for b in bv.bars.values():
                b._sig = None
        self.say("nouvelle partie")
        self.refresh()

    def undo(self) -> None:
        entry = self.game.undo()
        self.inter.clear()
        self.ready = {0: None, 1: None}
        self.say(f"annulé : {entry.seat} {entry.san}" if entry else "rien à annuler")
        self.refresh()

    def _bot_type_changed(self, seat: Seat) -> None:
        self.players[seat] = BOT_TYPES[self.bot_type[seat].get()](f"bot-{seat}")
        self.ready = {0: None, 1: None}

    def toggle_pause(self) -> None:
        try:
            if self.game.clocks.paused:
                self.game.resume()
            else:
                self.game.pause()
        except BughouseError as exc:
            self.say(str(exc))
        self.refresh()

    def resign(self, seat: Seat) -> None:
        try:
            self.game.resign(seat)
        except BughouseError as exc:
            self.say(str(exc))
        self.inter.clear()
        self.refresh()

    def _bots_changed(self) -> None:
        self.ready = {0: None, 1: None}
        self.refresh()

    def _is_bot_turn(self, board: int) -> bool:
        return self.bot_vars[Seat(board, self.game.turn(board))].get()

    def on_square(self, board: int, sq: int) -> None:
        if self._is_bot_turn(board):
            self.say(f"c'est au tour d'un bot sur la planche {'AB'[board]}")
            return
        moves = self.inter.click_square(board, sq)
        if moves:
            move = moves[0] if len(moves) == 1 else self.ask_promotion(board, moves)
            if move is not None:
                self.play(board, move)
        self.refresh()

    def on_pocket(self, board: int, color: chess.Color, piece_type: int) -> None:
        if not self._is_bot_turn(board):
            self.inter.click_pocket(board, color, piece_type)
        self.refresh()

    def play(self, board: int, move: chess.Move) -> None:
        try:
            self.say(describe(self.game.push(board, move)))
        except BughouseError as exc:
            self.say(str(exc))
        self.inter.clear()

    def ask_promotion(self, board: int, moves: list[chess.Move]) -> chess.Move | None:
        color = self.game.turn(board)
        top = tk.Toplevel(self.root)
        top.title("Promotion")
        top.transient(self.root)
        top.resizable(False, False)
        choice: dict[str, chess.Move] = {}

        def pick(m: chess.Move) -> None:
            choice["move"] = m
            top.destroy()

        glyphs = GLYPH_FILLED if color == chess.BLACK else GLYPH_HOLLOW
        tk.Label(top, text="Promouvoir en :").pack(padx=10, pady=(8, 2))
        row = tk.Frame(top)
        row.pack(padx=10, pady=8)
        for m in sorted(moves, key=lambda m: -(m.promotion or 0)):
            tk.Button(row, text=glyphs[m.promotion], font=(PIECE_FONT, 26), command=lambda m=m: pick(m)).pack(side=tk.LEFT, padx=2)
        top.grab_set()
        self.root.wait_window(top)
        return choice.get("move")

    # ------------------------------------------------------------------
    # Boucle
    # ------------------------------------------------------------------
    def run_bots(self) -> None:
        g = self.game
        now = monotonic()
        for b in (0, 1):
            seat = Seat(b, g.turn(b))
            if g.is_over or g.clocks.paused or not self.bot_vars[seat].get() or g.is_blocked(b):
                self.ready[b] = None
            elif self.ready[b] is None:
                self.ready[b] = now + self.delay_var.get() * random.uniform(0.5, 1.5)
            elif now >= self.ready[b]:
                self.ready[b] = None
                try:
                    self.say("[bot] " + describe(g.push(b, self.players[seat].choose_move(g, b))))
                except BughouseError:
                    pass

    def _tick(self) -> None:
        try:
            self.game.check_time()
            self.run_bots()
            self.refresh()
        finally:
            self.root.after(self.TICK_MS, self._tick)

    def refresh(self) -> None:
        g = self.game
        self.inter.validate()
        for bv in self.boards:
            bv.update()
        self._update_log()
        self.pause_btn.config(text="▶ Reprendre" if g.clocks.paused else "⏸ Pause", state=tk.DISABLED if g.is_over else tk.NORMAL)
        if g.is_over:
            r = g.result
            self.state_var.set(f"TERMINÉE — {team_name(r.winner)} gagne ({r.reason.value}, perdant : {r.loser})")
        else:
            self.state_var.set("PAUSE" if g.clocks.paused else "En cours")

    def _update_log(self) -> None:
        hist = self.game.history
        sig = (len(hist), id(hist[-1]) if hist else None)
        if sig == self._log_sig:
            return
        self._log_sig = sig
        lines = []
        for e in hist:
            cap = f"  +{GLYPH_HOLLOW[e.captured]}→{e.seat.partner}" if e.captured else ""
            lines.append(f"{e.ply:3d}. {e.seat}  {e.san}{cap}")
        self.log.config(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.insert(tk.END, "\n".join(lines))
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)


def main(argv: list[str] | None = None) -> None:
    from .cli import parse_seat

    ap = argparse.ArgumentParser(description="Bughouse 2v2 — interface graphique")
    ap.add_argument("--base", type=float, default=180.0, help="secondes par joueur (défaut 180)")
    ap.add_argument("--increment", type=float, default=0.0, help="incrément par coup (défaut 0)")
    ap.add_argument("--bots", default="", help="places jouées par des bots au départ, ex. BW,BB")
    ap.add_argument("--bot-type", choices=["random", "minimax"], default="random")
    args = ap.parse_args(argv)
    seats = frozenset(parse_seat(s) for s in args.bots.split(",") if s.strip())
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f"Impossible d'ouvrir une fenêtre : {exc}")
    # make = MinimaxPlayer if args.bot_type == "minimax" else RandomPlayer
    App(root, TimeControl(args.base, args.increment), bots=seats,
        bot_type="Minimax" if args.bot_type == "minimax" else "Aléatoire")
    root.mainloop()


if __name__ == "__main__":
    main()
