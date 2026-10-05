"""Simulateur événementiel en temps virtuel : 4 bots, les deux planches avancent en parallèle.

    python -m bughouse2v2.sim --seed 1 --base 180 --log
"""
from __future__ import annotations

if __package__ in (None, ""):  # lancé comme un simple script (python sim.py, bouton « Run » d'un IDE)
    import os
    import runpy
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        runpy.run_module("bughouse2v2.sim", run_name="__main__")
    except ImportError as exc:
        if getattr(exc, "name", None) == "chess":
            raise SystemExit("Il manque la bibliothèque chess : pip install -r requirements.txt")
        if "bughouse2v2" in str(exc):
            raise SystemExit("Les fichiers doivent rester dans un dossier nommé bughouse2v2/ (avec __init__.py).")
        raise
    raise SystemExit

import argparse
import random

from .clock import ALL_SEATS, ManualTime, TimeControl
from .game import Game
from .players import Player, RandomPlayer
from .seat import Seat


def simulate(
    players: dict[Seat, Player] | None = None,
    *,
    control: TimeControl = TimeControl(180.0, 0.0),
    think_range: tuple[float, float] = (0.3, 3.0),
    seed: int = 0,
    max_events: int = 100_000,
) -> Game:
    """Joue une partie complète en temps virtuel et renvoie le ``Game`` terminé.

    ``think_range`` : temps de réflexion simulé (uniforme) par coup, en secondes.
    """
    rng = random.Random(seed)
    clock = ManualTime()
    game = Game(control, now=clock)
    if players is None:
        players = {s: RandomPlayer(f"rnd-{s}", seed=rng.randrange(2**32)) for s in ALL_SEATS}

    game.start()
    ready: dict[int, float | None] = {0: None, 1: None}  # heure à laquelle le joueur au trait jouera

    for _ in range(max_events):
        if game.is_over:
            break
        for b in (0, 1):
            if ready[b] is None and not game.is_blocked(b):
                ready[b] = clock() + rng.uniform(*think_range)

        pending = {b: t for b, t in ready.items() if t is not None}
        if pending:
            board = min(pending, key=pending.__getitem__)
            target = pending[board]
        else:  # les deux joueurs au trait sont bloqués : on attend qu'un drapeau tombe
            board = None
            target = clock() + min(game.time_left(s) for s in game.active_seats) + 1e-6

        clock.advance(max(0.0, target - clock()))
        if game.check_time() is not None or board is None:
            continue

        seat = Seat(board, game.turn(board))
        game.push(board, players[seat].choose_move(game, board))
        ready[board] = None
    return game


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--base", type=float, default=180.0, help="secondes par joueur")
    ap.add_argument("--increment", type=float, default=0.0)
    ap.add_argument("--log", action="store_true", help="affiche tous les coups")
    args = ap.parse_args()

    game = simulate(control=TimeControl(args.base, args.increment), seed=args.seed)
    if args.log:
        for e in game.history:
            cap = f" (+{e.captured} au partenaire)" if e.captured else ""
            print(f"{e.ply:4d}  t={e.elapsed:6.1f}s  {e.seat}  {e.san}{cap}")
    print(game.render())
    print(f"{len(game.history)} coups joués")


if __name__ == "__main__":
    main()
