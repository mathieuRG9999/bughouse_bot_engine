"""Horloges de bughouse : 4 horloges indépendantes (2 planches x 2 couleurs).

Sur chaque planche, seule l'horloge du joueur au trait tourne ; les deux planches
avancent donc en parallèle. La source de temps est injectable (``ManualTime`` pour
les tests et les simulations, ``time.monotonic`` pour une vraie partie).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .seat import ALL_SEATS, Seat

TimeSource = Callable[[], float]
monotonic: TimeSource = time.monotonic


class ManualTime:
    """Horloge virtuelle : le temps n'avance que quand on le demande."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        if dt < 0:
            raise ValueError("le temps ne recule pas")
        self.t += dt


@dataclass(frozen=True)
class TimeControl:
    base: float = 180.0  # secondes par joueur (3 min)
    increment: float = 0.0  # secondes ajoutées après chaque coup


@dataclass(frozen=True)
class ClockSnapshot:
    remaining: dict[Seat, float]
    running: frozenset[Seat]


class ClockSet:
    def __init__(self, control: TimeControl) -> None:
        self.increment = control.increment
        self.remaining: dict[Seat, float] = {s: float(control.base) for s in ALL_SEATS}
        self.running: set[Seat] = set()
        self.paused = False
        self._last = 0.0

    # --- cycle de vie -------------------------------------------------
    def start(self, seats: Iterable[Seat], now: float) -> None:
        self.running = set(seats)
        self._last = now

    def sync(self, now: float) -> None:
        """Facture le temps écoulé depuis le dernier sync aux horloges qui tournent."""
        if not self.paused:
            dt = now - self._last
            for seat in self.running:
                self.remaining[seat] -= dt
        self._last = now

    def stop(self, now: float) -> None:
        self.sync(now)
        self.running.clear()

    def pause(self, now: float) -> None:
        self.sync(now)
        self.paused = True

    def resume(self, now: float) -> None:
        self._last = now
        self.paused = False

    # --- lecture -------------------------------------------------------
    def time_left(self, seat: Seat, now: float) -> float:
        ticking = seat in self.running and not self.paused
        return self.remaining[seat] - ((now - self._last) if ticking else 0.0)

    def flagged(self) -> Seat | None:
        """À appeler après ``sync`` : le joueur à qui il manque le plus de temps, s'il y en a un."""
        out = [s for s in self.running if self.remaining[s] <= 0]
        return min(out, key=lambda s: self.remaining[s]) if out else None

    # --- événements ----------------------------------------------------
    def press(self, seat: Seat, now: float) -> None:
        """``seat`` vient de jouer : on arrête son horloge, incrément, l'adversaire démarre."""
        self.sync(now)
        self.running.discard(seat)
        self.remaining[seat] += self.increment
        self.running.add(Seat(seat.board, not seat.color))

    # --- annulation ----------------------------------------------------
    def snapshot(self) -> ClockSnapshot:
        return ClockSnapshot(dict(self.remaining), frozenset(self.running))

    def restore(self, snap: ClockSnapshot, now: float) -> None:
        """Remet les temps dans l'état du snapshot ; le temps repart de ``now``."""
        self.remaining = dict(snap.remaining)
        self.running = set(snap.running)
        self._last = now
