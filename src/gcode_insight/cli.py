"""Command-line interface: ``gcode-insight analyze | cost | compare``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .analysis import Analysis, AnalysisOptions, MachineProfile, analyze_file
from .cost import CostInputs, compute_cost
from .html_report import render_html
from .report import format_analysis, format_compare, format_cost

__all__ = ["build_parser", "main"]


def _add_out_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        metavar="FILE",
        help="write the output (text or --json) to FILE as UTF-8 without a BOM "
        "instead of printing it; use this rather than '>' in PowerShell",
    )


def _add_analysis_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("filament")
    group.add_argument(
        "--filament-diameter",
        type=float,
        metavar="MM",
        help="filament diameter (default: slicer metadata, else 1.75)",
    )
    group.add_argument(
        "--material",
        metavar="NAME",
        help="material for the density table: PLA, PETG, ABS, ASA, TPU",
    )
    group.add_argument(
        "--density",
        type=float,
        metavar="G_CM3",
        help="filament density in g/cm^3 (overrides --material and metadata)",
    )
    group.add_argument(
        "--plate",
        type=int,
        metavar="N",
        help="plate number inside a .gcode.3mf archive (default: lowest)",
    )
    defaults = MachineProfile()
    group = parser.add_argument_group("time model")
    group.add_argument(
        "--accel",
        type=float,
        metavar="MM_S2",
        help=f"acceleration for extruding moves (default {defaults.print_accel:g})",
    )
    group.add_argument(
        "--travel-accel",
        type=float,
        metavar="MM_S2",
        help=f"acceleration for travel moves (default {defaults.travel_accel:g})",
    )
    group.add_argument(
        "--max-feedrate",
        type=float,
        nargs=4,
        metavar=("X", "Y", "Z", "E"),
        help="maximum speed per axis in mm/s (default {:g} {:g} {:g} {:g})".format(
            *defaults.max_feedrate
        ),
    )
    group.add_argument(
        "--max-accel",
        type=float,
        nargs=4,
        metavar=("X", "Y", "Z", "E"),
        help="maximum acceleration per axis in mm/s^2 (default {:g} {:g} {:g} {:g})".format(
            *defaults.max_accel
        ),
    )
    group.add_argument(
        "--jerk",
        type=float,
        metavar="MM_S",
        help=f"junction speed step (default {defaults.jerk:g})",
    )
    group.add_argument(
        "--ignore-gcode-limits",
        action="store_true",
        help="do not apply M201/M203/M204/M220 from the file; use only the values above",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gcode-insight",
        description="Analyse FDM G-code files without a printer: filament, time, layers, cost.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    analyze = commands.add_parser(
        "analyze", help="print statistics for one file", description="Analyse one G-code file."
    )
    analyze.add_argument("file", type=Path, help="G-code file (.gcode or .gcode.3mf)")
    analyze.add_argument("--json", action="store_true", help="print JSON instead of text")
    analyze.add_argument("--html", type=Path, metavar="OUT", help="also write an HTML report")
    analyze.add_argument(
        "--all-layers", action="store_true", help="list every layer in the text summary"
    )
    _add_out_option(analyze)
    _add_analysis_options(analyze)

    cost = commands.add_parser(
        "cost",
        help="estimate cost and price",
        description="Estimate per-print cost and a suggested price; see the README for formulas.",
    )
    cost.add_argument("file", type=Path, help="G-code file (.gcode or .gcode.3mf)")
    cost.add_argument(
        "--filament-price",
        type=float,
        required=True,
        metavar="PER_KG",
        help="filament price per kg",
    )
    cost.add_argument(
        "--machine-rate", type=float, default=0.0, metavar="PER_HOUR", help="machine hourly rate"
    )
    cost.add_argument(
        "--power", type=float, default=0.0, metavar="WATTS", help="average power draw in watts"
    )
    cost.add_argument(
        "--kwh-price", type=float, default=0.0, metavar="PER_KWH", help="electricity price per kWh"
    )
    cost.add_argument(
        "--failure-rate",
        type=float,
        default=0.0,
        metavar="PCT",
        help="share of prints that fail, in percent (default 0)",
    )
    cost.add_argument(
        "--margin", type=float, default=0.0, metavar="PCT", help="markup on cost, in percent"
    )
    cost.add_argument(
        "--setup-cost", type=float, default=0.0, metavar="AMOUNT", help="fixed cost per batch"
    )
    cost.add_argument("--copies", type=int, default=1, metavar="N", help="batch size (default 1)")
    cost.add_argument(
        "--time-source",
        choices=("auto", "model", "slicer"),
        default="auto",
        help="print time to cost: the slicer's estimate, this tool's model, "
        "or auto = slicer if present (default)",
    )
    cost.add_argument("--currency", default="", metavar="SYMBOL", help="prefix for amounts")
    cost.add_argument("--json", action="store_true", help="print JSON instead of text")
    cost.add_argument("--html", type=Path, metavar="OUT", help="also write an HTML report")
    _add_out_option(cost)
    _add_analysis_options(cost)

    compare = commands.add_parser(
        "compare",
        help="compare two files",
        description="Compare two G-code files, e.g. two slicings of the same model.",
    )
    compare.add_argument("file_a", type=Path, metavar="A")
    compare.add_argument("file_b", type=Path, metavar="B")
    compare.add_argument("--json", action="store_true", help="print JSON instead of text")
    _add_out_option(compare)
    _add_analysis_options(compare)
    return parser


def _options(args: argparse.Namespace) -> AnalysisOptions:
    defaults = MachineProfile()
    machine = MachineProfile(
        max_feedrate=tuple(args.max_feedrate) if args.max_feedrate else defaults.max_feedrate,
        max_accel=tuple(args.max_accel) if args.max_accel else defaults.max_accel,
        print_accel=args.accel if args.accel is not None else defaults.print_accel,
        travel_accel=(
            args.travel_accel if args.travel_accel is not None else defaults.travel_accel
        ),
        jerk=args.jerk if args.jerk is not None else defaults.jerk,
    )
    return AnalysisOptions(
        filament_diameter=args.filament_diameter,
        density=args.density,
        material=args.material,
        machine=machine,
        honor_gcode_limits=not args.ignore_gcode_limits,
    )


def _pick_time(analysis: Analysis, source: str) -> tuple[float, str]:
    slicer_time = analysis.metadata.estimated_time_s
    if source == "slicer" and slicer_time is None:
        raise ValueError("--time-source slicer: the file has no slicer time estimate")
    if source in ("slicer", "auto") and slicer_time is not None:
        return slicer_time, "slicer estimate"
    return analysis.estimated_time_s, "gcode-insight model"


def _run(args: argparse.Namespace) -> int:
    options = _options(args)
    if args.command == "compare":
        first = analyze_file(args.file_a, options, args.plate)
        second = analyze_file(args.file_b, options, args.plate)
        if args.json:
            _emit(args, json.dumps({"a": first.to_dict(), "b": second.to_dict()}, indent=2) + "\n")
        else:
            _emit(args, format_compare(first, second))
        return 0

    analysis = analyze_file(args.file, options, args.plate)
    if args.command == "analyze":
        if args.html is not None:
            args.html.write_text(render_html(analysis), encoding="utf-8")
        if args.json:
            _emit(args, json.dumps(analysis.to_dict(), indent=2) + "\n")
        else:
            _emit(args, format_analysis(analysis, max_layers=0 if args.all_layers else 12))
        return 0

    inputs = CostInputs(
        filament_price_per_kg=args.filament_price,
        machine_rate_per_hour=args.machine_rate,
        power_watts=args.power,
        electricity_price_per_kwh=args.kwh_price,
        failure_rate=args.failure_rate / 100.0,
        margin=args.margin / 100.0,
        setup_cost=args.setup_cost,
        copies=args.copies,
    )
    time_s, time_label = _pick_time(analysis, args.time_source)
    breakdown = compute_cost(analysis.mass_g, time_s, inputs)
    if args.html is not None:
        args.html.write_text(render_html(analysis, breakdown, args.currency), encoding="utf-8")
    if args.json:
        payload = {
            "source": analysis.source,
            "time_source": time_label,
            "cost": breakdown.to_dict(),
            "warnings": analysis.warnings,
        }
        _emit(args, json.dumps(payload, indent=2) + "\n")
    else:
        _emit(args, format_cost(analysis, breakdown, time_label, args.currency))
    return 0


def _emit(args: argparse.Namespace, text: str) -> None:
    """Print ``text``, or write it to ``--out`` as UTF-8 without a byte-order mark.

    Redirecting with ``>`` in Windows PowerShell 5.1 re-encodes the output (UTF-16 by default,
    UTF-8 with a byte-order mark when ``Out-File`` is set to ``utf8``), which strict JSON
    readers reject; ``--out`` avoids the shell entirely.
    """
    if args.out is None:
        sys.stdout.write(text)
        return
    args.out.write_text(text, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (OSError, ValueError) as error:
        print(f"gcode-insight: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
