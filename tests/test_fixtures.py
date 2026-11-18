"""End-to-end checks on the slicer-style fixtures.

Ground truth comes from ``fixtures/expected.json``, which the fixture generator
writes from its own bookkeeping (see ``fixtures/generate_fixtures.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fixtures.generate_fixtures import build
from gcode_insight import Analysis, analyze_file

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["bambu_cube.gcode", "orca_cube.gcode", "prusa_cube.gcode", "marlin_generic.gcode"]
EXPECTED: dict[str, dict[str, Any]] = json.loads(
    (FIXTURES / "expected.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module", params=NAMES)
def case(request: pytest.FixtureRequest) -> tuple[Analysis, dict[str, Any]]:
    name: str = request.param
    return analyze_file(FIXTURES / name), EXPECTED[name]


def test_committed_fixtures_match_the_generator() -> None:
    for name, content in build().items():
        on_disk = (FIXTURES / name).read_text(encoding="utf-8")
        assert on_disk == content, f"{name} is stale; re-run generate_fixtures.py"


def test_filament_totals(case: tuple[Analysis, dict[str, Any]]) -> None:
    analysis, expected = case
    assert analysis.filament_mm == pytest.approx(expected["filament_mm"], abs=1e-4)
    by_tool = {str(tool.tool): tool.filament_mm for tool in analysis.tools}
    assert by_tool == pytest.approx(expected["filament_by_tool"], abs=1e-4)


def test_layers(case: tuple[Analysis, dict[str, Any]]) -> None:
    analysis, expected = case
    assert analysis.layer_count == expected["layers"]
    assert [layer.filament_mm for layer in analysis.layers] == pytest.approx(
        expected["layer_filament"], abs=1e-4
    )
    heights = [layer.z for layer in analysis.layers if layer.z is not None]
    assert len(heights) == analysis.layer_count
    assert heights == sorted(heights)
    assert all(layer.time_s > 0 for layer in analysis.layers)


def test_paths_retractions_and_extent(case: tuple[Analysis, dict[str, Any]]) -> None:
    analysis, expected = case
    assert analysis.extrude_path_mm == pytest.approx(expected["extrude_path_mm"], abs=1e-3)
    assert analysis.retractions == expected["retractions"]
    box = analysis.bounding_box
    assert box is not None
    actual = [box.min_x, box.max_x, box.min_y, box.max_y, box.min_z, box.max_z]
    assert actual == pytest.approx(expected["bbox"], abs=1e-6)


def test_time_is_split_across_layers(case: tuple[Analysis, dict[str, Any]]) -> None:
    analysis, _ = case
    parts = analysis.startup.time_s + sum(layer.time_s for layer in analysis.layers)
    assert parts == pytest.approx(analysis.estimated_time_s)
    assert analysis.estimated_time_s > 0


def test_slicer_filament_figure_agrees(case: tuple[Analysis, dict[str, Any]]) -> None:
    analysis, _ = case
    reported = analysis.metadata.filament_used_mm
    if reported:  # the plain Marlin fixture has no slicer comments
        assert sum(reported) == pytest.approx(analysis.filament_mm, abs=0.011)
        assert sum(analysis.metadata.filament_used_g) == pytest.approx(analysis.mass_g, abs=0.011)


def test_bambu_fixture_details() -> None:
    analysis = analyze_file(FIXTURES / "bambu_cube.gcode")
    meta = analysis.metadata
    assert (meta.slicer, meta.slicer_version) == ("BambuStudio", "01.10.01.50")
    assert analysis.layer_mode == "markers"
    assert meta.total_layers == analysis.layer_count == 5
    assert meta.layer_height == 0.2
    assert meta.nozzle_diameter == 0.4
    assert meta.filament_type == ["PLA", "PETG"]
    assert [(t.tool, t.material, t.density) for t in analysis.tools] == [
        (0, "PLA", 1.24),
        (1, "PETG", 1.27),
    ]
    assert analysis.tool_changes == 1
    assert analysis.startup.filament_mm > 0  # nozzle load line stays out of layer 1
    assert analysis.nozzle_temp_max == 245.0
    assert analysis.bed_temp_max == 55.0
    assert analysis.fan_max_percent == {1: pytest.approx(100.0), 2: pytest.approx(178 / 2.55)}
    assert analysis.time_comparison is not None
    assert analysis.time_comparison.basis == "model printing time"
    assert analysis.time_comparison.slicer_time_s == 27.0
    assert meta.estimated_time_s == 393.0
    assert analysis.warnings == []


def test_orca_fixture_details() -> None:
    analysis = analyze_file(FIXTURES / "orca_cube.gcode")
    meta = analysis.metadata
    assert (meta.slicer, meta.slicer_version) == ("OrcaSlicer", "2.1.1")
    assert analysis.layer_mode == "markers"
    assert meta.total_layers == 5
    assert meta.filament_type == ["ABS"]
    assert analysis.tools[0].density == 1.04
    assert meta.estimated_time_s == 35.0
    assert analysis.time_comparison is not None
    assert analysis.time_comparison.basis == "total estimated time"
    assert analysis.bed_temp_max == 100.0


def test_prusa_fixture_details() -> None:
    analysis = analyze_file(FIXTURES / "prusa_cube.gcode")
    meta = analysis.metadata
    assert (meta.slicer, meta.slicer_version) == ("PrusaSlicer", "2.7.4+win64")
    assert analysis.layer_mode == "markers"
    assert analysis.layer_count == 6
    assert meta.filament_type == ["PETG"]
    assert meta.filament_density == [1.27]
    assert meta.first_layer_height == 0.2
    assert meta.estimated_time_s == 64.0
    assert analysis.fan_max_percent == {0: pytest.approx(30.0)}


def test_marlin_fixture_details() -> None:
    analysis = analyze_file(FIXTURES / "marlin_generic.gcode")
    assert analysis.metadata.is_empty
    assert analysis.layer_mode == "z"
    assert [layer.z for layer in analysis.layers] == [0.25, 0.5, 0.75, 1.0]
    assert analysis.dwell_time_s == pytest.approx(1.5)
    assert analysis.time_comparison is None
    assert any("PLA density" in warning for warning in analysis.warnings)
