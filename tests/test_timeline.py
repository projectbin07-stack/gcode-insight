"""Per-tool filament per layer, tool-change events and layer start/end times (0.4.0)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from gcode_insight import Analysis, ToolChange, analyze_file, analyze_lines

# With the default profile an extruding move at F600 (10 mm/s) accelerates at 3000 mm/s^2.
# A 10 mm move that starts and ends at rest cruises almost all the way:
# t = d / v + v / a = 1 + 10 / 3000 s. One that starts at rest and leaves at full speed (or
# arrives at full speed and stops) needs half the speed-change allowance: d / v + v / (2 a).
FIXTURES = Path(__file__).parent / "fixtures"
REST_TO_REST = 1.0 + 10.0 / 3000.0
REST_TO_SPEED = 1.0 + 10.0 / 6000.0

PROGRAM = """G90
M83
G92 Z0.2
G4 S1
;LAYER_CHANGE
G1 X10 E1 F600
G4 S2
T1
G1 X20 E2
;LAYER_CHANGE
G92 Z0.4
G1 X30 E3
T0
G1 X40 E4
"""


def run(text: str) -> Analysis:
    return analyze_lines(text.splitlines())


def test_filament_is_split_by_tool_within_each_layer() -> None:
    result = run(PROGRAM)
    assert result.layer_mode == "markers"
    first, second = result.layers
    assert first.filament_mm_by_tool == pytest.approx({0: 1.0, 1: 2.0})
    assert second.filament_mm_by_tool == pytest.approx({1: 3.0, 0: 4.0})
    assert result.startup.filament_mm_by_tool == {}
    for layer in result.layers:
        assert sum(layer.filament_mm_by_tool.values()) == pytest.approx(layer.filament_mm)


def test_layer_start_and_end_times_are_the_running_sum() -> None:
    result = run(PROGRAM)
    startup = result.startup
    first, second = result.layers
    assert (startup.start_s, startup.end_s) == pytest.approx((0.0, 1.0))
    # Layer 1: the 10 mm move at rest on both ends (the dwell stops it), the 2 s dwell, then
    # the move after the tool change, which flows into layer 2 at full speed.
    assert first.time_s == pytest.approx(REST_TO_REST + 2.0 + REST_TO_SPEED)
    assert (first.start_s, first.end_s) == pytest.approx((1.0, 1.0 + first.time_s))
    # Layer 2: the move from layer 1's speed down to rest at T0, then one at rest both ends.
    assert second.time_s == pytest.approx(REST_TO_SPEED + REST_TO_REST)
    assert second.start_s == pytest.approx(first.end_s)
    assert second.end_s == pytest.approx(result.estimated_time_s)
    expected_total = 1.0 + 2.0 + 2 * REST_TO_REST + 2 * REST_TO_SPEED
    assert result.estimated_time_s == pytest.approx(expected_total)


def test_tool_change_events_carry_layer_and_time() -> None:
    result = run(PROGRAM)
    assert result.tool_changes == 2
    first_change, second_change = result.tool_change_events
    assert first_change == ToolChange(
        from_tool=0, to_tool=1, layer=1, time_s=first_change.time_s, line=8
    )
    assert first_change.time_s == pytest.approx(1.0 + REST_TO_REST + 2.0)
    assert (second_change.from_tool, second_change.to_tool) == (1, 0)
    assert (second_change.layer, second_change.line) == (2, 13)
    assert second_change.time_s == pytest.approx(result.layers[1].start_s + REST_TO_SPEED)


def test_z_mode_gives_the_same_split_and_times() -> None:
    result = run(PROGRAM.replace(";LAYER_CHANGE\n", ""))
    assert result.layer_mode == "z"
    assert [layer.z for layer in result.layers] == [0.2, 0.4]
    assert [layer.filament_mm_by_tool for layer in result.layers] == [
        pytest.approx({0: 1.0, 1: 2.0}),
        pytest.approx({1: 3.0, 0: 4.0}),
    ]
    assert [(c.layer, c.line) for c in result.tool_change_events] == [(1, 7), (2, 11)]
    assert result.layers[-1].end_s == pytest.approx(result.estimated_time_s)


def test_change_before_the_first_move_of_a_z_layer_belongs_to_the_layer_still_open() -> None:
    # Without markers a layer opens at its first extruding move, so a tool change commanded
    # just before that move is reported in the previous layer.
    result = run("M83\nG1 Z0.2 F600\nG1 X10 E1\nG1 Z0.4\nT1\nG1 X20 E1\n")
    assert [c.layer for c in result.tool_change_events] == [1]
    assert result.layers[1].filament_mm_by_tool == pytest.approx({1: 1.0})


def test_firmware_selectors_and_repeats_are_not_events() -> None:
    result = run("M83\nT0\nG1 X10 E1 F600\nT1000\nT255\nT0\nG1 X20 E1\n")
    assert result.tool_changes == 0
    assert result.tool_change_events == []
    assert result.layers[0].filament_mm_by_tool == pytest.approx({0: 2.0})


def test_json_has_string_tool_keys_times_and_events() -> None:
    result = run(PROGRAM)
    data = json.loads(json.dumps(result.to_dict()))
    assert data["schema_version"] == 4
    layer = data["layers"][0]
    assert layer["filament_mm_by_tool"] == pytest.approx({"0": 1.0, "1": 2.0})
    assert layer["start_s"] == pytest.approx(1.0)
    assert layer["end_s"] == pytest.approx(result.layers[0].end_s)
    assert data["startup"]["filament_mm_by_tool"] == {}
    assert data["tool_change_events"][0] == {
        "from_tool": 0,
        "to_tool": 1,
        "layer": 1,
        "time_s": pytest.approx(1.0 + REST_TO_REST + 2.0),
        "line": 8,
    }
    assert len(data["tool_change_events"]) == data["tool_changes"] == 2


def test_synthetic_two_filament_fixture_timeline_is_consistent() -> None:
    result = analyze_file(FIXTURES / "bambu_cube.gcode")
    sections = [result.startup, *result.layers]
    for before, after in itertools.pairwise(sections):
        assert after.start_s == pytest.approx(before.end_s)
    assert sections[-1].end_s == pytest.approx(result.estimated_time_s)
    for tool in result.tools:
        per_layer = sum(s.filament_mm_by_tool.get(tool.tool, 0.0) for s in sections)
        assert per_layer == pytest.approx(tool.filament_mm)
    (change,) = result.tool_change_events
    assert (change.from_tool, change.to_tool, change.layer) == (0, 1, 3)
    third = result.layers[2]
    assert third.start_s < change.time_s < third.end_s
    assert set(third.filament_mm_by_tool) == {0, 1}
