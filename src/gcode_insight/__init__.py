"""gcode-insight: analyse FDM G-code files without a printer."""

from __future__ import annotations

__version__ = "0.3.0"

from .analysis import (
    SCHEMA_VERSION,
    Analysis,
    AnalysisOptions,
    Analyzer,
    BoundingBox,
    LayerStats,
    MachineProfile,
    TimeComparison,
    ToolChange,
    ToolUsage,
    analyze_file,
    analyze_lines,
)
from .cost import CostBreakdown, CostInputs, compute_cost
from .html_report import render_html
from .materials import MATERIAL_DENSITIES, density_for, filament_mass_g, filament_volume_mm3
from .metadata import SlicerMetadata, parse_duration
from .parser import Command, iter_commands, parse_line
from .report import format_analysis, format_compare, format_cost, format_duration
from .timing import Block, Planner, junction_speed, trapezoid_time

__all__ = [
    "MATERIAL_DENSITIES",
    "SCHEMA_VERSION",
    "Analysis",
    "AnalysisOptions",
    "Analyzer",
    "Block",
    "BoundingBox",
    "Command",
    "CostBreakdown",
    "CostInputs",
    "LayerStats",
    "MachineProfile",
    "Planner",
    "SlicerMetadata",
    "TimeComparison",
    "ToolChange",
    "ToolUsage",
    "__version__",
    "analyze_file",
    "analyze_lines",
    "compute_cost",
    "density_for",
    "filament_mass_g",
    "filament_volume_mm3",
    "format_analysis",
    "format_compare",
    "format_cost",
    "format_duration",
    "iter_commands",
    "junction_speed",
    "parse_duration",
    "parse_line",
    "render_html",
    "trapezoid_time",
]
