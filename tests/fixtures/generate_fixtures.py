"""Generate the G-code fixtures used by the test-suite.

Run ``python tests/fixtures/generate_fixtures.py`` to rewrite the ``.gcode``
files and ``expected.json`` next to this script. The output is deterministic and
committed; ``tests/test_fixtures.py`` fails if the committed files drift from
what this script produces.

The fixtures are *synthetic*. They were written for this project to imitate the
comment and command conventions of each slicer; they are not slicer output and
contain no third-party content. In particular the "estimated printing time"
values in the headers/footers are made-up placeholders, not real slicer
estimates.

``expected.json`` holds ground truth computed here with independent
bookkeeping (summing the E values and path lengths as they are written), so the
analyser is checked against numbers it did not produce itself.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
FILAMENT_AREA = math.pi * (1.75 / 2.0) ** 2
RETRACT = 0.8


@dataclass
class Truth:
    """Independent bookkeeping of what was written."""

    filament_by_tool: dict[int, float] = field(default_factory=dict)
    extrude_path_mm: float = 0.0
    retractions: int = 0
    layers: int = 0
    layer_filament: list[float] = field(default_factory=list)
    min_x: float = math.inf
    max_x: float = -math.inf
    min_y: float = math.inf
    max_y: float = -math.inf
    min_z: float = math.inf
    max_z: float = -math.inf

    def as_dict(self) -> dict[str, object]:
        return {
            "filament_mm": round(sum(self.filament_by_tool.values()), 5),
            "filament_by_tool": {str(k): round(v, 5) for k, v in self.filament_by_tool.items()},
            "extrude_path_mm": round(self.extrude_path_mm, 4),
            "retractions": self.retractions,
            "layers": self.layers,
            "layer_filament": [round(v, 5) for v in self.layer_filament],
            "bbox": [
                round(v, 3)
                for v in (self.min_x, self.max_x, self.min_y, self.max_y, self.min_z, self.max_z)
            ],
        }


class Writer:
    """Tiny G-code emitter that tracks position and ground truth."""

    def __init__(self, width: float, height: float, absolute_e: bool) -> None:
        self.lines: list[str] = []
        self.truth = Truth()
        self.e_per_mm = width * height / FILAMENT_AREA
        self.absolute_e = absolute_e
        self.x = self.y = self.z = 0.0
        self.e = 0.0  # logical E axis value (absolute mode)
        self.tool = 0
        self.in_layer = False
        self.retracted = False

    def raw(self, *lines: str) -> None:
        self.lines.extend(lines)

    def _e_word(self, delta: float) -> tuple[str, float]:
        if self.absolute_e:
            target = round(self.e + delta, 5)
            actual = target - self.e
            self.e = target
            return f"E{target:.5f}", actual
        actual = round(delta, 5)
        return f"E{actual:.5f}", actual

    def reset_e(self) -> None:
        self.e = 0.0
        self.raw("G92 E0")

    def _count(self, amount: float) -> None:
        truth = self.truth
        truth.filament_by_tool[self.tool] = truth.filament_by_tool.get(self.tool, 0.0) + amount
        if self.in_layer:
            truth.layer_filament[-1] += amount

    def _extent(self, x: float, y: float) -> None:
        truth = self.truth
        truth.min_x, truth.max_x = min(truth.min_x, x), max(truth.max_x, x)
        truth.min_y, truth.max_y = min(truth.min_y, y), max(truth.max_y, y)
        truth.min_z, truth.max_z = min(truth.min_z, self.z), max(truth.max_z, self.z)

    def begin_layer(self) -> None:
        self.in_layer = True
        self.truth.layers += 1
        self.truth.layer_filament.append(0.0)

    def move_z(self, z: float, feed: int = 600) -> None:
        self.z = round(z, 3)
        self.raw(f"G1 Z{self.z:.3f} F{feed}")

    def travel(self, x: float, y: float, feed: int = 9000) -> None:
        self.x, self.y = round(x, 3), round(y, 3)
        self.raw(f"G1 X{self.x:.3f} Y{self.y:.3f} F{feed}")

    def line(self, x: float, y: float, feed: int | None = None) -> None:
        x, y = round(x, 3), round(y, 3)
        length = math.hypot(x - self.x, y - self.y)
        word, amount = self._e_word(length * self.e_per_mm)
        self._extent(self.x, self.y)
        self._extent(x, y)
        self.x, self.y = x, y
        self.truth.extrude_path_mm += length
        self._count(amount)
        suffix = f" F{feed}" if feed is not None else ""
        self.raw(f"G1 X{x:.3f} Y{y:.3f} {word}{suffix}")

    def arc_ccw(self, x: float, y: float, i: float, j: float) -> None:
        """Quarter-circle corner, counter-clockwise, centre at (x0 + i, y0 + j)."""
        x, y = round(x, 3), round(y, 3)
        radius = math.hypot(i, j)
        length = radius * math.pi / 2.0
        word, amount = self._e_word(length * self.e_per_mm)
        self._extent(self.x, self.y)
        self._extent(x, y)
        self.x, self.y = x, y
        self.truth.extrude_path_mm += length
        self._count(amount)
        self.raw(f"G3 X{x:.3f} Y{y:.3f} I{i:.3f} J{j:.3f} {word}")

    def retract(self, feed: int = 1800) -> None:
        if self.retracted:
            return
        self.retracted = True
        word, _ = self._e_word(-RETRACT)
        self.truth.retractions += 1
        self.raw(f"G1 {word} F{feed}")

    def unretract(self, feed: int = 1800) -> None:
        if not self.retracted:
            return
        self.retracted = False
        word, _ = self._e_word(RETRACT)
        self.raw(f"G1 {word} F{feed}")

    def prime(self, amount: float, feed: int = 300) -> None:
        word, actual = self._e_word(amount)
        self._count(actual)
        self.raw(f"G1 {word} F{feed}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def square_loop(w: Writer, cx: float, cy: float, half: float, feed: int) -> None:
    w.travel(cx - half, cy - half)
    w.unretract()
    w.line(cx + half, cy - half, feed)
    w.line(cx + half, cy + half)
    w.line(cx - half, cy + half)
    w.line(cx - half, cy - half)
    w.retract()


def rounded_loop(w: Writer, cx: float, cy: float, half: float, r: float, feed: int) -> None:
    w.travel(cx - half + r, cy - half)
    w.unretract()
    w.line(cx + half - r, cy - half, feed)
    w.arc_ccw(cx + half, cy - half + r, 0.0, r)
    w.line(cx + half, cy + half - r)
    w.arc_ccw(cx + half - r, cy + half, -r, 0.0)
    w.line(cx - half + r, cy + half)
    w.arc_ccw(cx - half, cy + half - r, 0.0, -r)
    w.line(cx - half, cy - half + r)
    w.arc_ccw(cx - half + r, cy - half, r, 0.0)
    w.retract()


def infill(w: Writer, cx: float, cy: float, half: float, layer: int, feed: int) -> None:
    """Zig-zag lines 2 mm apart; direction alternates with the layer."""
    offsets = [-half + 2.0 * k for k in range(int(half) + 1)]
    first = True
    for n, offset in enumerate(offsets):
        low, high = (-half, half) if n % 2 == 0 else (half, -half)
        if layer % 2 == 0:
            start, end = (cx + offset, cy + low), (cx + offset, cy + high)
        else:
            start, end = (cx + low, cy + offset), (cx + high, cy + offset)
        if first:
            w.travel(*start)
            w.unretract()
            w.line(*end, feed)
            first = False
        else:
            w.line(*start)
            w.line(*end)
    w.retract()


def bambu() -> tuple[str, Truth]:
    """Bambu Studio style: header/config blocks, CHANGE_LAYER, arcs, two filaments."""
    layers, height, width = 5, 0.2, 0.42
    cx = cy = 128.0
    w = Writer(width, height, absolute_e=False)
    w.raw(
        "M73 P0 R8",
        "M201 X20000 Y20000 Z500 E5000",
        "M203 X500 Y500 Z20 E30",
        "M204 S10000",
        "M140 S55",
        "M104 S140",
        "G28",
        "M190 S55",
        "M109 S220",
        "M1002 gcode_claim_action : 2",
        "G90",
        "M83",
        "T1000",
        "; nozzle load line",
        "G1 Z0.3 F1200",
        "G1 X18 Y1 F18000",
    )
    w.x, w.y, w.z = 18.0, 1.0, 0.3
    purge = Writer(0.5, 0.3, absolute_e=False).e_per_mm * 4.0  # deliberately heavy bead
    w.e_per_mm, normal = purge, w.e_per_mm
    w.line(78.0, 1.0, 1800)
    w.e_per_mm = normal
    w.retract()
    for layer in range(layers):
        z = height * (layer + 1)
        if layer == 3:
            w.raw("; filament end gcode", "M620 S1A", "M204 S9000", "G1 Z3.6 F1200", "T1")
            w.tool = 1
            w.raw("M621 S1A", "M109 S245")
            w.raw("; FLUSH_START")
            w.unretract()
            w.prime(4.0)
            w.retract()
            w.raw("; FLUSH_END")
        w.raw(
            "; CHANGE_LAYER",
            f"; Z_HEIGHT: {z:g}",
            f"; LAYER_HEIGHT: {height:g}",
            f"; layer num/total_layer_count: {layer + 1}/{layers}",
            f"M73 L{layer + 1}",
        )
        w.begin_layer()
        w.move_z(z + 0.4)
        if layer == 1:
            w.raw("M106 P1 S255", "M106 P2 S178")
        w.raw("; FEATURE: Inner wall", f"; LINE_WIDTH: {width + 0.03:g}", "M204 S6000")
        w.travel(cx - 9.0, cy - 9.0, 30000)
        w.move_z(z)
        rounded_loop(w, cx, cy, 9.37, 1.5, 9000 if layer else 3000)
        w.raw("; FEATURE: Outer wall", f"; LINE_WIDTH: {width:g}", "M204 S5000")
        rounded_loop(w, cx, cy, 9.79, 2.0, 6000 if layer else 3000)
        w.raw("; FEATURE: Sparse infill", "M204 S10000")
        infill(w, cx, cy, 8.0, layer, 12000 if layer else 3000)
    w.raw("M106 P1 S0", "M106 P2 S0", "G1 Z5 F900", "M104 S0", "M140 S0", "M73 P100 R0")

    truth = w.truth
    lengths = [truth.filament_by_tool[t] for t in sorted(truth.filament_by_tool)]
    densities = [1.24, 1.27]
    volumes = [length * FILAMENT_AREA / 1000.0 for length in lengths]
    header = [
        "; HEADER_BLOCK_START",
        "; BambuStudio 01.10.01.50",
        "; model printing time: 27s; total estimated time: 6m 33s",
        f"; total layer number: {layers}",
        "; total filament length [mm] : " + ",".join(f"{v:.2f}" for v in lengths),
        "; total filament volume [cm^3] : " + ",".join(f"{v:.2f}" for v in volumes),
        "; total filament weight [g] : "
        + ",".join(f"{v * d:.2f}" for v, d in zip(volumes, densities, strict=True)),
        "; filament_density: 1.24,1.27",
        "; filament_diameter: 1.75,1.75",
        f"; max_z_height: {layers * height:.2f}",
        "; HEADER_BLOCK_END",
        "",
        "; CONFIG_BLOCK_START",
        "; curr_bed_type = Textured PEI Plate",
        "; filament_colour = #FFFFFF;#161616",
        "; filament_type = PLA;PETG",
        "; initial_layer_print_height = 0.2",
        "; layer_height = 0.2",
        "; nozzle_diameter = 0.4",
        "; printer_model = Bambu Lab P1S",
        "; CONFIG_BLOCK_END",
        "",
    ]
    return "\n".join(header) + "\n" + w.text(), truth


def orca() -> tuple[str, Truth]:
    """OrcaSlicer style with Klipper-flavoured commands and a footer."""
    layers, height, width = 5, 0.2, 0.45
    cx = cy = 110.0
    w = Writer(width, height, absolute_e=False)
    w.raw(
        "; HEADER_BLOCK_START",
        "; generated by OrcaSlicer 2.1.1 on 2024-08-20 at 18:04:11",
        f"; total layer number: {layers}",
        "; filament_density: 1.04",
        "; filament_diameter: 1.75",
        f"; max_z_height: {layers * height:.2f}",
        "; HEADER_BLOCK_END",
        "",
        "M73 P0 R2",
        "M190 S100",
        "M109 S260",
        "PRINT_START EXTRUDER=260 BED=100",
        "G90",
        "G21",
        "M83 ; use relative distances for extrusion",
        "EXCLUDE_OBJECT_DEFINE NAME=cube_id_0_copy_0 CENTER=110,110",
        "M106 S0",
    )
    for layer in range(layers):
        z = height * (layer + 1)
        w.raw(";LAYER_CHANGE", f";Z:{z:g}", f";HEIGHT:{height:g}", ";BEFORE_LAYER_CHANGE")
        w.begin_layer()
        w.raw(
            f"SET_VELOCITY_LIMIT ACCEL={5000 if layer else 500}", f"M204 S{5000 if layer else 500}"
        )
        w.move_z(z + 0.2)
        if layer == 1:
            w.raw("M106 S127.5")
        w.raw("EXCLUDE_OBJECT_START NAME=cube_id_0_copy_0", ";TYPE:Inner wall", ";WIDTH:0.45")
        w.travel(cx - 9.325, cy - 9.325, 18000)
        w.move_z(z)
        square_loop(w, cx, cy, 9.325, 7200 if layer else 1800)
        w.raw(";TYPE:Outer wall", ";WIDTH:0.45")
        square_loop(w, cx, cy, 9.775, 3600 if layer else 1800)
        w.raw(";TYPE:Sparse infill", ";WIDTH:0.45")
        infill(w, cx, cy, 8.0, layer, 9000 if layer else 1800)
        w.raw("EXCLUDE_OBJECT_END NAME=cube_id_0_copy_0")
    w.raw("M106 S0", "PRINT_END", "M73 P100 R0")
    length = w.truth.filament_by_tool[0]
    volume = length * FILAMENT_AREA / 1000.0
    w.raw(
        f"; filament used [mm] = {length:.2f}",
        f"; filament used [cm3] = {volume:.2f}",
        f"; filament used [g] = {volume * 1.04:.2f}",
        "; filament cost = 0.01",
        f"; total filament used [g] = {volume * 1.04:.2f}",
        "; total filament cost = 0.01",
        f"; total layers count = {layers}",
        "; estimated printing time (normal mode) = 35s",
        "",
        "; CONFIG_BLOCK_START",
        "; filament_type = ABS",
        "; initial_layer_print_height = 0.2",
        "; layer_height = 0.2",
        "; nozzle_diameter = 0.4",
        "; printer_model = Voron 2.4 350",
        "; CONFIG_BLOCK_END",
    )
    return w.text(), w.truth


def prusa() -> tuple[str, Truth]:
    """PrusaSlicer style: absolute E reset per layer, settings footer."""
    layers, height, width = 6, 0.2, 0.45
    cx, cy = 125.0, 105.0
    w = Writer(width, height, absolute_e=True)
    w.raw(
        "; generated by PrusaSlicer 2.7.4+win64 on 2024-05-02 at 09:15:27 UTC",
        "",
        "; external perimeters extrusion width = 0.45mm",
        "; perimeters extrusion width = 0.45mm",
        "; infill extrusion width = 0.45mm",
        "",
        "M201 X2500 Y2500 Z400 E5000 ; sets maximum accelerations, mm/sec^2",
        "M203 X180 Y180 Z12 E80 ; sets maximum feedrates, mm / sec",
        "M204 P2000 R1250 T2500 ; sets acceleration (P, T) and retract acceleration (R), mm/sec^2",
        "M107",
        "M104 S170 ; set extruder temp for bed leveling",
        "M140 S85 ; set bed temp",
        "M190 S85 ; wait for bed temp",
        "G28 ; home all",
        "M104 S240 ; set extruder temp",
        "M109 S240 ; wait for extruder temp",
        "G90 ; use absolute coordinates",
        "M82 ; use absolute distances for extrusion",
        "G92 E0",
    )
    for layer in range(layers):
        z = height * (layer + 1)
        w.raw(";LAYER_CHANGE", f";Z:{z:g}", f";HEIGHT:{height:g}", ";BEFORE_LAYER_CHANGE")
        w.reset_e()
        w.begin_layer()
        w.move_z(z + 0.2, 720)
        w.raw(";AFTER_LAYER_CHANGE")
        if layer == 1:
            w.raw("M106 S76.5")
        w.raw(";TYPE:Perimeter", ";WIDTH:0.45")
        w.travel(cx - 9.325, cy - 9.325, 10800)
        w.move_z(z, 720)
        square_loop(w, cx, cy, 9.325, 2700 if layer else 1200)
        w.raw(";TYPE:External perimeter")
        square_loop(w, cx, cy, 9.775, 1500 if layer else 1200)
        w.raw(";TYPE:Infill")
        infill(w, cx, cy, 8.0, layer, 4800 if layer else 1200)
    w.raw("M107", "G1 Z10 F720 ; Move print head up", "M104 S0", "M140 S0", "M84 ; disable motors")
    length = w.truth.filament_by_tool[0]
    volume = length * FILAMENT_AREA / 1000.0
    w.raw(
        f"; filament used [mm] = {length:.2f}",
        f"; filament used [cm3] = {volume:.2f}",
        f"; filament used [g] = {volume * 1.27:.2f}",
        "; filament cost = 0.02",
        f"; total filament used [g] = {volume * 1.27:.2f}",
        "; total filament cost = 0.02",
        "; estimated printing time (normal mode) = 1m 4s",
        "; estimated printing time (silent mode) = 1m 6s",
        "",
        "; prusaslicer_config = begin",
        "; filament_density = 1.27",
        "; filament_colour = #FF8000",
        "; filament_diameter = 1.75",
        "; filament_type = PETG",
        "; first_layer_height = 0.2",
        "; layer_height = 0.2",
        "; nozzle_diameter = 0.4",
        "; printer_model = MK4S",
        "; prusaslicer_config = end",
    )
    return w.text(), w.truth


def marlin() -> tuple[str, Truth]:
    """Plain Marlin G-code: no slicer comments, layers only visible as Z changes."""
    layers, height, width = 4, 0.25, 0.5
    cx = cy = 60.0
    w = Writer(width, height, absolute_e=True)
    w.raw(
        "M140 S60",
        "M104 S205",
        "G28",
        "M190 S60",
        "M109 S205",
        "G21",
        "G90",
        "G92 E0",
        "M106 S128",
    )
    for layer in range(layers):
        w.begin_layer()
        w.move_z(height * (layer + 1), 300)
        square_loop(w, cx, cy, 14.75, 1500)
        square_loop(w, cx, cy, 14.25, 2400)
        if layer < layers - 1:
            w.raw("G4 P500")
    w.raw(
        "G91",
        "G1 Z5 E-2 F600",
        "G90",
        "G28 X Y",
        "M104 S0",
        "M140 S0",
        "M107",
        "M84",
    )
    return w.text(), w.truth


FIXTURES = {
    "bambu_cube.gcode": bambu,
    "orca_cube.gcode": orca,
    "prusa_cube.gcode": prusa,
    "marlin_generic.gcode": marlin,
}


def build() -> dict[str, str]:
    """Return {file name: content} for every generated file, including expected.json."""
    files: dict[str, str] = {}
    expected: dict[str, object] = {}
    for name, factory in FIXTURES.items():
        text, truth = factory()
        files[name] = text
        expected[name] = truth.as_dict()
    files["expected.json"] = json.dumps(expected, indent=2) + "\n"
    return files


if __name__ == "__main__":
    for file_name, content in build().items():
        (HERE / file_name).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {file_name}")
