from __future__ import annotations

import math

import pytest

from gcode_insight.timing import Block, Planner, junction_speed, trapezoid_time

X = (1.0, 0.0, 0.0)
Y = (0.0, 1.0, 0.0)
NEG_X = (-1.0, 0.0, 0.0)


def test_trapezoid_rest_to_rest() -> None:
    # 0 -> 50 mm/s at 1000 mm/s^2 takes 0.05 s over 1.25 mm; same to brake;
    # the remaining 97.5 mm cruise at 50 mm/s takes 1.95 s.
    assert trapezoid_time(100.0, 50.0, 1000.0) == pytest.approx(2.05)


def test_triangle_when_too_short_to_reach_nominal() -> None:
    # 1 mm cannot reach 50 mm/s: peak = sqrt(a * d) = sqrt(1000), t = 2 * peak / a.
    assert trapezoid_time(1.0, 50.0, 1000.0) == pytest.approx(2.0 * math.sqrt(1000.0) / 1000.0)


def test_pure_cruise_when_entering_and_leaving_at_nominal() -> None:
    assert trapezoid_time(100.0, 50.0, 1000.0, entry=50.0, exit_speed=50.0) == pytest.approx(2.0)


def test_asymmetric_entry_and_exit() -> None:
    # entry 20: accel 0.03 s over 1.05 mm; exit 0: brake 0.05 s over 1.25 mm;
    # cruise (10 - 2.3) / 50 = 0.154 s.
    assert trapezoid_time(10.0, 50.0, 1000.0, entry=20.0) == pytest.approx(0.234)


def test_zero_distance_and_invalid_inputs() -> None:
    assert trapezoid_time(0.0, 50.0, 1000.0) == 0.0
    with pytest.raises(ValueError):
        trapezoid_time(1.0, 0.0, 1000.0)
    with pytest.raises(ValueError):
        trapezoid_time(1.0, 10.0, 0.0)


def test_junction_speed_rules() -> None:
    assert junction_speed(X, X, 60.0, 40.0, 8.0) == 40.0  # collinear: slower of the two
    assert junction_speed(X, Y, 60.0, 40.0, 8.0) == pytest.approx(8.0 / math.sqrt(2.0))
    assert junction_speed(X, NEG_X, 60.0, 40.0, 8.0) == pytest.approx(4.0)
    assert junction_speed(X, Y, 3.0, 3.0, 8.0) == 3.0  # slow enough to corner freely
    assert junction_speed(None, X, 60.0, 40.0, 8.0) == 0.0
    assert junction_speed(X, None, 60.0, 40.0, 8.0) == 0.0


def _run(blocks: list[Block], jerk: float = 10.0, window: int = 64) -> list[float]:
    times: list[float] = []
    planner = Planner(jerk, lambda _block, seconds: times.append(seconds), window=window)
    for block in blocks:
        planner.add(block)
    planner.flush()
    return times


def test_collinear_blocks_behave_like_one_long_move() -> None:
    times = _run([Block(50.0, 50.0, 1000.0, X, X), Block(50.0, 50.0, 1000.0, X, X)])
    assert len(times) == 2
    assert sum(times) == pytest.approx(2.05)


def test_right_angle_corner_slows_to_junction_speed() -> None:
    # Junction speed = 10 / sqrt(2) = 7.0711 mm/s. Per block: 0.05 s to reach
    # 50 mm/s (1.25 mm), (50 - 7.0711) / 1000 = 0.0429289 s to brake over
    # (2500 - 50) / 2000 = 1.225 mm, cruise 97.525 / 50 = 1.9505 s.
    per_block = 0.05 + 0.0429289 + 1.9505
    times = _run([Block(100.0, 50.0, 1000.0, X, X), Block(100.0, 50.0, 1000.0, Y, Y)])
    assert times[0] == pytest.approx(per_block, abs=1e-6)
    assert times[1] == pytest.approx(per_block, abs=1e-6)


def test_lookahead_brakes_before_a_short_final_block() -> None:
    # The last 0.1 mm block must end at rest, so it can be entered at no more
    # than sqrt(2 * 1000 * 0.1) = 14.142 mm/s; the long block has to brake to that.
    times = _run([Block(100.0, 50.0, 1000.0, X, X), Block(0.1, 50.0, 1000.0, X, X)])
    entry = math.sqrt(200.0)
    assert times[0] == pytest.approx(trapezoid_time(100.0, 50.0, 1000.0, 0.0, entry))
    assert times[1] == pytest.approx(entry / 1000.0)
    # Same total as one 100.1 mm move, since the pair is collinear.
    assert sum(times) == pytest.approx(trapezoid_time(100.1, 50.0, 1000.0))


def test_extruder_only_block_forces_a_stop() -> None:
    times = _run(
        [
            Block(100.0, 50.0, 1000.0, X, X),
            Block(0.8, 30.0, 5000.0, None, None),
            Block(100.0, 50.0, 1000.0, X, X),
        ]
    )
    assert times[0] == pytest.approx(2.05)
    assert times[1] == pytest.approx(trapezoid_time(0.8, 30.0, 5000.0))
    assert times[2] == pytest.approx(2.05)


def test_sliding_window_matches_single_move() -> None:
    blocks = [Block(1.0, 50.0, 1000.0, X, X) for _ in range(300)]
    times = _run(blocks, window=8)
    assert len(times) == 300
    assert sum(times) == pytest.approx(trapezoid_time(300.0, 50.0, 1000.0))


def test_flush_resets_to_rest_and_ignores_empty_blocks() -> None:
    times: list[float] = []
    planner = Planner(10.0, lambda _block, seconds: times.append(seconds))
    planner.flush()
    planner.add(Block(0.0, 50.0, 1000.0, X, X))
    planner.add(Block(100.0, 50.0, 1000.0, X, X))
    planner.flush()
    planner.add(Block(100.0, 50.0, 1000.0, X, X))
    planner.flush()
    assert times == [pytest.approx(2.05), pytest.approx(2.05)]
    with pytest.raises(ValueError):
        Planner(10.0, lambda _block, _seconds: None, window=0)
