"""Machine-state simulation: turns a command stream into print statistics.

The :class:`Analyzer` consumes :class:`~gcode_insight.parser.Command` objects
one at a time and keeps only running totals plus one small record per layer, so
memory use does not grow with file size (beyond the per-layer list).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from .materials import (
    DEFAULT_DENSITY,
    DEFAULT_FILAMENT_DIAMETER,
    density_for,
    filament_volume_mm3,
)
from .metadata import MetadataCollector, SlicerMetadata
from .parser import Command, iter_commands
from .reader import read_gcode_lines
from .timing import Block, Planner, Vector

__all__ = [
    "Analysis",
    "AnalysisOptions",
    "Analyzer",
    "BoundingBox",
    "LayerStats",
    "MachineProfile",
    "TimeComparison",
    "ToolUsage",
    "analyze_file",
    "analyze_lines",
]

_T = TypeVar("_T")

_EPS = 1e-9
_LAYER_Z_TOLERANCE = 1e-4
#: Tool numbers at or above this are treated as firmware-internal selectors
#: (Bambu printers use T255, T1000 and similar) rather than filament changes.
_MAX_TOOL_NUMBER = 100
_ARC_SAMPLE_STEP = math.radians(2.0)
_LAYER_MARKERS = frozenset({"LAYER_CHANGE", "CHANGE_LAYER"})


@dataclass(frozen=True, slots=True)
class MachineProfile:
    """Kinematic limits used by the time model.

    The defaults are generic values for a fast desktop printer; they are not a
    measured profile of any particular machine. Limits embedded in the file
    (``M201``, ``M203``, ``M204``) replace them while analysing unless
    :attr:`AnalysisOptions.honor_gcode_limits` is switched off.
    """

    #: Maximum speed per axis (X, Y, Z, E) in mm/s.
    max_feedrate: tuple[float, float, float, float] = (500.0, 500.0, 20.0, 80.0)
    #: Maximum acceleration per axis (X, Y, Z, E) in mm/s^2.
    max_accel: tuple[float, float, float, float] = (10000.0, 10000.0, 500.0, 5000.0)
    #: Acceleration for extruding moves in mm/s^2.
    print_accel: float = 3000.0
    #: Acceleration for non-extruding moves in mm/s^2.
    travel_accel: float = 3000.0
    #: Junction speed step in mm/s (see :mod:`gcode_insight.timing`).
    jerk: float = 8.0
    #: Speed assumed before the file sets its first feedrate, in mm/s.
    initial_feedrate: float = 50.0

    def __post_init__(self) -> None:
        values = (
            *self.max_feedrate,
            *self.max_accel,
            self.print_accel,
            self.travel_accel,
            self.jerk,
            self.initial_feedrate,
        )
        if any(value <= 0 for value in values):
            raise ValueError("all machine profile values must be positive")


@dataclass(frozen=True, slots=True)
class AnalysisOptions:
    """Knobs for :func:`analyze_file` / :func:`analyze_lines`."""

    #: Filament diameter in mm. ``None`` = slicer metadata, else 1.75.
    filament_diameter: float | None = None
    #: Density in g/cm^3 for every tool. Overrides ``material`` and metadata.
    density: float | None = None
    #: Material name looked up in the built-in table (PLA, PETG, ABS, ASA, TPU).
    material: str | None = None
    machine: MachineProfile = field(default_factory=MachineProfile)
    #: Apply M201/M203/M204/M220 found in the file to the time model.
    honor_gcode_limits: bool = True

    def __post_init__(self) -> None:
        if self.filament_diameter is not None and self.filament_diameter <= 0:
            raise ValueError("filament_diameter must be positive")
        if self.density is not None and self.density <= 0:
            raise ValueError("density must be positive")
        if self.material is not None and density_for(self.material) is None:
            raise ValueError(f"unknown material {self.material!r}; pass an explicit density")


@dataclass(slots=True)
class LayerStats:
    """Totals for one layer. ``index`` 0 is the start-up section before layer 1."""

    index: int
    z: float | None = None
    #: Net filament pushed through the nozzle during this layer, in mm of filament.
    filament_mm: float = 0.0
    #: Path length of extruding moves in mm.
    extrude_path_mm: float = 0.0
    #: Path length of non-extruding moves in mm.
    travel_mm: float = 0.0
    time_s: float = 0.0
    retractions: int = 0


@dataclass(slots=True)
class BoundingBox:
    """Axis-aligned extent of all extruding moves, in mm."""

    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

    @property
    def size(self) -> tuple[float, float, float]:
        return (self.max_x - self.min_x, self.max_y - self.min_y, self.max_z - self.min_z)


@dataclass(slots=True)
class ToolUsage:
    """Filament consumed by one tool / filament slot."""

    tool: int
    filament_mm: float
    volume_cm3: float
    mass_g: float
    material: str | None
    density: float
    diameter: float


@dataclass(slots=True)
class TimeComparison:
    """This model's estimate next to the slicer's own figure."""

    slicer_time_s: float
    #: Which slicer figure was used: "model printing time" or "total estimated time".
    basis: str
    estimate_s: float
    difference_s: float
    #: estimate / slicer; 1.0 means identical.
    ratio: float | None


@dataclass(slots=True)
class Analysis:
    """Everything :func:`analyze_file` learned about a G-code file."""

    source: str
    line_count: int
    metadata: SlicerMetadata
    #: "markers" when slicer layer-change comments were found, else "z".
    layer_mode: str
    layers: list[LayerStats]
    #: Everything before the first layer (start G-code, purge line in marker mode).
    startup: LayerStats
    filament_mm: float
    volume_cm3: float
    mass_g: float
    tools: list[ToolUsage]
    extrude_path_mm: float
    travel_mm: float
    retractions: int
    tool_changes: int
    bounding_box: BoundingBox | None
    #: Motion plus G4 dwell time from the trapezoidal model, in seconds.
    estimated_time_s: float
    dwell_time_s: float
    time_comparison: TimeComparison | None
    nozzle_temp_max: float | None
    bed_temp_max: float | None
    #: Highest commanded duty per fan index (M106 ``P``), in percent.
    fan_max_percent: dict[int, float]
    warnings: list[str]

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form suitable for ``json.dumps``."""
        data = asdict(self)
        data["layer_count"] = self.layer_count
        data["fan_max_percent"] = {str(k): v for k, v in self.fan_max_percent.items()}
        return data


class _LayerTracker:
    """Append-only list of layers; element 0 is the start-up bucket."""

    def __init__(self) -> None:
        self.items: list[LayerStats] = [LayerStats(index=0)]

    @property
    def current(self) -> LayerStats:
        return self.items[-1]

    def start(self, z: float | None = None) -> None:
        self.items.append(LayerStats(index=len(self.items), z=z))


@dataclass(slots=True)
class _Arc:
    centre_x: float
    centre_y: float
    radius: float
    start_angle: float
    sweep: float  # positive, radians
    sign: float  # +1 counter-clockwise, -1 clockwise

    @property
    def length(self) -> float:
        return self.radius * self.sweep

    def tangent(self, fraction: float) -> Vector:
        angle = self.start_angle + self.sign * self.sweep * fraction
        return (-math.sin(angle) * self.sign, math.cos(angle) * self.sign, 0.0)

    def points(self) -> Iterable[tuple[float, float]]:
        steps = max(1, math.ceil(self.sweep / _ARC_SAMPLE_STEP))
        for k in range(steps + 1):
            angle = self.start_angle + self.sign * self.sweep * k / steps
            yield (
                self.centre_x + self.radius * math.cos(angle),
                self.centre_y + self.radius * math.sin(angle),
            )


class Analyzer:
    """Incremental analyser. Call :meth:`feed` per command, then :meth:`finish`."""

    def __init__(self, options: AnalysisOptions | None = None) -> None:
        self.options = options or AnalysisOptions()
        machine = self.options.machine
        self._vmax = list(machine.max_feedrate)
        self._amax = list(machine.max_accel)
        self._print_accel = machine.print_accel
        self._travel_accel = machine.travel_accel
        self._feed = machine.initial_feedrate  # mm/s
        self._feed_factor = 1.0
        self._unit = 1.0  # mm per file unit (25.4 after G20)

        self._pos = [0.0, 0.0, 0.0]
        self._e = 0.0
        self._abs_xyz = True
        self._abs_e = True
        self._e_mode_explicit = False

        self._tool = 0
        # The extruder is modelled as one shared E axis (single nozzle fed by
        # several filaments). ``_e_net`` is the signed sum of all E movement and
        # ``_e_high_water`` the furthest it has ever been pushed; only pushes
        # beyond the high-water mark count as consumed filament, so a retract /
        # unretract pair adds nothing.
        self._e_net = 0.0
        self._e_high_water = 0.0
        self._tools: dict[int, float] = {}
        self._tool_changes = 0

        self._marker_layers = _LayerTracker()
        self._z_layers = _LayerTracker()
        self._marker_count = 0

        self._extrude_path = 0.0
        self._travel = 0.0
        self._retractions = 0
        self._bbox: list[float] | None = None
        self._motion_time = 0.0
        self._dwell_time = 0.0
        self._nozzle_max: float | None = None
        self._bed_max: float | None = None
        self._fans: dict[int, float] = {}
        self._line_count = 0
        self._warnings: list[str] = []
        self._meta = MetadataCollector()
        self._planner = Planner(machine.jerk, self._on_block_timed)

        self._handlers: dict[str, Callable[[Command], None]] = {
            "G0": self._linear,
            "G1": self._linear,
            "G2": lambda c: self._arc_move(c, clockwise=True),
            "G3": lambda c: self._arc_move(c, clockwise=False),
            "G4": self._dwell,
            "G10": self._firmware_retract,
            "G20": lambda c: self._set_unit(25.4),
            "G21": lambda c: self._set_unit(1.0),
            "G28": self._home,
            "G90": lambda c: self._set_positioning(absolute=True),
            "G91": lambda c: self._set_positioning(absolute=False),
            "G92": self._set_position,
            "M82": lambda c: self._set_e_mode(absolute=True),
            "M83": lambda c: self._set_e_mode(absolute=False),
            "M104": self._nozzle_temp,
            "M109": self._nozzle_temp,
            "M140": self._bed_temp,
            "M190": self._bed_temp,
            "M106": self._fan,
            "M201": self._max_accel,
            "M203": self._max_feedrate,
            "M204": self._accel,
            "M220": self._feed_percent,
        }

    # ------------------------------------------------------------------ feed

    def feed(self, command: Command) -> None:
        self._line_count = max(self._line_count, command.line_no)
        if command.comment is not None:
            self._meta.feed(command.comment)
            self._check_layer_marker(command.comment)
        code = command.code
        if not code:
            return
        handler = self._handlers.get(code)
        if handler is not None:
            handler(command)
        elif code[0] == "T" and code[1:].isdigit():
            self._select_tool(int(code[1:]))

    def _check_layer_marker(self, comment: str) -> None:
        is_marker = comment in _LAYER_MARKERS or (
            comment.startswith("LAYER:") and comment[6:].strip().lstrip("-").isdigit()
        )
        if not is_marker:
            return
        self._marker_count += 1
        current = self._marker_layers.current
        # Some slicers emit two different markers per layer; an empty layer is
        # therefore reused instead of opening another one.
        if current.index == 0 or current.extrude_path_mm > 0 or current.filament_mm > 0:
            self._marker_layers.start()

    # ------------------------------------------------------------- modal state

    def _set_unit(self, mm_per_unit: float) -> None:
        self._unit = mm_per_unit

    def _set_positioning(self, absolute: bool) -> None:
        self._abs_xyz = absolute
        # Marlin 2 behaviour: G90/G91 also switch E until M82/M83 pins it.
        if not self._e_mode_explicit:
            self._abs_e = absolute

    def _set_e_mode(self, absolute: bool) -> None:
        self._abs_e = absolute
        self._e_mode_explicit = True

    def _set_position(self, command: Command) -> None:
        for axis, letter in enumerate("XYZ"):
            if letter in command.params:
                self._pos[axis] = command.params[letter] * self._unit
        if "E" in command.params:
            self._e = command.params["E"] * self._unit

    def _home(self, command: Command) -> None:
        self._planner.flush()
        named = [letter for letter in "XYZ" if letter in command.params or letter in command.flags]
        for axis, letter in enumerate("XYZ"):
            if not named or letter in named:
                self._pos[axis] = 0.0

    def _select_tool(self, number: int) -> None:
        if number >= _MAX_TOOL_NUMBER or number == self._tool:
            return
        self._planner.flush()
        self._tool = number
        self._tool_changes += 1

    def _nozzle_temp(self, command: Command) -> None:
        if command.code == "M109":
            self._planner.flush()
        value = command.params.get("S", command.params.get("R"))
        if value is not None and (self._nozzle_max is None or value > self._nozzle_max):
            self._nozzle_max = value

    def _bed_temp(self, command: Command) -> None:
        if command.code == "M190":
            self._planner.flush()
        value = command.params.get("S", command.params.get("R"))
        if value is not None and (self._bed_max is None or value > self._bed_max):
            self._bed_max = value

    def _fan(self, command: Command) -> None:
        index = int(command.params.get("P", 0))
        duty = min(max(command.params.get("S", 255.0), 0.0), 255.0) / 255.0 * 100.0
        self._fans[index] = max(self._fans.get(index, 0.0), duty)

    def _max_accel(self, command: Command) -> None:
        self._set_axis_limits(command, self._amax)

    def _max_feedrate(self, command: Command) -> None:
        self._set_axis_limits(command, self._vmax)

    def _set_axis_limits(self, command: Command, limits: list[float]) -> None:
        if not self.options.honor_gcode_limits:
            return
        for axis, letter in enumerate("XYZE"):
            value = command.params.get(letter)
            if value is not None and value > 0:
                limits[axis] = value

    def _accel(self, command: Command) -> None:
        if not self.options.honor_gcode_limits:
            return
        params = command.params
        if params.get("S", 0.0) > 0:
            self._print_accel = self._travel_accel = params["S"]
        if params.get("P", 0.0) > 0:
            self._print_accel = params["P"]
        if params.get("T", 0.0) > 0:
            self._travel_accel = params["T"]

    def _feed_percent(self, command: Command) -> None:
        if self.options.honor_gcode_limits and command.params.get("S", 0.0) > 0:
            self._feed_factor = command.params["S"] / 100.0

    def _dwell(self, command: Command) -> None:
        self._planner.flush()
        seconds = command.params.get("S")
        if seconds is None:
            seconds = command.params.get("P", 0.0) / 1000.0
        seconds = max(seconds, 0.0)
        self._dwell_time += seconds
        self._marker_layers.current.time_s += seconds
        self._z_layers.current.time_s += seconds

    def _firmware_retract(self, command: Command) -> None:
        # A bare G10 is a firmware retraction; with parameters it sets offsets.
        if command.params or command.flags:
            return
        self._retractions += 1
        self._marker_layers.current.retractions += 1
        self._z_layers.current.retractions += 1

    # ----------------------------------------------------------------- motion

    def _read_targets(self, command: Command) -> tuple[list[float], float]:
        params = command.params
        if "F" in params and params["F"] > 0:
            self._feed = params["F"] * self._unit / 60.0
        target = list(self._pos)
        for axis, letter in enumerate("XYZ"):
            if letter in params:
                value = params[letter] * self._unit
                target[axis] = value if self._abs_xyz else target[axis] + value
        delta_e = 0.0
        if "E" in params:
            value = params["E"] * self._unit
            if self._abs_e:
                delta_e = value - self._e
                self._e = value
            else:
                delta_e = value
                self._e += value
        return target, delta_e

    def _linear(self, command: Command) -> None:
        target, delta_e = self._read_targets(command)
        self._move(target, delta_e, None)

    def _arc_move(self, command: Command, clockwise: bool) -> None:
        target, delta_e = self._read_targets(command)
        self._move(target, delta_e, self._build_arc(command, target, clockwise))

    def _build_arc(self, command: Command, target: list[float], clockwise: bool) -> _Arc | None:
        params = command.params
        x0, y0 = self._pos[0], self._pos[1]
        x1, y1 = target[0], target[1]
        if "R" in params:
            radius = params["R"] * self._unit
            chord = math.hypot(x1 - x0, y1 - y0)
            if chord < _EPS or abs(radius) < chord / 2.0:
                return None
            height = math.sqrt(radius * radius - (chord / 2.0) ** 2)
            side = -1.0 if clockwise != (radius < 0) else 1.0
            centre_x = (x0 + x1) / 2.0 - side * height * (y1 - y0) / chord
            centre_y = (y0 + y1) / 2.0 + side * height * (x1 - x0) / chord
            radius = abs(radius)
        else:
            offset_i = params.get("I", 0.0) * self._unit
            offset_j = params.get("J", 0.0) * self._unit
            radius = math.hypot(offset_i, offset_j)
            if radius < _EPS:
                return None
            centre_x, centre_y = x0 + offset_i, y0 + offset_j
        start = math.atan2(y0 - centre_y, x0 - centre_x)
        end = math.atan2(y1 - centre_y, x1 - centre_x)
        sweep = (start - end) if clockwise else (end - start)
        sweep %= 2.0 * math.pi
        if sweep < 1e-9:
            sweep = 2.0 * math.pi  # same start and end point: full circle
        return _Arc(centre_x, centre_y, radius, start, sweep, -1.0 if clockwise else 1.0)

    def _move(self, target: list[float], delta_e: float, arc: _Arc | None) -> None:
        dx = target[0] - self._pos[0]
        dy = target[1] - self._pos[1]
        dz = target[2] - self._pos[2]
        xy_length = arc.length if arc is not None else math.hypot(dx, dy)
        distance = math.hypot(xy_length, dz)
        extruding = delta_e > 0 and xy_length > _EPS

        if extruding:
            z_layer = self._z_layers.current
            if z_layer.index == 0 or (
                z_layer.z is not None and abs(target[2] - z_layer.z) > _LAYER_Z_TOLERANCE
            ):
                self._z_layers.start(target[2])
            marker_layer = self._marker_layers.current
            if marker_layer.index > 0 and marker_layer.z is None:
                marker_layer.z = target[2]
        layers = (self._marker_layers.current, self._z_layers.current)

        if abs(delta_e) > 0:
            if delta_e < 0 and self._e_net >= self._e_high_water - _EPS:
                self._retractions += 1
                for layer in layers:
                    layer.retractions += 1
            self._e_net += delta_e
            if self._e_net > self._e_high_water:
                gained = self._e_net - self._e_high_water
                self._e_high_water = self._e_net
                self._tools[self._tool] = self._tools.get(self._tool, 0.0) + gained
                for layer in layers:
                    layer.filament_mm += gained

        if extruding:
            self._extrude_path += distance
            for layer in layers:
                layer.extrude_path_mm += distance
            self._grow_bbox(self._pos[0], self._pos[1], self._pos[2])
            self._grow_bbox(target[0], target[1], target[2])
            if arc is not None:
                for x, y in arc.points():
                    self._grow_bbox(x, y, target[2])
        elif distance > _EPS:
            self._travel += distance
            for layer in layers:
                layer.travel_mm += distance

        self._queue_block(dx, dy, dz, delta_e, xy_length, distance, extruding, arc)
        self._pos = target

    def _grow_bbox(self, x: float, y: float, z: float) -> None:
        box = self._bbox
        if box is None:
            self._bbox = [x, x, y, y, z, z]
            return
        box[0], box[1] = min(box[0], x), max(box[1], x)
        box[2], box[3] = min(box[2], y), max(box[3], y)
        box[4], box[5] = min(box[4], z), max(box[5], z)

    def _queue_block(
        self,
        dx: float,
        dy: float,
        dz: float,
        delta_e: float,
        xy_length: float,
        distance: float,
        extruding: bool,
        arc: _Arc | None,
    ) -> None:
        direction_in: Vector | None
        direction_out: Vector | None
        if distance > _EPS:
            length = distance
            if arc is not None:
                share = xy_length / distance
                components = (share, share, abs(dz) / distance, abs(delta_e) / distance)
                direction_in, direction_out = arc.tangent(0.0), arc.tangent(1.0)
            else:
                components = (
                    abs(dx) / distance,
                    abs(dy) / distance,
                    abs(dz) / distance,
                    abs(delta_e) / distance,
                )
                direction_in = direction_out = (dx / distance, dy / distance, dz / distance)
            accel = self._print_accel if extruding else self._travel_accel
        elif abs(delta_e) > _EPS:
            length = abs(delta_e)
            components = (0.0, 0.0, 0.0, 1.0)
            direction_in = direction_out = None
            accel = math.inf
        else:
            return

        nominal = self._feed * self._feed_factor
        for share, v_limit, a_limit in zip(components, self._vmax, self._amax, strict=True):
            if share > 1e-9:
                nominal = min(nominal, v_limit / share)
                accel = min(accel, a_limit / share)
        if arc is not None:
            # Centripetal acceleration v^2 / r may not exceed the move's acceleration.
            nominal = min(nominal, math.sqrt(accel * arc.radius))
        self._planner.add(
            Block(
                distance=length,
                nominal=nominal,
                accel=accel,
                direction_in=direction_in,
                direction_out=direction_out,
                tag=(self._marker_layers.current.index, self._z_layers.current.index),
            )
        )

    def _on_block_timed(self, block: Block, seconds: float) -> None:
        self._motion_time += seconds
        self._marker_layers.items[block.tag[0]].time_s += seconds
        self._z_layers.items[block.tag[1]].time_s += seconds

    # ----------------------------------------------------------------- finish

    def finish(self, source: str = "<input>") -> Analysis:
        """Flush pending moves and build the :class:`Analysis`."""
        self._planner.flush()
        meta = self._meta.metadata
        warnings = list(self._warnings)
        tracker = self._marker_layers if self._marker_count > 0 else self._z_layers
        layer_mode = "markers" if self._marker_count > 0 else "z"

        tools: list[ToolUsage] = []
        default_density_used = False
        for number in sorted(self._tools):
            length = self._tools[number]
            if length <= 0:
                continue
            material, density, is_default = self._material_for(number, meta)
            default_density_used = default_density_used or is_default
            diameter = self._diameter_for(number, meta)
            volume_mm3 = filament_volume_mm3(length, diameter)
            tools.append(
                ToolUsage(
                    tool=number,
                    filament_mm=length,
                    volume_cm3=volume_mm3 / 1000.0,
                    mass_g=volume_mm3 / 1000.0 * density,
                    material=material,
                    density=density,
                    diameter=diameter,
                )
            )
        if not tools:
            warnings.append("no extrusion found; filament, mass and bounding box are empty")
        elif default_density_used:
            warnings.append(
                f"material unknown; mass assumes PLA density {DEFAULT_DENSITY} g/cm^3 "
                "(use --material or --density)"
            )

        estimate = self._motion_time + self._dwell_time
        comparison: TimeComparison | None = None
        reference, basis = meta.model_time_s, "model printing time"
        if reference is None:
            reference, basis = meta.estimated_time_s, "total estimated time"
        if reference is not None:
            comparison = TimeComparison(
                slicer_time_s=reference,
                basis=basis,
                estimate_s=estimate,
                difference_s=estimate - reference,
                ratio=estimate / reference if reference > 0 else None,
            )

        box = self._bbox
        return Analysis(
            source=source,
            line_count=self._line_count,
            metadata=meta,
            layer_mode=layer_mode,
            layers=tracker.items[1:],
            startup=tracker.items[0],
            filament_mm=sum(tool.filament_mm for tool in tools),
            volume_cm3=sum(tool.volume_cm3 for tool in tools),
            mass_g=sum(tool.mass_g for tool in tools),
            tools=tools,
            extrude_path_mm=self._extrude_path,
            travel_mm=self._travel,
            retractions=self._retractions,
            tool_changes=self._tool_changes,
            bounding_box=BoundingBox(*box) if box is not None else None,
            estimated_time_s=estimate,
            dwell_time_s=self._dwell_time,
            time_comparison=comparison,
            nozzle_temp_max=self._nozzle_max,
            bed_temp_max=self._bed_max,
            fan_max_percent=dict(sorted(self._fans.items())),
            warnings=warnings,
        )

    def _material_for(self, tool: int, meta: SlicerMetadata) -> tuple[str | None, float, bool]:
        """Return (material name, density, density-is-the-fallback-default)."""
        options = self.options
        name = options.material or _pick(meta.filament_type, tool)
        if options.density is not None:
            return name, options.density, False
        if options.material is not None:
            density = density_for(options.material)
            assert density is not None  # validated in AnalysisOptions
            return name, density, False
        meta_density = _pick(meta.filament_density, tool)
        if meta_density is not None and meta_density > 0:
            return name, meta_density, False
        if name is not None:
            table_density = density_for(name)
            if table_density is not None:
                return name, table_density, False
        return name, DEFAULT_DENSITY, True

    def _diameter_for(self, tool: int, meta: SlicerMetadata) -> float:
        if self.options.filament_diameter is not None:
            return self.options.filament_diameter
        diameter = _pick(meta.filament_diameter, tool)
        if diameter is not None and diameter > 0:
            return diameter
        return DEFAULT_FILAMENT_DIAMETER


def _pick(values: list[_T], index: int) -> _T | None:
    """Per-tool lookup: a single-entry list applies to every tool."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return values[index] if 0 <= index < len(values) else None


def analyze_lines(
    lines: Iterable[str],
    options: AnalysisOptions | None = None,
    source: str = "<input>",
) -> Analysis:
    """Analyse G-code supplied as an iterable of text lines."""
    analyzer = Analyzer(options)
    for command in iter_commands(lines):
        analyzer.feed(command)
    return analyzer.finish(source)


def analyze_file(
    path: str | Path,
    options: AnalysisOptions | None = None,
    plate: int | None = None,
) -> Analysis:
    """Analyse a ``.gcode`` file, or one plate of a Bambu ``.gcode.3mf`` archive."""
    path = Path(path)
    return analyze_lines(read_gcode_lines(path, plate), options, source=path.name)
