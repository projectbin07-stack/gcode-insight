# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-18

First release.

### Added

- Streaming G-code parser: `G0/G1`, `G2/G3` arcs (`I/J` and `R`), `G4`, `G20/G21`, `G28`,
  `G90/G91`, `G92`, `M82/M83`, tool changes, `M104/M109/M140/M190`, `M106/M107`.
- Slicer metadata extraction for Bambu Studio, OrcaSlicer, PrusaSlicer/SuperSlicer and Cura comment
  styles.
- Layer detection from slicer markers or Z changes; per-layer filament, extrusion path, travel path
  and time; bounding box; retraction count; per-tool filament usage.
- Filament length to volume and mass with a built-in density table (PLA, PETG, ABS, ASA, TPU).
- Trapezoidal time model with per-axis limits, look-ahead and a simple junction rule; honours
  `M201/M203/M204/M220`; comparison with the slicer's estimate.
- Cost model with filament, machine rate, electricity, failure allowance, markup, setup cost and
  batch totals.
- CLI commands `analyze`, `cost` and `compare`; text, JSON and self-contained HTML output.
- Reading of Bambu/Orca `.gcode.3mf` archives.

### Known gaps

- Not yet validated against real slicer output, measured print times or weighed parts; see the
  README section "Known limitations".

[0.1.0]: https://github.com/projectbin07-stack/gcode-insight/releases/tag/v0.1.0
