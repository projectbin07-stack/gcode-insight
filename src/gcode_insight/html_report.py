"""Self-contained HTML report with inline SVG charts.

The page has no scripts, no external stylesheets, fonts or images: everything
is inline, so it can be archived next to the G-code or attached to a job ticket.
"""

from __future__ import annotations

import math
from html import escape

from . import __version__
from .analysis import Analysis, LayerStats
from .cost import CostBreakdown
from .report import format_duration

__all__ = ["render_html"]

_MAX_COLUMNS = 240
_WIDTH, _HEIGHT = 720.0, 240.0
_LEFT, _RIGHT, _TOP, _BOTTOM = 52.0, 8.0, 12.0, 30.0

_CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--panel:#ffffff;--border:#e3e2dd;
--text:#0b0b0b;--text-2:#52514e;--grid:#e3e2dd;--series:#2a78d6;--series-hover:#1c5cab}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--surface:#1a1a19;--panel:#232322;
--border:#3a3a37;--text:#f0efec;--text-2:#c3c2b7;--grid:#3a3a37;--series:#3987e5;
--series-hover:#6aa6ee}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 8px}
p.sub,figcaption,footer{color:var(--text-2);font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.tile{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px}
.tile .k{color:var(--text-2);font-size:12px}.tile .v{font-size:20px;font-weight:600}
.tile .n{color:var(--text-2);font-size:12px}
figure{margin:0;background:var(--panel);border:1px solid var(--border);border-radius:8px;
padding:12px}
svg{display:block;width:100%;height:auto}
svg text{fill:var(--text-2);font-size:11px;font-family:inherit}
.grid{stroke:var(--grid);stroke-width:1}.bar{fill:var(--series)}.hit{fill:transparent}
.col:hover .bar{fill:var(--series-hover)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:4px 8px;border-bottom:1px solid var(--border)}
th:first-child,td:first-child{text-align:left}th{color:var(--text-2);font-weight:500}
details{margin-top:8px}summary{cursor:pointer;color:var(--text-2);font-size:13px}
.warn{border-left:3px solid var(--text-2);padding:4px 10px;margin:8px 0;font-size:13px}
footer{margin-top:32px}
"""


def _nice_ticks(maximum: float, target: int = 4) -> list[float]:
    """Round tick values (1/2/5 x 10^k steps) covering 0..maximum."""
    if maximum <= 0:
        return [0.0, 1.0]
    raw = maximum / target
    magnitude = 10.0 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1.0, 2.0, 5.0, 10.0) if m * magnitude >= raw)
    count = math.ceil(maximum / step - 1e-9)
    return [step * i for i in range(count + 1)]


def _bin_layers(layers: list[LayerStats], attribute: str) -> list[tuple[str, float]]:
    """(label, value) per column; long prints are averaged into at most 240 columns."""
    group = max(1, math.ceil(len(layers) / _MAX_COLUMNS))
    columns: list[tuple[str, float]] = []
    for start in range(0, len(layers), group):
        chunk = layers[start : start + group]
        value = sum(float(getattr(layer, attribute)) for layer in chunk) / len(chunk)
        if len(chunk) == 1:
            label = f"Layer {chunk[0].index}"
        else:
            label = f"Layers {chunk[0].index}-{chunk[-1].index} (mean)"
        columns.append((label, value))
    return columns


def _column_chart(columns: list[tuple[str, float]], unit: str, title: str) -> str:
    plot_w = _WIDTH - _LEFT - _RIGHT
    plot_h = _HEIGHT - _TOP - _BOTTOM
    ticks = _nice_ticks(max((value for _, value in columns), default=0.0))
    top = ticks[-1]
    baseline = _TOP + plot_h
    parts = [f'<svg viewBox="0 0 {_WIDTH:g} {_HEIGHT:g}" role="img" aria-label="{escape(title)}">']
    for tick in ticks:
        y = baseline - tick / top * plot_h
        parts.append(
            f'<line class="grid" x1="{_LEFT:g}" x2="{_WIDTH - _RIGHT:g}" y1="{y:.1f}" '
            f'y2="{y:.1f}"/>'
        )
        parts.append(f'<text x="{_LEFT - 6:g}" y="{y + 4:.1f}" text-anchor="end">{tick:g}</text>')
    band = plot_w / len(columns)
    width = min(24.0, band - 2.0) if band >= 4.0 else band
    label_every = max(1, math.ceil(len(columns) / 12))
    for i, (label, value) in enumerate(columns):
        x = _LEFT + band * i + (band - width) / 2.0
        height = value / top * plot_h
        radius = min(4.0, width / 2.0, height)
        y = baseline - height
        bar = (
            f"M{x:.2f},{baseline:.2f}V{y + radius:.2f}Q{x:.2f},{y:.2f} {x + radius:.2f},{y:.2f}"
            f"H{x + width - radius:.2f}Q{x + width:.2f},{y:.2f} {x + width:.2f},{y + radius:.2f}"
            f"V{baseline:.2f}Z"
        )
        parts.append(
            f'<g class="col"><title>{escape(label)}: {value:.2f} {escape(unit)}</title>'
            f'<rect class="hit" x="{_LEFT + band * i:.2f}" y="{_TOP:g}" width="{band:.2f}" '
            f'height="{plot_h:g}"/><path class="bar" d="{bar}"/></g>'
        )
        if i % label_every == 0:
            short = label.split(" ")[1].split("-")[0]
            parts.append(
                f'<text x="{_LEFT + band * (i + 0.5):.1f}" y="{baseline + 16:.1f}" '
                f'text-anchor="middle">{escape(short)}</text>'
            )
    parts.append(
        f'<text x="{_LEFT + plot_w / 2:.1f}" y="{_HEIGHT - 1:g}" text-anchor="middle">layer</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _tile(key: str, value: str, note: str = "") -> str:
    note_html = f'<div class="n">{escape(note)}</div>' if note else ""
    return (
        f'<div class="tile"><div class="k">{escape(key)}</div>'
        f'<div class="v">{escape(value)}</div>{note_html}</div>'
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def render_html(
    analysis: Analysis,
    cost: CostBreakdown | None = None,
    currency: str = "",
) -> str:
    """Render ``analysis`` (and optionally a cost breakdown) as one HTML document."""
    meta = analysis.metadata
    slicer = f"{meta.slicer} {meta.slicer_version or ''}".strip() if meta.slicer else "unknown"
    comparison = analysis.time_comparison
    time_note = "trapezoidal model"
    if comparison is not None and comparison.ratio is not None:
        time_note = (
            f"slicer: {format_duration(comparison.slicer_time_s)}; "
            f"model is {(comparison.ratio - 1) * 100:+.1f}% vs slicer"
        )
    box = analysis.bounding_box
    size = "{:.1f} x {:.1f} x {:.1f} mm".format(*box.size) if box is not None else "n/a"

    tiles = [
        _tile("Estimated time (model)", format_duration(analysis.estimated_time_s), time_note),
        _tile(
            "Filament", f"{analysis.filament_mm / 1000:.2f} m", f"{analysis.volume_cm3:.2f} cm^3"
        ),
        _tile("Mass", f"{analysis.mass_g:.1f} g"),
        _tile("Layers", str(analysis.layer_count), f"from {analysis.layer_mode}"),
        _tile("Retractions", str(analysis.retractions)),
        _tile("Extruded extent", size),
    ]
    if cost is not None:
        tiles.append(_tile("Unit cost", f"{currency}{cost.unit_cost:,.2f}"))
        tiles.append(_tile("Suggested price", f"{currency}{cost.unit_price:,.2f}"))

    sections: list[str] = []
    if analysis.layers:
        binned = len(analysis.layers) > _MAX_COLUMNS
        note = " Adjacent layers are averaged to fit the chart." if binned else ""
        for attribute, unit, title in (
            ("time_s", "s", "Time per layer (seconds)"),
            ("filament_mm", "mm", "Filament per layer (mm of filament)"),
        ):
            chart = _column_chart(_bin_layers(analysis.layers, attribute), unit, title)
            sections.append(
                f"<h2>{escape(title)}</h2><figure>{chart}"
                f"<figcaption>Hover a column for its value.{note}</figcaption></figure>"
            )
        rows = [
            [
                str(layer.index),
                f"{layer.z:.2f}" if layer.z is not None else "-",
                f"{layer.filament_mm:.2f}",
                f"{layer.extrude_path_mm:.1f}",
                f"{layer.travel_mm:.1f}",
                f"{layer.time_s:.1f}",
                str(layer.retractions),
            ]
            for layer in analysis.layers
        ]
        sections.append(
            "<details><summary>Per-layer table</summary>"
            + _table(
                ["Layer", "Z mm", "Filament mm", "Extrude mm", "Travel mm", "Time s", "Retracts"],
                rows,
            )
            + "</details>"
        )

    if analysis.tools:
        rows = [
            [
                f"T{tool.tool}",
                tool.material or "unknown",
                f"{tool.filament_mm:.1f}",
                f"{tool.volume_cm3:.3f}",
                f"{tool.mass_g:.2f}",
                f"{tool.density:g}",
            ]
            for tool in analysis.tools
        ]
        sections.append(
            "<h2>Filament by tool</h2>"
            + _table(["Tool", "Material", "Length mm", "Volume cm^3", "Mass g", "Density"], rows)
        )

    if cost is not None:
        rows = [
            ["Filament", f"{currency}{cost.filament:,.2f}"],
            ["Machine time", f"{currency}{cost.machine:,.2f}"],
            ["Electricity", f"{currency}{cost.electricity:,.2f}"],
            ["Failure allowance", f"{currency}{cost.failure_allowance:,.2f}"],
            ["Setup share", f"{currency}{cost.setup_share:,.2f}"],
            ["Unit cost", f"{currency}{cost.unit_cost:,.2f}"],
            ["Suggested unit price", f"{currency}{cost.unit_price:,.2f}"],
            [f"Batch cost ({cost.copies} copies)", f"{currency}{cost.batch_cost:,.2f}"],
            [f"Batch price ({cost.copies} copies)", f"{currency}{cost.batch_price:,.2f}"],
        ]
        sections.append("<h2>Cost</h2>" + _table(["Item", "Amount"], rows))

    warnings = "".join(f'<div class="warn">{escape(w)}</div>' for w in analysis.warnings)
    title = escape(analysis.source)
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title} - G-code report</title><style>{_CSS}</style></head><body><main>"
        f"<h1>{title}</h1>"
        f'<p class="sub">Slicer: {escape(slicer)} &middot; {analysis.line_count} lines</p>'
        f'{warnings}<div class="tiles">{"".join(tiles)}</div>{"".join(sections)}'
        "<footer>Time is a trapezoidal-motion estimate and excludes heating, homing, bed "
        "levelling and filament changes. "
        f"Generated by gcode-insight {escape(__version__)}.</footer>"
        "</main></body></html>\n"
    )
