# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-11-25

### Added

- A shared printer and material registry (`print_registry.json` and `registry.py`). It lists the
  Bambu Lab P1S, P1P, X1 Carbon, A1 and A1 mini with build volume, enclosure, nozzle options,
  build plates and AMS capacity. Each printer has manufacturer source URLs. It also lists base
  polymers with trade-name aliases. This repo holds the canonical copy: printfarm-planner,
  print-forge and stl-doctor vendor the two files unchanged, and their CI compares the copies
  with this release. See [docs/registry.md](docs/registry.md).
- Cura's Griffin-flavour `;PRINT.TIME:` header is read as the slicer's time estimate.
  `;GENERATOR.NAME` / `;GENERATOR.VERSION` identify the slicer.
- `metadata.estimated_time_source` in the JSON names the comment the slicer total came from.
  `schema_version` is now 3. Nothing was removed or renamed.

### Changed

- Material densities are now resolved through the registry aliases before the leading-letters
  rule. `Silk PLA` therefore gets the PLA density, where it previously had none and fell back to
  the PLA default with a warning. The density values are unchanged (generic values, not
  datasheet figures).
- For Cura files the time comparison is labelled with its source (`Cura ;PRINT.TIME` or
  `Cura ;TIME`) instead of `total estimated time`.

Before and after, on the new synthetic Griffin fixture (`tests/fixtures/cura_griffin.gcode`):

```text
0.2.0  Model estimate   15.2s
       Slicer estimate  not present in file
0.3.0  Model estimate             15.2s
       Slicer (Cura ;PRINT.TIME)  1m 35s
       Model vs slicer            -80 s (-84.0%)
```

On the audit's Marlin-flavour Cura file (`;TIME:125`) only the label changes, from
`Slicer (total estimated time)  2m 05s` to `Slicer (Cura ;TIME)  2m 05s`.

## [0.2.0] - 2026-11-24

### Fixed

- The filament colour and the printer model the file was sliced for were not read, although Bambu
  Studio, OrcaSlicer and PrusaSlicer write both. printfarm-planner therefore saw a two-colour PLA
  job as `PLA + PLA`, charged a material change against loaded `PLA:black` spools, and could
  schedule a file sliced for one printer model on another.
- Saving `--json` output with `>` in Windows PowerShell produced a file other tools could not read
  (UTF-16 or UTF-8 with a BOM). The new `--out` option writes UTF-8 without a BOM.

### Added

- `metadata.filament_colour` (`filament_colour`, one `#RRGGBB` per filament), `metadata.printer_model`
  (`printer_model`, or Cura's `TARGET_MACHINE.NAME`) and `tools[].colour` in the JSON; the colour
  and printer model also appear in the text summary.
- `"schema_version": 2` at the top of `analyze --json` output. 0.1.0 output has no version field;
  version 2 only adds fields.
- `-o/--out FILE` for `analyze`, `cost` and `compare`.

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

[0.3.0]: https://github.com/projectbin07-stack/gcode-insight/releases/tag/v0.3.0
[0.2.0]: https://github.com/projectbin07-stack/gcode-insight/releases/tag/v0.2.0
[0.1.0]: https://github.com/projectbin07-stack/gcode-insight/releases/tag/v0.1.0
