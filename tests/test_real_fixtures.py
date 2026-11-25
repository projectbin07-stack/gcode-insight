"""The analyser on real OrcaSlicer output (tests/fixtures/real/, see its README)."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from gcode_insight import Analysis, analyze_file, load_registry
from gcode_insight.reader import list_plates

REAL = Path(__file__).parent / "fixtures" / "real"
PROVENANCE: dict[str, Any] = json.loads((REAL / "provenance.json").read_text(encoding="utf-8"))
FILES = {entry["file"]: entry for entry in PROVENANCE["fixtures"]}

#: fixture -> (registry key of the printer it was sliced for, filament colours)
EXPECTED = {
    "p1s-bead.gcode.3mf": ("p1s", ["#FFFFFF"]),
    "a1-bead.gcode.3mf": ("a1", ["#FFFFFF"]),
    "a1-mini-bead.gcode.3mf": ("a1-mini", ["#FFFFFF"]),
    "p1s-two-colour.gcode.3mf": ("p1s", ["#FFFFFF", "#161616"]),
}


def analyse(name: str) -> Analysis:
    return analyze_file(REAL / name)


def test_every_fixture_matches_its_recorded_checksum() -> None:
    assert sorted(FILES) == sorted(EXPECTED)
    for name, entry in FILES.items():
        assert hashlib.sha256((REAL / name).read_bytes()).hexdigest() == entry["sha256"], name
        assert entry["slicer"] == "OrcaSlicer"
        assert entry["slicer_version"] == "2.4.2"
    orca = PROVENANCE["orca_slicer"]
    assert orca["download"].startswith("https://github.com/SoftFever/OrcaSlicer/releases/")
    assert len(orca["sha256"]) == 64


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_real_file_metadata(name: str) -> None:
    key, colours = EXPECTED[name]
    assert list_plates(REAL / name) == [1]
    result = analyse(name)
    meta = result.metadata
    assert (meta.slicer, meta.slicer_version) == ("OrcaSlicer", "2.4.2")
    printer = load_registry().printer(meta.printer_model or "")
    assert printer is not None and printer.key == key
    assert meta.filament_colour == colours
    assert [tool.colour for tool in result.tools] == colours
    assert all(tool.material == "PLA" for tool in result.tools)
    # Layer markers from the slicer define the layers, and the count agrees with its header.
    assert result.layer_mode == "markers"
    assert result.layer_count == meta.total_layers == 59
    assert result.layers[0].z == pytest.approx(0.2)
    assert meta.layer_height == pytest.approx(0.2)
    assert meta.nozzle_diameter == pytest.approx(0.4)
    assert meta.estimated_time_s is not None and meta.model_time_s is not None
    assert result.time_comparison is not None
    assert result.time_comparison.basis == "model printing time"
    assert result.warnings == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_real_file_timeline_is_consistent(name: str) -> None:
    result = analyse(name)
    sections = [result.startup, *result.layers]
    assert result.startup.start_s == 0.0
    for before, after in itertools.pairwise(sections):
        assert after.start_s == pytest.approx(before.end_s)
        assert after.end_s >= after.start_s
    assert sections[-1].end_s == pytest.approx(result.estimated_time_s)
    for section in sections:
        assert sum(section.filament_mm_by_tool.values()) == pytest.approx(section.filament_mm)
    for tool in result.tools:
        total = sum(s.filament_mm_by_tool.get(tool.tool, 0.0) for s in sections)
        assert total == pytest.approx(tool.filament_mm)


def test_single_filament_files_have_no_tool_changes() -> None:
    for name, (_, colours) in EXPECTED.items():
        if len(colours) == 1:
            result = analyse(name)
            assert result.tool_changes == 0
            assert result.tool_change_events == []
            assert [t.tool for t in result.tools] == [0]


def test_two_colour_file_tool_changes() -> None:
    result = analyse("p1s-two-colour.gcode.3mf")
    events = result.tool_change_events
    assert len(events) == result.tool_changes == 20
    assert [t.tool for t in result.tools] == [0, 1]
    # The changes alternate between the two filaments and run forward in time and in layers.
    for before, after in itertools.pairwise(events):
        assert after.from_tool == before.to_tool
        assert after.time_s >= before.time_s
        assert after.layer >= before.layer
        assert after.line > before.line
    sections = [result.startup, *result.layers]
    for event in events:
        section = sections[event.layer]
        assert section.start_s <= event.time_s <= section.end_s
    # The start G-code loads the second filament (the tile, which starts layer 1), so the
    # first change is reported from the analyser's initial tool 0 during start-up.
    first = events[0]
    assert (first.from_tool, first.to_tool, first.layer) == (0, 1, 0)
    assert set(result.startup.filament_mm_by_tool) == {1}
    # Both objects print from the first layer, so layer 1 uses both filaments.
    assert set(result.layers[0].filament_mm_by_tool) == {0, 1}
