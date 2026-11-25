from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from gcode_insight import (
    CostInputs,
    __version__,
    analyze_file,
    analyze_lines,
    compute_cost,
    format_analysis,
    format_compare,
    format_duration,
    render_html,
)
from gcode_insight.cli import main
from gcode_insight.html_report import _nice_ticks
from gcode_insight.reader import list_plates, read_gcode_lines

FIXTURES = Path(__file__).parent / "fixtures"
BAMBU = FIXTURES / "bambu_cube.gcode"
ORCA = FIXTURES / "orca_cube.gcode"
PRUSA = FIXTURES / "prusa_cube.gcode"
MARLIN = FIXTURES / "marlin_generic.gcode"


# --------------------------------------------------------------- formatting


def test_format_duration() -> None:
    assert format_duration(0.0) == "0.0s"
    assert format_duration(42.34) == "42.3s"
    assert format_duration(60.0) == "1m 00s"
    assert format_duration(125.4) == "2m 05s"
    assert format_duration(3723.0) == "1h 02m 03s"
    assert format_duration(90000.0) == "25h 00m 00s"


def test_text_summary_contents() -> None:
    text = format_analysis(analyze_file(BAMBU))
    assert text.startswith("G-code analysis: bambu_cube.gcode\n")
    assert "BambuStudio 01.10.01.50" in text
    assert "5 (detected from slicer markers)" in text
    assert "T0 PLA" in text and "T1 PETG" in text
    assert "Slicer (model printing time)" in text
    assert "Tool changes    1" in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_text_summary_truncates_long_layer_tables() -> None:
    analysis = analyze_file(PRUSA)
    short = format_analysis(analysis, max_layers=2)
    assert "... 4 more layers" in short
    assert "more layers" not in format_analysis(analysis, max_layers=0)


def test_text_summary_without_metadata() -> None:
    text = format_analysis(analyze_file(MARLIN))
    assert "unknown (no slicer comments recognised)" in text
    assert "detected from Z changes" in text
    assert "not present in file" in text
    assert "of which dwell" in text
    assert "warning: material unknown" in text


def test_compare_table() -> None:
    text = format_compare(analyze_file(ORCA), analyze_file(PRUSA))
    lines = text.splitlines()
    assert "A: orca_cube.gcode" in lines[0] and "B: prusa_cube.gcode" in lines[0]
    layers = next(line for line in lines if line.startswith("Layers"))
    assert layers.split() == ["Layers", "5", "6", "+1"]
    filament = next(line for line in lines if line.startswith("Filament"))
    assert "+11.7 mm (+20.0%)" in filament


# --------------------------------------------------------------------- html


def test_html_report_is_self_contained() -> None:
    analysis = analyze_file(BAMBU)
    cost = compute_cost(analysis.mass_g, 600.0, CostInputs(filament_price_per_kg=20.0, copies=3))
    page = render_html(analysis, cost, currency="$")
    assert page.startswith("<!DOCTYPE html>")
    assert page.count("<svg") == 2
    assert page.count('class="bar"') == 2 * analysis.layer_count
    for forbidden in ("http://", "https://", "<script", "<link", "<img", "@import", "url("):
        assert forbidden not in page
    assert "Time per layer (seconds)" in page
    assert "Filament per layer (mm of filament)" in page
    assert "Batch cost (3 copies)" in page
    assert "Suggested price" in page
    assert f"gcode-insight {__version__}" in page


def test_html_escapes_the_file_name() -> None:
    analysis = analyze_lines(["M83", "G1 X10 E1 F1200"], source="<b>&.gcode")
    page = render_html(analysis)
    assert "<b>&.gcode" not in page
    assert "&lt;b&gt;&amp;.gcode" in page
    assert "Unit cost" not in page


def test_html_without_layers_has_no_charts() -> None:
    page = render_html(analyze_lines(["G28"]))
    assert "<svg" not in page
    assert "no extrusion found" in page


def test_html_bins_very_long_prints() -> None:
    lines = ["M83"]
    for layer in range(500):
        lines += [f"G1 Z{0.2 * (layer + 1):.2f} F600", f"G1 X{10 + layer % 2} E1 F1200"]
    analysis = analyze_lines(lines)
    assert analysis.layer_count == 500
    page = render_html(analysis)
    assert page.count('class="bar"') == 2 * 167  # groups of 3 layers
    assert "Layers 1-3 (mean)" in page
    assert "averaged to fit" in page


def test_nice_ticks() -> None:
    assert _nice_ticks(0.0) == [0.0, 1.0]
    assert _nice_ticks(8.4) == [0.0, 5.0, 10.0]
    assert _nice_ticks(14.73) == [0.0, 5.0, 10.0, 15.0]
    assert _nice_ticks(100.0) == [0.0, 50.0, 100.0]
    assert _nice_ticks(0.37)[-1] == pytest.approx(0.4)


# ---------------------------------------------------------------------- cli


def test_cli_analyze_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", str(ORCA)]) == 0
    out = capsys.readouterr().out
    assert "G-code analysis: orca_cube.gcode" in out
    assert "OrcaSlicer 2.1.1" in out


def test_cli_analyze_json_and_html(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    report = tmp_path / "report.html"
    assert main(["analyze", str(PRUSA), "--json", "--html", str(report)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["source"] == "prusa_cube.gcode"
    assert data["layer_count"] == 6
    assert data["metadata"]["slicer"] == "PrusaSlicer"
    assert data["time_comparison"]["basis"] == "total estimated time"
    assert report.read_text(encoding="utf-8").count("<svg") == 2


def test_cli_analysis_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", str(MARLIN), "--json", "--material", "PETG"]) == 0
    base = json.loads(capsys.readouterr().out)
    assert base["tools"][0]["density"] == 1.27
    assert base["warnings"] == []
    args = [
        "analyze", str(MARLIN), "--json", "--density", "1.0", "--filament-diameter", "2.85",
        "--accel", "500", "--travel-accel", "500", "--jerk", "1",
        "--max-feedrate", "30", "30", "5", "20", "--max-accel", "500", "500", "100", "1000",
        "--ignore-gcode-limits",
    ]  # fmt: skip
    assert main(args) == 0
    slow = json.loads(capsys.readouterr().out)
    assert slow["tools"][0]["diameter"] == 2.85
    assert slow["mass_g"] == pytest.approx(slow["volume_cm3"])
    assert slow["estimated_time_s"] > base["estimated_time_s"]


def test_cli_cost_uses_slicer_time_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    args = [
        "cost", str(PRUSA), "--filament-price", "25", "--machine-rate", "2", "--power", "120",
        "--kwh-price", "0.3", "--failure-rate", "5", "--margin", "50", "--setup-cost", "1",
        "--copies", "4", "--json",
    ]  # fmt: skip
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    analysis = analyze_file(PRUSA)
    hours = 64.0 / 3600.0  # the fixture's footer says 1m 4s
    run_cost = analysis.mass_g / 1000 * 25 + hours * 2 + 0.12 * hours * 0.3
    unit_cost = run_cost / 0.95 + 0.25
    assert data["time_source"] == "slicer estimate"
    assert data["cost"]["time_s"] == 64.0
    assert data["cost"]["unit_cost"] == pytest.approx(unit_cost)
    assert data["cost"]["unit_price"] == pytest.approx(unit_cost * 1.5)
    assert data["cost"]["batch_price"] == pytest.approx(unit_cost * 1.5 * 4)


def test_cli_cost_text_and_model_time(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    report = tmp_path / "cost.html"
    args = [
        "cost", str(PRUSA), "--filament-price", "25", "--copies", "10", "--currency", "EUR ",
        "--time-source", "model", "--html", str(report),
    ]  # fmt: skip
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Cost estimate: prusa_cube.gcode" in out
    assert "(gcode-insight model)" in out
    assert "Batch of 10" in out
    assert re.search(r"Suggested price\s+EUR 0\.01", out)
    assert "Unit cost" in report.read_text(encoding="utf-8")


def test_cli_cost_falls_back_to_model_time(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["cost", str(MARLIN), "--filament-price", "20"]) == 0
    out = capsys.readouterr().out
    assert "(gcode-insight model)" in out
    assert "Batch of" not in out
    assert main(["cost", str(MARLIN), "--filament-price", "20", "--time-source", "slicer"]) == 2
    assert "no slicer time estimate" in capsys.readouterr().err


def test_cli_compare(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compare", str(ORCA), str(PRUSA)]) == 0
    assert "B - A" in capsys.readouterr().out
    assert main(["compare", str(ORCA), str(PRUSA), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["a"]["layer_count"] == 5 and data["b"]["layer_count"] == 6


def test_cli_errors(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["analyze", str(tmp_path / "missing.gcode")]) == 2
    assert "error" in capsys.readouterr().err
    assert main(["analyze", str(ORCA), "--material", "unobtainium"]) == 2
    assert "unknown material" in capsys.readouterr().err
    assert main(["analyze", str(ORCA), "--plate", "2"]) == 2
    assert "not a .3mf archive" in capsys.readouterr().err
    assert main(["cost", str(ORCA), "--filament-price", "20", "--failure-rate", "100"]) == 2
    assert "failure_rate" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["cost", str(ORCA)])  # --filament-price is required


def test_module_entry_point_reports_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "gcode_insight", "--version"],
        capture_output=True,
        text=True,
        check=True,
        env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert completed.stdout.strip() == f"gcode-insight {__version__}"


# ------------------------------------------------------------------- reader


def _make_3mf(path: Path, plates: dict[int, Path]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Metadata/slice_info.config", "<config/>")
        for number, source in plates.items():
            archive.write(source, f"Metadata/plate_{number}.gcode")


def test_gcode_3mf_archive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    archive = tmp_path / "job.gcode.3mf"
    _make_3mf(archive, {2: BAMBU, 3: ORCA})
    assert list_plates(archive) == [2, 3]
    default = analyze_file(archive)
    assert default.source == "job.gcode.3mf"
    assert default.filament_mm == pytest.approx(analyze_file(BAMBU).filament_mm)
    assert analyze_file(archive, plate=3).metadata.slicer == "OrcaSlicer"
    with pytest.raises(ValueError, match="plate 1 not found"):
        analyze_file(archive, plate=1)
    assert main(["analyze", str(archive), "--plate", "3"]) == 0
    assert "OrcaSlicer" in capsys.readouterr().out


def test_3mf_without_gcode_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "model.3mf"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("3D/3dmodel.model", "<model/>")
    with pytest.raises(ValueError, match="no sliced G-code"):
        list(read_gcode_lines(archive))


def test_undecodable_bytes_do_not_abort(tmp_path: Path) -> None:
    path = tmp_path / "latin.gcode"
    path.write_bytes(b"; caf\xe9 \xff\nM83\nG1 X10 E1 F1200\r\n")
    assert analyze_file(path).filament_mm == pytest.approx(1.0)


def test_json_carries_colour_printer_model_and_schema_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["analyze", str(BAMBU), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 4
    assert data["metadata"]["printer_model"] == "Bambu Lab P1S"
    assert data["metadata"]["filament_colour"] == ["#FFFFFF", "#161616"]
    assert [(t["tool"], t["material"], t["colour"]) for t in data["tools"]] == [
        (0, "PLA", "#FFFFFF"),
        (1, "PETG", "#161616"),
    ]
    assert main(["analyze", str(MARLIN), "--json"]) == 0
    plain = json.loads(capsys.readouterr().out)
    assert plain["metadata"]["printer_model"] is None
    assert plain["tools"][0]["colour"] is None


def test_text_summary_shows_printer_model_and_colours(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", str(PRUSA)]) == 0
    out = capsys.readouterr().out
    assert re.search(r"Sliced for\s+MK4S", out)
    assert "PETG #FF8000 (density 1.27" in out


@pytest.mark.parametrize("command", ["analyze", "cost", "compare"])
def test_out_writes_utf8_without_bom(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "result.json"
    args = {
        "analyze": ["analyze", str(BAMBU)],
        "cost": ["cost", str(BAMBU), "--filament-price", "20"],
        "compare": ["compare", str(ORCA), str(PRUSA)],
    }[command]
    assert main([*args, "--json", "--out", str(out)]) == 0
    assert capsys.readouterr().out == ""
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert isinstance(json.loads(raw.decode("utf-8")), dict)


def test_out_with_text_output(tmp_path: Path) -> None:
    out = tmp_path / "summary.txt"
    assert main(["analyze", str(ORCA), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("G-code analysis: orca_cube.gcode")


def test_cli_labels_cura_print_time_as_the_slicer_figure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cura = Path(__file__).parent / "fixtures" / "cura_griffin.gcode"
    assert main(["analyze", str(cura)]) == 0
    out = capsys.readouterr().out
    assert re.search(r"Slicer \(Cura ;PRINT\.TIME\)\s+1m 35s", out)
    assert "Model estimate" in out
    assert main(["analyze", str(cura), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["metadata"]["estimated_time_source"] == ";PRINT.TIME"
    assert data["time_comparison"]["basis"] == "Cura ;PRINT.TIME"
    assert data["time_comparison"]["slicer_time_s"] == 95.0
