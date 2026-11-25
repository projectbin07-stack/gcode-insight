# Shared printer and material registry

`src/gcode_insight/print_registry.json` (data) and `src/gcode_insight/registry.py` (loader,
lookups, validation) form one registry of printers and materials. The same two files, byte for
byte, are also used by:

| Repo | Copy | Uses it for |
|---|---|---|
| gcode-insight (canonical) | `src/gcode_insight/` | material densities, base polymer of slicer material names |
| printfarm-planner | `src/printfarm_planner/` | built-in printer models, nozzle and AMS limits, material normalisation |
| print-forge | `src/print_forge/` | `--printer` build volumes |
| stl-doctor | `src/stl_doctor/` | `--printer` build volumes |

## What it holds

- **Printers:** key (`a1-mini`), vendor, model, aliases, build volume, enclosure, nozzle
  material, included and optional nozzle diameters, included and compatible build plates, AMS
  capacity (units, slots per unit, maximum slots, AMS lite units), notes and sources.
- **Materials:** base polymer key (`PLA`), name, aliases (`PLA Silk`, `PETG HF`, `PLA-CF`,
  `PLA+`) and a generic density where one is held.

Every printer entry has at least one manufacturer source URL and its retrieval date, and the
loader rejects an entry without one. Printer figures come only from those pages: Bambu Lab's
store specification tables, the X1-Carbon Combo quick start guide (the X1 Carbon store page no
longer resolves) and the Bambu Lab wiki's AMS connection guides. The material densities are the
generic values gcode-insight has used since 0.1.0. They are **not** taken from a datasheet, and
the data file says so.

Material names resolve to a base polymer in two steps. First an exact alias match, ignoring
case, spaces, hyphens and underscores (`silk pla` gives PLA). If that fails, the leading letters
are tried (`PETG-CF` gives PETG), which is the rule gcode-insight 0.1.0 used for its density
table. `PCTG` stays unknown rather than being read as `PC`.

## Decision: a vendored file pinned to gcode-insight, not a shared package

The four tools are stdlib-only packages, installed from git tags and not from PyPI. The options
considered were these:

1. **A new `print-registry` package that the others depend on.** This would add a runtime
   dependency, installed from a git URL, to four packages that currently have none. Users and
   CI would have to resolve that dependency, and a fifth repository would need its own release
   cycle. Rejected.
2. **One repo owns the data and the others import it at runtime.** This would make stl-doctor
   and print-forge depend on an unrelated tool just to read five build volumes. Rejected for the
   same reason.
3. **Vendor the two files into each repo, with one canonical owner and a CI check.** Every
   package stays dependency-free and works offline. The cost is copying two files when the data
   changes. Chosen.

**gcode-insight owns the canonical copy.** It is the lowest layer of the pipeline (it reads what
the slicer wrote), it already owned the material normalisation that the planner needed, and
printfarm-planner's CI already pins a gcode-insight release.

**Drift is caught in CI.** Each consumer has a `registry` job that downloads `registry.py` and
`print_registry.json` from the gcode-insight tag it pins and fails if either file differs from
its own copy (`cmp`). The job runs on Linux. `.gitattributes` forces LF line endings, so the
check is byte-exact.

## Changing the registry

1. Edit the canonical files here and bump `registry_version` in the data. Add a source URL and
   retrieval date for any printer figure. Do not add a figure that has no source.
2. Run the tests (`tests/test_registry.py`), update the changelog, and release gcode-insight.
3. Copy both files unchanged into the consumers. Move each consumer's pin, in the `registry`
   job and anywhere else it pins gcode-insight, to the new tag, then release the consumers.
