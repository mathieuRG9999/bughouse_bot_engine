"""Interface graphique tkinter : les deux planches, les poches, les 4 horloges, undo, bots.

    python play_gui.py
    python play_gui.py --bots BW,BB --base 120 --increment 1

Jouer : clic sur une de tes pièces puis sur la case d'arrivée (les coups possibles sont
marqués). Pour poser une pièce de ta poche : clic sur la pièce dans la poche, puis sur une
case libre. Ctrl+Z annule le dernier coup. Cocher « Bot » à côté d'une place la fait jouer
par ``RandomPlayer`` (ou par le joueur que tu passes à ``App(players=...)``).

Pièces optionnelles : dépose des PNG (wK.png, wQ.png, wR.png, wB.png, wN.png, wP.png,
bK.png, ... à la taille SQUARE) dans bughouse2v2/pieces/ ; sinon les glyphes Unicode sont utilisés.
"""
from __future__ import annotations

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
import os
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


from .async_bots import AsyncBots
from .clock import TimeControl, monotonic
from .game import BughouseError, Game, HistoryEntry
from .interaction import Interaction
from .players import Player, RandomPlayer
from .minimax import MinimaxPlayer
from .seat import ALL_SEATS, Seat

SQUARE = 56  # taille d'une case en pixels

# --- thème ---
BG, PANEL, PANEL_2, HOVER = "#1e1f22", "#2b2d31", "#3a3d44", "#4a4d55"
FG, MUTED = "#e6e6e6", "#9aa0a6"
TEAM_COLORS = ("#7fb8ff", "#ffb36b")  # AW+BB / AB+BW

LIGHT, DARK = "#eeeed2", "#769656"  # plateau « vert »
LAST_LIGHT, LAST_DARK = "#f5f682", "#b9ca43"
SELECT_COLOR, CHECK_COLOR = "#ffd24d", "#e8575a"
# (fond, texte)
CLOCK_ON, CLOCK_OFF, CLOCK_LOW = ("#f2f2f2", "#111111"), (PANEL_2, MUTED), ("#d64545", "#ffffff")

MONO = {"Windows": "Consolas", "Darwin": "Menlo"}.get(platform.system(), "DejaVu Sans Mono")
PIECE_FONT = {"Windows": "Segoe UI Symbol", "Darwin": "Apple Symbols"}.get(platform.system(), "DejaVu Sans")
GLYPH_FILLED = {chess.PAWN: "♟", chess.KNIGHT: "♞", chess.BISHOP: "♝", chess.ROOK: "♜", chess.QUEEN: "♛", chess.KING: "♚"}
GLYPH_HOLLOW = {chess.PAWN: "♙", chess.KNIGHT: "♘", chess.BISHOP: "♗", chess.ROOK: "♖", chess.QUEEN: "♕", chess.KING: "♔"}
POCKET_ORDER = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN)
BOT_TYPES = {"Aléatoire": RandomPlayer, "Minimax": MinimaxPlayer}


def blend(c1: str, c2: str, t: float) -> str:
    """Mélange deux couleurs #rrggbb (simule une transparence)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def team_of(seat: Seat) -> int:
    return 0 if (seat.board == 0) == (seat.color == chess.WHITE) else 1


def apply_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)
    o = root.option_add
    o("*Background", BG); o("*Foreground", FG)
    o("*Font", "TkDefaultFont")
    o("*Button.Background", PANEL_2); o("*Button.Foreground", FG)
    o("*Button.activeBackground", HOVER); o("*Button.activeForeground", FG)
    o("*Button.relief", "flat"); o("*Button.borderWidth", 0)
    o("*Button.highlightThickness", 0); o("*Button.cursor", "hand2")
    o("*Button.padX", 10); o("*Button.padY", 4)
    o("*Menubutton.Background", PANEL_2); o("*Menubutton.activeBackground", HOVER)
    o("*Menubutton.relief", "flat"); o("*Menubutton.borderWidth", 0)
    o("*Menubutton.highlightThickness", 0); o("*Menubutton.padX", 8)
    o("*Menu.Background", PANEL_2); o("*Menu.Foreground", FG)
    o("*Menu.activeBackground", HOVER); o("*Menu.borderWidth", 0)
    o("*Checkbutton.selectColor", PANEL_2); o("*Checkbutton.activeBackground", BG)
    o("*Checkbutton.activeForeground", FG); o("*Checkbutton.highlightThickness", 0)
    o("*Entry.Background", PANEL_2); o("*Entry.Foreground", FG)
    o("*Entry.insertBackground", FG); o("*Entry.relief", "flat")
    o("*Entry.highlightThickness", 1); o("*Entry.highlightBackground", PANEL_2)
    o("*Entry.highlightColor", "#5b9bd5")
    o("*Scale.troughColor", PANEL_2); o("*Scale.highlightThickness", 0)
    o("*Scale.borderWidth", 0); o("*Scale.activeBackground", HOVER)
    o("*Text.Background", PANEL); o("*Text.Foreground", FG)
    o("*Text.relief", "flat"); o("*Text.highlightThickness", 0)
    o("*Scrollbar.Background", PANEL_2); o("*Scrollbar.troughColor", PANEL)
    o("*Scrollbar.borderWidth", 0); o("*Scrollbar.relief", "flat")


_IMG: dict[str, tk.PhotoImage | None] = {}


def piece_image(piece: chess.Piece) -> tk.PhotoImage | None:
    """Image PNG de la pièce si le dossier pieces/ existe, sinon None (repli sur les glyphes)."""
    key = ("w" if piece.color == chess.WHITE else "b") + piece.symbol().upper()
    if key not in _IMG:
        try:
            _IMG[key] = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), "pieces", key + ".png"))
        except tk.TclError:
            _IMG[key] = None
    return _IMG[key]


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
        self.frame = tk.Frame(parent, bg=PANEL, padx=10, pady=6)
        self.title = tk.Label(self.frame, anchor="w", bg=PANEL, fg=FG, font=("TkDefaultFont", 10, "bold"))
        self.clock = tk.Label(self.frame, width=7, font=(MONO, 17, "bold"), padx=6, pady=1)
        self.pocket = tk.Frame(self.frame, bg=PANEL)
        self.title.pack(side=tk.LEFT)
        self.clock.pack(side=tk.LEFT, padx=8)
        self.pocket.pack(side=tk.LEFT)
        self._sig: object = None

    def update(self) -> None:
        app, g, seat = self.app, self.app.game, self.seat
        t = g.time_left(seat)
        running = seat in g.active_seats and not g.clocks.paused
        bg, fg = CLOCK_LOW if (t < 10 and running) else CLOCK_ON if running else CLOCK_OFF
        self.clock.config(text=format_time(t), bg=bg, fg=fg)
        name = "Blancs" if seat.color == chess.WHITE else "Noirs"
        bot = ""
        if app.bot_vars[seat].get():
            bot = "  🤖 réfléchit…" if app.async_bots.is_thinking(seat) else "  🤖"
        blocked = "  — bloqué, attend une pièce" if running and g.is_blocked(seat.board) else ""
        dot = "● " if running else "   "
        self.title.config(
            text=f"{dot}{seat} {name}{bot}{blocked}",
            fg=TEAM_COLORS[team_of(seat)] if running else MUTED,
        )

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
                padx=5,
                pady=0,
                state=tk.NORMAL if can_drop else tk.DISABLED,
                disabledforeground=MUTED,
                bg=SELECT_COLOR if pt == picked else PANEL_2,
                fg="#111111" if pt == picked else FG,
                activebackground=HOVER,
                command=lambda pt=pt: app.on_pocket(seat.board, seat.color, pt),
            ).pack(side=tk.LEFT, padx=2)


class BoardView:
    def __init__(self, app: "App", parent: tk.Widget, idx: int, flipped: bool) -> None:
        self.app, self.idx, self.flipped = app, idx, flipped
        self.frame = tk.Frame(parent, padx=6, pady=4)
        head = tk.Frame(self.frame)
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text=f"Planche {'AB'[idx]}", font=("TkDefaultFont", 11, "bold"), fg=FG).pack(side=tk.LEFT)
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
                m, r = SQUARE // 2, SQUARE // 6
                dot = blend(color, "#000000", 0.22)  # marqueur « translucide » adapté à la case
                if piece:  # capture : anneau
                    c.create_oval(x + 3, y + 3, x + SQUARE - 3, y + SQUARE - 3, outline=dot, width=5)
                else:
                    c.create_oval(x + m - r, y + m - r, x + m + r, y + m + r, fill=dot, outline="")
            tint = DARK if light else LIGHT
            if (self.flipped and chess.square_rank(sq) == 7) or (not self.flipped and chess.square_rank(sq) == 0):
                c.create_text(x + SQUARE - 7, y + SQUARE - 8, text="abcdefgh"[chess.square_file(sq)], fill=tint, font=("TkDefaultFont", 9, "bold"))
            if (self.flipped and chess.square_file(sq) == 7) or (not self.flipped and chess.square_file(sq) == 0):
                c.create_text(x + 7, y + 8, text=str(chess.square_rank(sq) + 1), fill=tint, font=("TkDefaultFont", 9, "bold"))

    def _piece(self, x: int, y: int, piece: chess.Piece) -> None:
        cx, cy = x + SQUARE // 2, y + SQUARE // 2 + 1
        img = piece_image(piece)
        if img:
            self.canvas.create_image(cx, y + SQUARE // 2, image=img)
            return
        font = (PIECE_FONT, -int(SQUARE * 0.78))
        glyph = GLYPH_FILLED[piece.piece_type]
        fill, edge = ("#ffffff", "#1a1a1a") if piece.color == chess.WHITE else ("#161616", "#e8e8e8")
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):  # 4 contours : plus léger
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
        parallel: bool = True,
    ) -> None:
        self.root = root
        apply_theme(root)  # avant la création des widgets
        self.bot_type = {s: tk.StringVar(value=bot_type) for s in ALL_SEATS}
        self.players: dict[Seat, Player] = {s: BOT_TYPES[bot_type](f"bot-{s}") for s in ALL_SEATS}
        self.bot_vars = {s: tk.BooleanVar(value=s in bots) for s in ALL_SEATS}
        self.base_var = tk.StringVar(value=f"{control.base:g}")
        self.inc_var = tk.StringVar(value=f"{control.increment:g}")
        self.delay_var = tk.DoubleVar(value=0.8)
        self.msg_var = tk.StringVar(value="")
        self.state_var = tk.StringVar(value="")
        self.async_bots = AsyncBots(workers=2 if parallel else 0)
        self._closed = False
        self._after_id = None
        self._log_sig: object = None
        self.game = Game(control, now=monotonic)
        self.inter = Interaction(self.game)

        root.title("Bughouse 2v2")
        self._build()
        self.new_game()
        root.bind("<Control-z>", lambda _e: self.undo())
        root.protocol("WM_DELETE_WINDOW", self.close)
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
        mb = tk.Menubutton(bar, text="Abandon ▾")
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
        tk.Label(bots, text="   Équipes : AW+BB  contre  AB+BW", fg=MUTED).pack(side=tk.LEFT)

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
        self.log = tk.Text(box, width=30, height=24, state=tk.DISABLED, font=(MONO, 10), wrap="none",
                           padx=8, pady=6, spacing1=2)
        self.log.tag_configure("t0", foreground=TEAM_COLORS[0])
        self.log.tag_configure("t1", foreground=TEAM_COLORS[1])
        self.log.tag_configure("cap", foreground=MUTED)
        scroll = tk.Scrollbar(box, command=self.log.yview)
        self.log.config(yscrollcommand=scroll.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.LEFT, fill=tk.Y)

        status = tk.Frame(root, bg=PANEL)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.state_lbl = tk.Label(status, textvariable=self.state_var, anchor="w", bg=PANEL, font=("TkDefaultFont", 10, "bold"))
        self.state_lbl.pack(side=tk.LEFT, padx=6, pady=3)
        tk.Label(status, textvariable=self.msg_var, anchor="w", bg=PANEL, fg=MUTED).pack(side=tk.LEFT, padx=6)

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
        self.async_bots.reset()
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
        self.async_bots.reset()
        self.say(f"annulé : {entry.seat} {entry.san}" if entry else "rien à annuler")
        self.refresh()

    def _bot_type_changed(self, seat: Seat) -> None:
        self.players[seat] = BOT_TYPES[self.bot_type[seat].get()](f"bot-{seat}")
        self.async_bots.reset()

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
        self.async_bots.reset()
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
        for entry in self.async_bots.poll(
            self.game,
            self.players,
            enabled=lambda seat: self.bot_vars[seat].get(),
            delay=lambda: self.delay_var.get() * random.uniform(0.5, 1.5),
            on_error=self.say,
        ):
            self.say("[bot] " + describe(entry))

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self.game.check_time()
            self.run_bots()
            self.refresh()
        finally:
            if not self._closed:
                self._after_id = self.root.after(self.TICK_MS, self._tick)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.async_bots.shutdown()
        self.root.destroy()

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
            self.state_lbl.config(fg="#ff7b7b")
        else:
            self.state_var.set("PAUSE" if g.clocks.paused else "En cours")
            self.state_lbl.config(fg="#ffb347" if g.clocks.paused else "#7bd88f")

    def _update_log(self) -> None:
        hist = self.game.history
        sig = (len(hist), id(hist[-1]) if hist else None)
        if sig == self._log_sig:
            return
        self._log_sig = sig
        self.log.config(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        for e in hist:
            self.log.insert(tk.END, f"{e.ply:3d}. {e.seat}  {e.san}", f"t{team_of(e.seat)}")
            if e.captured:
                self.log.insert(tk.END, f"  +{GLYPH_HOLLOW[e.captured]}→{e.seat.partner}", "cap")
            self.log.insert(tk.END, "\n")
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
    app = App(root, TimeControl(args.base, args.increment), bots=seats,
              bot_type="Minimax" if args.bot_type == "minimax" else "Aléatoire")
    if app.async_bots.fallback_reason:
        app.say(app.async_bots.fallback_reason)
    root.mainloop()


if __name__ == "__main__":
    main()