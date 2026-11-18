"""Analyser tests on small inline programs with hand-computed expectations."""

from __future__ import annotations

import json
import math

import pytest

from gcode_insight import Analysis, AnalysisOptions, MachineProfile, analyze_lines

FILAMENT_AREA = math.pi * 0.875**2  # mm^2 for 1.75 mm filament


def run(text: str, options: AnalysisOptions | None = None) -> Analysis:
    return analyze_lines(text.splitlines(), options)


# ---------------------------------------------------------------- extrusion


def test_straight_20mm_extrusion() -> None:
    result = run("G90\nM83\nG1 X0 Y0 Z0.2 F6000\nG1 X20 E0.665 F1200\n")
    assert result.filament_mm == pytest.approx(0.665)
    assert result.extrude_path_mm == pytest.approx(20.0)
    # 0.665 mm of 1.75 mm filament = 1.5995 mm^3 = 0.0015995 cm^3 -> 0.0019834 g of PLA.
    assert result.volume_cm3 == pytest.approx(0.665 * FILAMENT_AREA / 1000.0)
    assert result.volume_cm3 == pytest.approx(0.0015995, abs=1e-7)
    assert result.mass_g == pytest.approx(0.0019834, abs=1e-7)
    box = result.bounding_box
    assert box is not None
    assert (box.min_x, box.max_x, box.min_y, box.max_y) == (0.0, 20.0, 0.0, 0.0)
    assert (box.min_z, box.max_z) == (0.2, 0.2)
    assert box.size == (20.0, 0.0, 0.0)
    assert result.layer_count == 1
    assert result.layers[0].z == 0.2
    assert result.retractions == 0


def test_absolute_extrusion_with_g92_reset() -> None:
    result = run("G90\nM82\nG1 X10 E1 F1200\nG1 X20 E2\nG92 E0\nG1 X30 E1\n")
    assert result.filament_mm == pytest.approx(3.0)
    assert result.extrude_path_mm == pytest.approx(30.0)


def test_retract_and_unretract_do_not_count_as_filament() -> None:
    result = run("M83\nG1 X10 E1 F1200\nG1 E-0.8\nG1 X50\nG1 E0.8\nG1 X60 E1\n")
    assert result.filament_mm == pytest.approx(2.0)
    assert result.retractions == 1
    assert result.travel_mm == pytest.approx(40.0)
    assert result.extrude_path_mm == pytest.approx(20.0)


def test_wipe_while_retracting_is_one_retraction() -> None:
    result = run("M83\nG1 X10 E1 F1200\nG1 E-0.5\nG1 X8 E-0.3\nG1 X20\nG1 E0.8\nG1 X30 E1\n")
    assert result.retractions == 1
    assert result.filament_mm == pytest.approx(2.0)
    assert result.travel_mm == pytest.approx(14.0)


def test_firmware_retraction_is_counted() -> None:
    result = run("G10\nG11\nG10 P1 X5\n")
    assert result.retractions == 1


def test_g91_makes_xyz_and_e_relative() -> None:
    result = run("G91\nG1 X10 E1 F1200\nG1 X10 E1\n")
    assert result.filament_mm == pytest.approx(2.0)
    assert result.bounding_box is not None
    assert result.bounding_box.max_x == 20.0


def test_explicit_m82_survives_g91() -> None:
    result = run("M82\nG91\nG1 X10 E1 F1200\nG1 X10 E2\n")
    assert result.filament_mm == pytest.approx(2.0)
    assert result.bounding_box is not None
    assert result.bounding_box.max_x == 20.0


def test_explicit_m83_survives_g90() -> None:
    result = run("M83\nG90\nG1 X10 E1 F1200\nG1 X20 E1\n")
    assert result.filament_mm == pytest.approx(2.0)


def test_g90_restores_absolute_e_when_never_pinned() -> None:
    result = run("G91\nG90\nG1 X10 E1 F1200\nG1 X20 E3\n")
    assert result.filament_mm == pytest.approx(3.0)


def test_g92_sets_axis_positions() -> None:
    result = run("G92 X50 Y50\nM83\nG1 X60 E1 F1200\n")
    box = result.bounding_box
    assert box is not None
    assert (box.min_x, box.max_x, box.min_y) == (50.0, 60.0, 50.0)


def test_g28_homes_named_axes_only() -> None:
    result = run("M83\nG1 X50 Y50 Z5 F6000\nG28 X\nG1 X10 E1\n")
    box = result.bounding_box
    assert box is not None
    assert (box.min_x, box.max_x, box.min_y, box.min_z) == (0.0, 10.0, 50.0, 5.0)


def test_g28_without_axes_homes_everything() -> None:
    result = run("M83\nG1 X50 Y50 Z5 F6000\nG28\nG1 X10 E1\n")
    box = result.bounding_box
    assert box is not None
    assert (box.min_x, box.max_x, box.min_y, box.min_z) == (0.0, 10.0, 0.0, 0.0)


def test_inch_units() -> None:
    result = run("G20\nM83\nG1 X1 E0.1 F60\n")
    assert result.extrude_path_mm == pytest.approx(25.4)
    assert result.filament_mm == pytest.approx(2.54)
    # 60 in/min = 25.4 mm/s; 25.4 mm at 3000 mm/s^2: 1 s + v/a.
    assert result.estimated_time_s == pytest.approx(1.0 + 25.4 / 3000.0)


# --------------------------------------------------------------------- arcs


def test_quarter_arc_counter_clockwise() -> None:
    result = run("G90\nM83\nG1 X10 Y0 F3000\nG3 X0 Y10 I-10 J0 E1\n")
    assert result.extrude_path_mm == pytest.approx(5.0 * math.pi)
    box = result.bounding_box
    assert box is not None
    assert [box.min_x, box.max_x] == pytest.approx([0.0, 10.0], abs=1e-9)
    assert [box.min_y, box.max_y] == pytest.approx([0.0, 10.0], abs=1e-9)


def test_semicircle_bounding_box_includes_the_bulge() -> None:
    ccw = run("M83\nG1 X10 Y0 F3000\nG3 X-10 Y0 I-10 J0 E1\n")
    assert ccw.extrude_path_mm == pytest.approx(10.0 * math.pi)
    assert ccw.bounding_box is not None
    assert ccw.bounding_box.max_y == pytest.approx(10.0)
    assert ccw.bounding_box.min_y == pytest.approx(0.0, abs=1e-9)

    cw = run("M83\nG1 X10 Y0 F3000\nG2 X-10 Y0 I-10 J0 E1\n")
    assert cw.extrude_path_mm == pytest.approx(10.0 * math.pi)
    assert cw.bounding_box is not None
    assert cw.bounding_box.min_y == pytest.approx(-10.0)
    assert cw.bounding_box.max_y == pytest.approx(0.0, abs=1e-9)


def test_full_circle_when_start_equals_end() -> None:
    result = run("M83\nG1 X10 Y0 F3000\nG3 X10 Y0 I-10 J0 E2\n")
    assert result.extrude_path_mm == pytest.approx(20.0 * math.pi)
    box = result.bounding_box
    assert box is not None
    assert [box.min_x, box.max_x] == pytest.approx([-10.0, 10.0])
    assert [box.min_y, box.max_y] == pytest.approx([-10.0, 10.0])


def test_radius_form_minor_and_major_arc() -> None:
    minor = run("M83\nG1 X10 Y0 F3000\nG3 X0 Y10 R10 E1\n")
    assert minor.extrude_path_mm == pytest.approx(5.0 * math.pi)
    major = run("M83\nG1 X10 Y0 F3000\nG3 X0 Y10 R-10 E1\n")
    assert major.extrude_path_mm == pytest.approx(15.0 * math.pi)


def test_helical_travel_arc_length() -> None:
    result = run("G1 X10 Y0 F3000\nG3 X10 Y0 I-10 J0 Z5\n")
    assert result.travel_mm == pytest.approx(10.0 + math.hypot(20.0 * math.pi, 5.0))


def test_degenerate_arcs_fall_back_to_a_line() -> None:
    no_centre = run("M83\nG1 X10 Y0 F3000\nG3 X5 Y0 E1\n")
    assert no_centre.extrude_path_mm == pytest.approx(5.0)
    radius_too_small = run("M83\nG1 X10 Y0 F3000\nG3 X0 Y0 R2 E1\n")
    assert radius_too_small.extrude_path_mm == pytest.approx(10.0)


def test_arc_time_uses_arc_length() -> None:
    # Quarter circle r = 10: 15.708 mm at 50 mm/s, 3000 mm/s^2, rest to rest = d/v + v/a.
    result = run("G92 X10 Y0\nG3 X0 Y10 I-10 J0 F3000\n")
    assert result.estimated_time_s == pytest.approx(5.0 * math.pi / 50.0 + 50.0 / 3000.0)


def test_arc_speed_is_limited_by_centripetal_acceleration() -> None:
    # r = 1 mm at 3000 mm/s^2 allows sqrt(3000) = 54.77 mm/s, below the commanded 100.
    result = run("G92 X1 Y0\nG3 X1 Y0 I-1 J0 F6000\n")
    speed = math.sqrt(3000.0)
    assert result.estimated_time_s == pytest.approx(2.0 * math.pi / speed + speed / 3000.0)


# --------------------------------------------------------------------- time


def test_known_duration_trapezoid_move() -> None:
    # 100 mm at F3000 (50 mm/s) with 1000 mm/s^2: 0.05 + 1.95 + 0.05 s.
    travel = run("M204 S1000\nG1 X100 F3000\n")
    assert travel.estimated_time_s == pytest.approx(2.05)
    printing = run("M83\nM204 S1000\nG1 X100 E3 F3000\n")
    assert printing.estimated_time_s == pytest.approx(2.05)


def test_print_and_travel_acceleration_are_separate() -> None:
    travel = run("M204 P1000 T2000\nG1 X100 F3000\n")
    assert travel.estimated_time_s == pytest.approx(2.0 + 50.0 / 2000.0)
    printing = run("M83\nM204 P1000 T2000\nG1 X100 E3 F3000\n")
    assert printing.estimated_time_s == pytest.approx(2.05)


def test_z_axis_limits_apply() -> None:
    # Default Z limits: 20 mm/s, 500 mm/s^2. 0.04 s + 0.4 mm each ramp, 9.2 mm cruise.
    result = run("G1 Z10 F6000\n")
    assert result.estimated_time_s == pytest.approx(0.04 + 0.04 + 9.2 / 20.0)


def test_axis_limit_scales_diagonal_moves() -> None:
    # X capped at 10 mm/s; a 3-4-5 move has 60 % of its speed in X -> 16.667 mm/s.
    result = run("M203 X10 Y500\nG1 X30 Y40 F6000\n")
    speed = 10.0 / 0.6
    assert result.estimated_time_s == pytest.approx(50.0 / speed + speed / 3000.0)


def test_gcode_limits_can_be_ignored() -> None:
    program = "M203 X10\nG1 X100 F6000\n"
    assert run(program).estimated_time_s == pytest.approx(10.0 + 10.0 / 3000.0)
    ignored = run(program, AnalysisOptions(honor_gcode_limits=False))
    assert ignored.estimated_time_s == pytest.approx(1.0 + 100.0 / 3000.0)
    assert run(
        "M204 S100\nM201 X50\nM220 S10\nG1 X100 F6000\n", AnalysisOptions(honor_gcode_limits=False)
    ).estimated_time_s == pytest.approx(1.0 + 100.0 / 3000.0)


def test_m201_and_m220() -> None:
    assert run("M201 X1000\nG1 X100 F3000\n").estimated_time_s == pytest.approx(2.05)
    assert run("M220 S50\nG1 X100 F6000\n").estimated_time_s == pytest.approx(2.0 + 50.0 / 3000.0)


def test_retraction_time_uses_extruder_limits() -> None:
    # 0.8 mm at 30 mm/s with the default 5000 mm/s^2 E acceleration:
    # two 0.006 s ramps covering 0.09 mm each, then 0.62 mm at 30 mm/s.
    result = run("M83\nG1 E-0.8 F1800\n")
    assert result.estimated_time_s == pytest.approx(0.012 + 0.62 / 30.0)


def test_corner_uses_junction_speed() -> None:
    options = AnalysisOptions(machine=MachineProfile(jerk=10.0))
    result = run("M204 S1000\nG1 X100 F3000\nG1 Y100\n", options)
    assert result.estimated_time_s == pytest.approx(2.0 * (0.05 + 0.0429289 + 1.9505), abs=1e-6)


def test_custom_machine_profile() -> None:
    machine = MachineProfile(travel_accel=500.0, max_feedrate=(40.0, 40.0, 5.0, 25.0))
    result = run("G1 X100 F6000\n", AnalysisOptions(machine=machine))
    assert result.estimated_time_s == pytest.approx(100.0 / 40.0 + 40.0 / 500.0)


def test_initial_feedrate_applies_before_any_f_word() -> None:
    result = run("G1 X100\n")
    assert result.estimated_time_s == pytest.approx(2.0 + 50.0 / 3000.0)


def test_dwell_adds_time() -> None:
    result = run("G4 P500\nG4 S2\n")
    assert result.dwell_time_s == pytest.approx(2.5)
    assert result.estimated_time_s == pytest.approx(2.5)


def test_dwell_stops_motion() -> None:
    result = run("M204 S1000\nG1 X50 F3000\nG4 P250\nG1 X100\n")
    one_move = 50.0 / 50.0 + 50.0 / 1000.0
    assert result.estimated_time_s == pytest.approx(2.0 * one_move + 0.25)


def test_comparison_with_slicer_estimate() -> None:
    result = run("; estimated printing time (normal mode) = 10s\nM204 S1000\nG1 X100 F3000\n")
    comparison = result.time_comparison
    assert comparison is not None
    assert comparison.basis == "total estimated time"
    assert comparison.slicer_time_s == 10.0
    assert comparison.estimate_s == pytest.approx(2.05)
    assert comparison.difference_s == pytest.approx(-7.95)
    assert comparison.ratio == pytest.approx(0.205)


def test_comparison_prefers_bambu_model_time() -> None:
    result = run("; model printing time: 4s; total estimated time: 6m 4s\nG1 X100 F3000\n")
    comparison = result.time_comparison
    assert comparison is not None
    assert comparison.basis == "model printing time"
    assert comparison.slicer_time_s == 4.0
    assert result.metadata.estimated_time_s == 364.0


def test_no_comparison_without_slicer_estimate() -> None:
    assert run("G1 X100 F3000\n").time_comparison is None


# ------------------------------------------------------------------- layers

Z_HOP_PROGRAM = """M83
G1 Z0.2 F600
G1 X10 E1 F1200
G1 Z0.6
G1 X0
G1 Z0.4
G1 X10 E2
G1 X0 E2
"""


def test_layers_from_z_changes_ignore_z_hops() -> None:
    result = run(Z_HOP_PROGRAM)
    assert result.layer_mode == "z"
    assert [layer.index for layer in result.layers] == [1, 2]
    assert [layer.z for layer in result.layers] == [0.2, 0.4]
    assert [layer.filament_mm for layer in result.layers] == [
        pytest.approx(1.0),
        pytest.approx(4.0),
    ]
    assert [layer.extrude_path_mm for layer in result.layers] == [10.0, 20.0]
    # Hop up 0.4, travel 10, hop down 0.2 all happen before layer 2's first extrusion.
    assert result.layers[0].travel_mm == pytest.approx(10.6)
    assert result.startup.travel_mm == pytest.approx(0.2)


MARKER_PROGRAM = """M83
G1 Z0.3 F600
G1 X50 E5 F1200
;LAYER_CHANGE
;Z:0.2
G1 Z0.2
G1 X60 E1
;LAYER_CHANGE
;Z:0.4
G1 Z0.4
G1 X70 E1.5
"""


def test_layers_from_markers_keep_purge_out_of_layer_one() -> None:
    result = run(MARKER_PROGRAM)
    assert result.layer_mode == "markers"
    assert result.layer_count == 2
    assert result.startup.filament_mm == pytest.approx(5.0)
    assert [layer.filament_mm for layer in result.layers] == [
        pytest.approx(1.0),
        pytest.approx(1.5),
    ]
    assert [layer.z for layer in result.layers] == [0.2, 0.4]
    assert result.filament_mm == pytest.approx(7.5)


def test_same_program_without_markers_counts_the_purge_as_a_layer() -> None:
    stripped = "\n".join(line for line in MARKER_PROGRAM.splitlines() if not line.startswith(";"))
    result = run(stripped)
    assert result.layer_mode == "z"
    assert result.layer_count == 3


def test_doubled_markers_open_one_layer() -> None:
    result = run(
        "M83\n;LAYER_CHANGE\n; CHANGE_LAYER\nG1 X10 E1 F1200\n"
        ";LAYER_CHANGE\n; CHANGE_LAYER\nG1 X20 E1\n"
    )
    assert result.layer_count == 2


def test_cura_layer_markers() -> None:
    result = run("M83\n;LAYER:0\nG1 X10 E1 F1200\n;LAYER:1\nG1 X20 E1\n;LAYER:top\n")
    assert result.layer_mode == "markers"
    assert result.layer_count == 2


def test_layer_times_add_up_to_the_total() -> None:
    result = run(Z_HOP_PROGRAM + "G4 P300\n")
    parts = result.startup.time_s + sum(layer.time_s for layer in result.layers)
    assert parts == pytest.approx(result.estimated_time_s)
    assert result.layers[-1].time_s > 0.3


def test_retractions_are_attributed_to_layers() -> None:
    result = run("M83\nG1 Z0.2 F600\nG1 X10 E1\nG1 E-1\nG1 Z0.4\nG1 E1\nG1 X20 E1\nG1 E-1\n")
    assert [layer.retractions for layer in result.layers] == [1, 1]
    assert result.retractions == 2


# -------------------------------------------------------- tools, temps, fans

TOOL_PROGRAM = """M83
T0
G1 X10 E1 F1200
T1
G1 X20 E2
T1000
G1 X30 E3
T0
G1 X40 E4
"""


def test_per_tool_usage_and_tool_changes() -> None:
    result = run(TOOL_PROGRAM)
    assert [tool.tool for tool in result.tools] == [0, 1]
    assert [tool.filament_mm for tool in result.tools] == pytest.approx([5.0, 5.0])
    assert result.tool_changes == 2  # T1000 is a firmware-internal selector, not a filament
    assert result.filament_mm == pytest.approx(10.0)


def test_per_tool_material_from_metadata() -> None:
    result = run("; filament_type = PLA;PETG\n" + TOOL_PROGRAM)
    first, second = result.tools
    assert (first.material, first.density) == ("PLA", 1.24)
    assert (second.material, second.density) == ("PETG", 1.27)
    expected = 5.0 * FILAMENT_AREA / 1000.0 * (1.24 + 1.27)
    assert result.mass_g == pytest.approx(expected)
    assert result.warnings == []


def test_metadata_density_beats_the_table() -> None:
    result = run("; filament_type = PLA\n; filament_density = 1.30\nM83\nG1 X10 E10 F1200\n")
    assert result.tools[0].density == 1.30
    assert result.tools[0].material == "PLA"


def test_unknown_tool_material_falls_back_with_a_warning() -> None:
    result = run("; filament_type = PA6-GF\nM83\nG1 X10 E10 F1200\n")
    assert result.tools[0].density == 1.24
    assert any("assumes PLA density" in warning for warning in result.warnings)


def test_temperatures_and_fans() -> None:
    result = run(
        "M104 S200\nM109 S215\nM104 S0\nM140 S60\nM190 R55\nM106 S127.5\nM106 P2\nM107\nM106 S64\n"
    )
    assert result.nozzle_temp_max == 215.0
    assert result.bed_temp_max == 60.0
    assert result.fan_max_percent == {0: pytest.approx(50.0), 2: pytest.approx(100.0)}


# ------------------------------------------------------------------ options


def test_density_material_and_diameter_options() -> None:
    program = "M83\nG1 X100 E100 F1200\n"
    volume = 100.0 * FILAMENT_AREA / 1000.0
    assert run(program, AnalysisOptions(density=1.0)).mass_g == pytest.approx(volume)
    petg = run(program, AnalysisOptions(material="petg"))
    assert petg.mass_g == pytest.approx(volume * 1.27)
    assert petg.warnings == []
    thick = run(program, AnalysisOptions(filament_diameter=2.85))
    assert thick.volume_cm3 == pytest.approx(100.0 * math.pi * 1.425**2 / 1000.0)
    both = run(program, AnalysisOptions(material="ABS", density=2.0))
    assert both.tools[0].density == 2.0


def test_metadata_diameter_is_used() -> None:
    result = run("; filament_diameter = 2.85\nM83\nG1 X100 E100 F1200\n")
    assert result.tools[0].diameter == 2.85


def test_default_density_warning() -> None:
    result = run("M83\nG1 X10 E1 F1200\n")
    assert len(result.warnings) == 1
    assert "PLA density" in result.warnings[0]


def test_invalid_options_are_rejected() -> None:
    with pytest.raises(ValueError):
        AnalysisOptions(material="unobtainium")
    with pytest.raises(ValueError):
        AnalysisOptions(density=0.0)
    with pytest.raises(ValueError):
        AnalysisOptions(filament_diameter=-1.75)
    with pytest.raises(ValueError):
        MachineProfile(jerk=0.0)


def test_empty_and_motionless_input() -> None:
    for program in ("", "; just a comment\nM117 hello\nG1 F3000\n"):
        result = run(program)
        assert result.layer_count == 0
        assert result.bounding_box is None
        assert result.filament_mm == 0.0
        assert result.mass_g == 0.0
        assert result.estimated_time_s == 0.0
        assert result.tools == []
        assert any("no extrusion" in warning for warning in result.warnings)


def test_to_dict_is_json_serialisable() -> None:
    result = run("; filament_type = PLA\nM106 S255\n" + MARKER_PROGRAM)
    data = json.loads(json.dumps(result.to_dict()))
    assert data["layer_count"] == 2
    assert data["layer_mode"] == "markers"
    assert data["filament_mm"] == pytest.approx(7.5)
    assert data["metadata"]["filament_type"] == ["PLA"]
    assert data["fan_max_percent"] == {"0": 100.0}
    assert len(data["layers"]) == 2
    assert data["bounding_box"]["max_x"] == 70.0
