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
- **Connection facts per printer** (schema 2, see below): the slicer's model code, the model
  code the printer reports, the camera stream and port, and whether the status report carries
  a chamber temperature.
- **AMS models** (schema 2): `ams`, `ams-lite`, `ams-2-pro`, `ams-ht`, with the module name
  that tells them apart in the printer's `get_version` reply.
- **Materials:** base polymer key (`PLA`), name, aliases (`PLA Silk`, `PETG HF`, `PLA-CF`,
  `PLA+`) and a generic density where one is held.

## Python API

`gcode_insight.registry` is a public API since gcode-insight 0.4.0. The names in its
`__all__` are also exported from `gcode_insight` itself, and they are only removed or changed
incompatibly in a new major version. Every type is a frozen dataclass with full type hints.

| Name | What it is |
|---|---|
| `load_registry(path=None) -> Registry` | the shipped data file (cached), or another file |
| `parse_registry(data) -> Registry` | validate already-decoded JSON |
| `Registry.printer(name) -> PrinterSpec or None` | by key, model, alias or slicer full name (`Bambu Lab X1 Carbon`), ignoring case, hyphens and underscores |
| `Registry.material(name)`, `.base_polymer(name)`, `.density(name)` | material lookups (`PLA Silk` gives PLA) |
| `Registry.ams_model(key) -> AmsModel or None` | `ams`, `ams-lite`, `ams-2-pro`, `ams-ht` |
| `Registry.version`, `.schema_version` | `registry_version` (the data) and `schema_version` (the layout) |
| `Registry.printers`, `.materials`, `.ams_models` | tuples in file order |
| `PrinterSpec` | the printer fields above, `.full_name`, and `.connection: ConnectionFacts` |
| `ConnectionFacts` | `slicer_model_id`, `reported_project_name`, `camera_stream`, `camera_port`, `chamber_temperature`: each a `Fact` or `None` |
| `Fact[V]` | `value` (`str`, `int` or `bool`), `basis` (`"official"` or `"community"`), `sources: tuple[Source, ...]`, `note: str or None` |
| `AmsModel` | `key`, `name`, `get_version_module: Fact[str] or None` |
| `MaterialSpec` | `key`, `name`, `aliases`, `density_g_cm3` |
| `Source` | `url` (https), `retrieved` (`YYYY-MM-DD`), `covers` (what the page states) |
| `RegistryError` | raised for a missing, malformed or inconsistent data file |
| `SCHEMA_VERSION` (`REGISTRY_SCHEMA_VERSION` in `gcode_insight`) | newest layout the loader reads (2); it also reads 1 |

```python
from gcode_insight import load_registry

registry = load_registry()
p1s = registry.printer("Bambu Lab P1S")
assert p1s is not None
print(p1s.build_volume_mm, p1s.ams_max_slots)  # (256.0, 256.0, 256.0) 16
model_id = p1s.connection.slicer_model_id
print(model_id.value, model_id.basis)  # C12 official
port = p1s.connection.camera_port
print(port.value, port.basis)  # 6000 community
print(p1s.connection.chamber_temperature)  # None: no source settles it
```

## Schema 2: connection facts

Each printer may have a `connection` object. Every entry in it is a fact with a value, a
basis, its sources and an optional note. From the P1S entry (URL shortened here):

```json
"connection": {
  "slicer_model_id": {
    "value": "C12", "basis": "official",
    "sources": [
      {"url": "https://github.com/bambulab/BambuStudio/blob/23a3375.../Bambu%20Lab%20P1S.json",
       "retrieved": "2026-11-25",
       "covers": "Bambu Studio machine profile \"Bambu Lab P1S\": \"model_id\": \"C12\""}
    ]
  },
  "camera_port": {"value": 6000, "basis": "community", "sources": ["..."]}
}
```

| Fact | Type | Meaning |
|---|---|---|
| `slicer_model_id` | string | `model_id` in Bambu Studio's machine profile |
| `reported_project_name` | string | `project_name` of the `esp32` module in the printer's `get_version` reply |
| `camera_stream` | `"rtsps"` or `"jpeg-tls"` | how the LAN camera streams: RTSP over TLS, or JPEG frames on a TLS socket |
| `camera_port` | integer | TCP port of that stream |
| `chamber_temperature` | boolean | whether the status report carries a usable chamber temperature |

`basis` is `"official"` only when a source is Bambu Lab's own: its wiki, store pages, blog or
the Bambu Studio source code. It is `"community"` when the only sources are third-party reverse
engineering (OpenBambuAPI, ha-bambulab). Bambu Lab publishes no protocol document, so
community facts describe what those projects observe on current firmware, and a firmware
update can change them. Community sources are cited at a fixed commit so the cited lines stay
where they are. All sources were read on 2026-11-25.

| | P1S | P1P | X1 Carbon | A1 | A1 mini |
|---|---|---|---|---|---|
| `slicer_model_id` (official) | C12 | C11 | BL-P001 | N2S | N1 |
| `reported_project_name` (community) | C12 | C11 | left out | N2S | N1 |
| `camera_stream` / `camera_port` (community) | jpeg-tls / 6000 | jpeg-tls / 6000 | rtsps / 322 | jpeg-tls / 6000 | jpeg-tls / 6000 |
| `chamber_temperature` (community) | left out | left out | true | false | false |

The top-level `ams_models` list gives the module prefix each AMS model uses in `get_version`
(community, ha-bambulab): `ams` (AMS), `ams_f1` (AMS lite), `n3f` (AMS 2 Pro) and `n3s`
(AMS HT).

**Left out on purpose**, because no source read settles them (the data file's
`connection_note` says the same):

- The SSDP `DevModel.bambu.com` value of each model. That it carries the `model_id` codes
  above is an inference; community code only shows an emulator advertising `BL-P001` for an
  X1 Carbon.
- The X1 Carbon's `reported_project_name`: ha-bambulab sees it empty and identifies the X1C
  by its board instead.
- Whether a P1S or P1P reports a usable chamber temperature. ha-bambulab does not expose one
  for them, but whether the field is absent or only meaningless is unconfirmed.
- Camera frame rates, and the firmware versions any of these facts depend on.

The P1S `reported_project_name` carries a note: ha-bambulab sees newer P1S firmware report an
empty `esp32` product name and name the model in the `ota` module instead, so `project_name`
may be absent there.

A schema 1 file still loads with the new loader: its printers have empty `ConnectionFacts`
and the registry has no AMS models. Older loaders (gcode-insight 0.3.0 and the copies vendored
from it) refuse a schema 2 file with "registry schema 2 is newer than 1", so the data file and
`registry.py` always move together, which the consumers' CI check already enforces.

## Sources

Every printer entry has at least one manufacturer source URL and its retrieval date, and the
loader rejects an entry without one; the same holds for every connection fact. Printer
specification figures come only from manufacturer pages: Bambu Lab's
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
   retrieval date for any printer figure. Do not add a figure that has no source. Mark a
   connection fact `community` unless a Bambu Lab source states it, and leave it out when the
   sources disagree or only imply it. A change to the layout also bumps `schema_version`.
2. Run the tests (`tests/test_registry.py`), update the changelog, and release gcode-insight.
3. Copy both files unchanged into the consumers. Move each consumer's pin, in the `registry`
   job and anywhere else it pins gcode-insight, to the new tag, then release the consumers.
