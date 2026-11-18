"""Plain-text renderings for the terminal."""

from __future__ import annotations

from .analysis import Analysis
from .cost import CostBreakdown

__all__ = ["format_analysis", "format_compare", "format_cost", "format_duration"]


def format_duration(seconds: float) -> str:
    """``3723`` -> ``"1h 02m 03s"``; sub-minute values keep one decimal."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _rows(pairs: list[tuple[str, str]]) -> list[str]:
    width = max(len(label) for label, _ in pairs)
    return [f"  {label.ljust(width)}  {value}" for label, value in pairs]


def _slicer_label(analysis: Analysis) -> str:
    meta = analysis.metadata
    if meta.slicer is None:
        return "unknown (no slicer comments recognised)"
    return f"{meta.slicer} {meta.slicer_version or ''}".strip()


def format_analysis(analysis: Analysis, max_layers: int = 12) -> str:
    """Human-readable summary. ``max_layers`` caps the per-layer table (0 = all)."""
    meta = analysis.metadata
    lines = [f"G-code analysis: {analysis.source}", ""]

    layer_basis = "slicer markers" if analysis.layer_mode == "markers" else "Z changes"
    file_rows = [
        ("Slicer", _slicer_label(analysis)),
        ("Lines", f"{analysis.line_count}"),
        ("Layers", f"{analysis.layer_count} (detected from {layer_basis})"),
    ]
    if meta.layer_height is not None:
        file_rows.append(("Layer height", f"{meta.layer_height:g} mm"))
    if meta.nozzle_diameter is not None:
        file_rows.append(("Nozzle", f"{meta.nozzle_diameter:g} mm"))
    box = analysis.bounding_box
    if box is not None:
        sx, sy, sz = box.size
        file_rows.append(
            (
                "Bounding box",
                f"{sx:.2f} x {sy:.2f} x {sz:.2f} mm "
                f"(X {box.min_x:.2f}..{box.max_x:.2f}, Y {box.min_y:.2f}..{box.max_y:.2f}, "
                f"Z {box.min_z:.2f}..{box.max_z:.2f})",
            )
        )
    if analysis.nozzle_temp_max is not None:
        file_rows.append(("Nozzle temp (max)", f"{analysis.nozzle_temp_max:g} C"))
    if analysis.bed_temp_max is not None:
        file_rows.append(("Bed temp (max)", f"{analysis.bed_temp_max:g} C"))
    if analysis.fan_max_percent:
        fans = ", ".join(f"P{i}: {v:.0f}%" for i, v in analysis.fan_max_percent.items())
        file_rows.append(("Fan (max)", fans))
    lines += ["File", *_rows(file_rows), ""]

    filament_rows = [
        ("Filament length", f"{analysis.filament_mm:.2f} mm ({analysis.filament_mm / 1000:.3f} m)"),
        ("Volume", f"{analysis.volume_cm3:.3f} cm^3"),
        ("Mass", f"{analysis.mass_g:.2f} g"),
    ]
    if len(analysis.tools) > 1 or any(tool.tool != 0 for tool in analysis.tools):
        for tool in analysis.tools:
            filament_rows.append(
                (
                    f"  T{tool.tool} {tool.material or '?'}",
                    f"{tool.filament_mm:.2f} mm, {tool.mass_g:.2f} g "
                    f"(density {tool.density:g} g/cm^3)",
                )
            )
    elif analysis.tools:
        tool = analysis.tools[0]
        filament_rows.append(
            (
                "Material",
                f"{tool.material or 'unknown'} (density {tool.density:g} g/cm^3, "
                f"diameter {tool.diameter:g} mm)",
            )
        )
    if meta.filament_used_mm:
        filament_rows.append(("Slicer says", f"{sum(meta.filament_used_mm):.2f} mm"))
    if meta.filament_used_g:
        filament_rows.append(("Slicer mass", f"{sum(meta.filament_used_g):.2f} g"))
    lines += ["Filament", *_rows(filament_rows), ""]

    motion_rows = [
        ("Extrusion path", f"{analysis.extrude_path_mm:.1f} mm"),
        ("Travel path", f"{analysis.travel_mm:.1f} mm"),
        ("Retractions", f"{analysis.retractions}"),
        ("Tool changes", f"{analysis.tool_changes}"),
    ]
    lines += ["Motion", *_rows(motion_rows), ""]

    time_rows = [("Model estimate", format_duration(analysis.estimated_time_s))]
    if analysis.dwell_time_s > 0:
        time_rows.append(("  of which dwell", format_duration(analysis.dwell_time_s)))
    comparison = analysis.time_comparison
    if comparison is not None:
        time_rows.append(
            (f"Slicer ({comparison.basis})", format_duration(comparison.slicer_time_s))
        )
        if comparison.ratio is not None:
            time_rows.append(
                (
                    "Model vs slicer",
                    f"{comparison.difference_s:+.0f} s ({(comparison.ratio - 1) * 100:+.1f}%)",
                )
            )
    else:
        time_rows.append(("Slicer estimate", "not present in file"))
    lines += [
        "Time (trapezoidal model; excludes heating, homing, levelling, filament changes)",
        *_rows(time_rows),
        "",
    ]

    if analysis.layers:
        shown = analysis.layers if max_layers <= 0 else analysis.layers[:max_layers]
        lines.append("Layers")
        lines.append("  layer       Z   filament mm   extrude mm   travel mm     time")
        for layer in shown:
            z_text = f"{layer.z:.2f}" if layer.z is not None else "-"
            lines.append(
                f"  {layer.index:5d} {z_text:>7} {layer.filament_mm:13.2f} "
                f"{layer.extrude_path_mm:12.1f} {layer.travel_mm:11.1f} "
                f"{format_duration(layer.time_s):>8}"
            )
        hidden = len(analysis.layers) - len(shown)
        if hidden > 0:
            lines.append(f"  ... {hidden} more layers (use --all-layers, --json or --html)")
        lines.append("")

    for warning in analysis.warnings:
        lines.append(f"warning: {warning}")
    return "\n".join(lines).rstrip() + "\n"


def format_cost(
    analysis: Analysis,
    cost: CostBreakdown,
    time_source: str,
    currency: str = "",
) -> str:
    """Cost breakdown for one copy and for the batch."""

    def money(value: float) -> str:
        return f"{currency}{value:,.2f}"

    lines = [f"Cost estimate: {analysis.source}", ""]
    basis_rows = [
        ("Filament mass", f"{cost.mass_g:.2f} g"),
        ("Print time", f"{format_duration(cost.time_s)} ({time_source})"),
    ]
    lines += ["Basis (one copy)", *_rows(basis_rows), ""]
    unit_rows = [
        ("Filament", money(cost.filament)),
        ("Machine time", money(cost.machine)),
        ("Electricity", money(cost.electricity)),
        ("Failure allowance", money(cost.failure_allowance)),
        ("Setup share", money(cost.setup_share)),
        ("Unit cost", money(cost.unit_cost)),
        ("Suggested price", money(cost.unit_price)),
    ]
    lines += ["Per copy", *_rows(unit_rows), ""]
    if cost.copies > 1:
        batch_rows = [
            ("Filament mass", f"{cost.batch_mass_g:.1f} g"),
            ("Machine time", format_duration(cost.batch_time_s)),
            ("Batch cost", money(cost.batch_cost)),
            ("Batch price", money(cost.batch_price)),
        ]
        lines += [f"Batch of {cost.copies}", *_rows(batch_rows), ""]
    for warning in analysis.warnings:
        lines.append(f"warning: {warning}")
    return "\n".join(lines).rstrip() + "\n"


def _delta(a: float, b: float, unit: str, digits: int) -> str:
    diff = b - a
    text = f"{diff:+.{digits}f} {unit}".rstrip()
    if a > 0:
        text += f" ({diff / a * 100:+.1f}%)"
    return text


def format_compare(a: Analysis, b: Analysis) -> str:
    """Side-by-side comparison; the delta column is B minus A."""
    box_a, box_b = a.bounding_box, b.bounding_box
    height_a = box_a.max_z if box_a is not None else 0.0
    height_b = box_b.max_z if box_b is not None else 0.0
    table: list[tuple[str, str, str, str]] = [
        ("Slicer", _short_slicer(a), _short_slicer(b), ""),
        ("Layers", str(a.layer_count), str(b.layer_count), f"{b.layer_count - a.layer_count:+d}"),
        (
            "Filament",
            f"{a.filament_mm:.1f} mm",
            f"{b.filament_mm:.1f} mm",
            _delta(a.filament_mm, b.filament_mm, "mm", 1),
        ),
        ("Mass", f"{a.mass_g:.2f} g", f"{b.mass_g:.2f} g", _delta(a.mass_g, b.mass_g, "g", 2)),
        (
            "Model time",
            format_duration(a.estimated_time_s),
            format_duration(b.estimated_time_s),
            _delta(a.estimated_time_s, b.estimated_time_s, "s", 0),
        ),
        (
            "Extrusion path",
            f"{a.extrude_path_mm:.1f} mm",
            f"{b.extrude_path_mm:.1f} mm",
            _delta(a.extrude_path_mm, b.extrude_path_mm, "mm", 1),
        ),
        (
            "Travel path",
            f"{a.travel_mm:.1f} mm",
            f"{b.travel_mm:.1f} mm",
            _delta(a.travel_mm, b.travel_mm, "mm", 1),
        ),
        (
            "Retractions",
            str(a.retractions),
            str(b.retractions),
            f"{b.retractions - a.retractions:+d}",
        ),
        (
            "Max Z",
            f"{height_a:.2f} mm",
            f"{height_b:.2f} mm",
            _delta(height_a, height_b, "mm", 2),
        ),
    ]
    header = ("", f"A: {a.source}", f"B: {b.source}", "B - A")
    widths = [max(len(row[i]) for row in [header, *table]) for i in range(4)]
    out = []
    for row in [header, *table]:
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(out) + "\n"


def _short_slicer(analysis: Analysis) -> str:
    return analysis.metadata.slicer or "unknown"
