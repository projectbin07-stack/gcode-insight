"""Trapezoidal motion-time model.

The model
---------
Every move is a *block* with a path length ``d`` (mm), a nominal speed ``v``
(mm/s, the commanded feedrate after per-axis limits) and an acceleration ``a``
(mm/s^2). Speed along a block follows a trapezoid: accelerate at ``a`` from the
entry speed, cruise at ``v``, decelerate at ``a`` to the exit speed. When the
block is too short to reach ``v`` the profile becomes a triangle.

Junctions (kept deliberately simple)
------------------------------------
The speed carried from one block into the next is limited by a single
"junction speed step" ``jerk`` (mm/s), in the spirit of classic Marlin jerk:

* direction unit vectors ``u1`` (leaving) and ``u2`` (entering) are compared;
* the candidate speed is ``min(v1, v2)``;
* if the instantaneous velocity change ``candidate * |u2 - u1|`` exceeds
  ``jerk``, the junction speed is reduced to ``jerk / |u2 - u1|``.

So collinear moves pass through at full speed, a 90 degree corner is taken at
``jerk / sqrt(2)`` and a reversal at ``jerk / 2``. Extruder-only moves
(retractions) always start and end at rest.

Look-ahead
----------
A backward pass makes sure each block can still brake to its exit speed, and a
forward pass makes sure each block can actually reach its entry speed. Blocks
are planned in a sliding window (:data:`DEFAULT_WINDOW` blocks of look-ahead),
which bounds memory for streaming and is far deeper than a real firmware queue.

What is *not* modelled: jerk-limited (S-curve) profiles, input shaping, pressure
/ linear advance, junction-deviation or square-corner-velocity planners, and
firmware-specific quirks. See the README for what that means for accuracy.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["DEFAULT_WINDOW", "Block", "Planner", "Vector", "junction_speed", "trapezoid_time"]

Vector = tuple[float, float, float]

DEFAULT_WINDOW = 64


def trapezoid_time(
    distance: float,
    nominal: float,
    accel: float,
    entry: float = 0.0,
    exit_speed: float = 0.0,
) -> float:
    """Time in seconds to cover ``distance`` with a trapezoidal speed profile.

    ``entry`` and ``exit_speed`` must be reachable (``|exit^2 - entry^2| <=
    2 * accel * distance``); the planner guarantees that. Example: 100 mm at a
    nominal 50 mm/s with 1000 mm/s^2 from rest to rest takes 0.05 s to
    accelerate over 1.25 mm, the same to brake, and 97.5 mm / 50 mm/s = 1.95 s
    of cruise: 2.05 s in total.
    """
    if distance <= 0.0:
        return 0.0
    if nominal <= 0.0 or accel <= 0.0:
        raise ValueError("nominal speed and acceleration must be positive")
    entry = min(entry, nominal)
    exit_speed = min(exit_speed, nominal)
    accel_dist = (nominal * nominal - entry * entry) / (2.0 * accel)
    decel_dist = (nominal * nominal - exit_speed * exit_speed) / (2.0 * accel)
    cruise_dist = distance - accel_dist - decel_dist
    if cruise_dist >= 0.0:
        return (nominal - entry) / accel + (nominal - exit_speed) / accel + cruise_dist / nominal
    # Triangle: peak speed is where the acceleration and braking ramps meet.
    peak_sq = (2.0 * accel * distance + entry * entry + exit_speed * exit_speed) / 2.0
    peak = math.sqrt(max(peak_sq, entry * entry, exit_speed * exit_speed))
    return (peak - entry) / accel + (peak - exit_speed) / accel


def junction_speed(
    leaving: Vector | None,
    entering: Vector | None,
    speed_before: float,
    speed_after: float,
    jerk: float,
) -> float:
    """Maximum speed carried across the junction between two blocks.

    ``leaving`` / ``entering`` are unit direction vectors; ``None`` marks a block
    with no XYZ motion (extruder only), which forces a full stop.
    """
    if leaving is None or entering is None:
        return 0.0
    candidate = min(speed_before, speed_after)
    change = math.dist(leaving, entering)
    if change * candidate > jerk:
        return jerk / change
    return candidate


@dataclass(slots=True)
class Block:
    """One move as seen by the planner."""

    distance: float
    nominal: float
    accel: float
    #: Unit direction at the start / end of the move (they differ for arcs).
    #: ``None`` for extruder-only moves.
    direction_in: Vector | None
    direction_out: Vector | None
    #: Opaque value handed back to the sink (the analyser stores layer indices).
    tag: tuple[int, int] = (0, 0)


class Planner:
    """Look-ahead planner that reports the duration of each block.

    ``sink(block, seconds)`` is called once per block, in order, as soon as the
    block's timing is final. Call :meth:`flush` wherever the machine comes to a
    stop (dwell, homing, tool change) and at the end of the file.
    """

    def __init__(
        self,
        jerk: float,
        sink: Callable[[Block, float], None],
        window: int = DEFAULT_WINDOW,
    ) -> None:
        if window < 1:
            raise ValueError("window must be at least 1")
        self._jerk = jerk
        self._sink = sink
        self._window = window
        self._blocks: list[Block] = []
        self._junctions: list[float] = []  # junction speed limit entering block i
        self._entry_speed = 0.0

    def add(self, block: Block) -> None:
        if block.distance <= 0.0:
            return
        if self._blocks:
            previous = self._blocks[-1]
            limit = junction_speed(
                previous.direction_out,
                block.direction_in,
                previous.nominal,
                block.nominal,
                self._jerk,
            )
        else:
            limit = self._entry_speed
        self._blocks.append(block)
        self._junctions.append(limit)
        if len(self._blocks) >= 2 * self._window:
            self._plan(emit=self._window)

    def flush(self) -> None:
        """Plan and emit everything queued; the machine is at rest afterwards."""
        if self._blocks:
            self._plan(emit=len(self._blocks))
        self._entry_speed = 0.0

    def _plan(self, emit: int) -> None:
        blocks = self._blocks
        count = len(blocks)
        # Backward pass: highest entry speed from which each block can still
        # brake to the entry speed of the block after it (0 after the last).
        entry_max = [0.0] * (count + 1)
        for i in range(count - 1, -1, -1):
            block = blocks[i]
            brake_limit = math.sqrt(entry_max[i + 1] ** 2 + 2.0 * block.accel * block.distance)
            entry_max[i] = min(self._junctions[i], brake_limit, block.nominal)
        # Forward pass: speeds actually reachable when accelerating from the start.
        entry = min(self._entry_speed, entry_max[0])
        for i in range(emit):
            block = blocks[i]
            reach_limit = math.sqrt(entry * entry + 2.0 * block.accel * block.distance)
            exit_speed = min(entry_max[i + 1], reach_limit)
            self._sink(
                block,
                trapezoid_time(block.distance, block.nominal, block.accel, entry, exit_speed),
            )
            entry = exit_speed
        del blocks[:emit]
        del self._junctions[:emit]
        if blocks:
            self._junctions[0] = entry
        self._entry_speed = entry
