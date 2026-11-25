from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from gcode_insight.materials import density_for
from gcode_insight.registry import (
    REGISTRY_PATH,
    ConnectionFacts,
    RegistryError,
    load_registry,
    normalise_material_name,
    normalise_printer_name,
    parse_registry,
)


def _raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return data


def test_registry_loads_with_every_printer_sourced() -> None:
    reg = load_registry()
    assert reg.version == 2
    assert reg.schema_version == 2
    assert [p.key for p in reg.printers] == ["p1s", "p1p", "x1c", "a1", "a1-mini"]
    for p in reg.printers:
        assert p.sources, p.key
        assert all(s.url.startswith("https://") and s.retrieved for s in p.sources)
        assert p.nozzle_included_mm in p.nozzle_options_mm
        assert p.ams_max_slots == p.ams_max_units * p.ams_slots_per_unit


def test_published_build_volumes() -> None:
    reg = load_registry()
    volumes = {p.key: p.build_volume_mm for p in reg.printers}
    assert volumes == {
        "p1s": (256.0, 256.0, 256.0),
        "p1p": (256.0, 256.0, 256.0),
        "x1c": (256.0, 256.0, 256.0),
        "a1": (256.0, 256.0, 256.0),
        "a1-mini": (180.0, 180.0, 180.0),
    }
    enclosed = {p.key for p in reg.printers if p.enclosed}
    assert enclosed == {"p1s", "x1c"}


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("X1C", "x1c"),
        ("x1-carbon", "x1c"),
        ("Bambu Lab X1 Carbon", "x1c"),
        ("P1P", "p1p"),
        ("p1s", "p1s"),
        ("A1 mini", "a1-mini"),
        ("a1_mini", "a1-mini"),
        ("Bambu Lab A1 mini", "a1-mini"),
        ("  bambu lab   A1 ", "a1"),
    ],
)
def test_printer_lookup(name: str, key: str) -> None:
    spec = load_registry().printer(name)
    assert spec is not None
    assert spec.key == key


def test_unknown_printer_is_none() -> None:
    assert load_registry().printer("Voron 2.4 350") is None
    assert load_registry().printer("") is None


def test_full_name_and_normalisers() -> None:
    spec = load_registry().printer("x1c")
    assert spec is not None
    assert spec.full_name == "Bambu Lab X1 Carbon"
    assert normalise_printer_name("Bambu Lab A1-mini") == "A1 MINI"
    assert normalise_material_name(" pla-cf ") == "PLA CF"


@pytest.mark.parametrize(
    ("name", "base"),
    [
        ("PLA-CF", "PLA"),
        ("PLA Silk", "PLA"),
        ("Silk PLA", "PLA"),
        ("pla basic", "PLA"),
        ("PLA+", "PLA"),
        ("PETG HF", "PETG"),
        ("PETG-CF", "PETG"),
        ("PET-G", "PETG"),
        ("TPU 95A", "TPU"),
        ("Nylon", "PA"),
        ("PAHT-CF", "PA"),
        ("PA6-GF", "PA"),
        ("PET", "PET"),
    ],
)
def test_material_base_polymer(name: str, base: str) -> None:
    assert load_registry().base_polymer(name) == base


def test_unknown_material() -> None:
    reg = load_registry()
    # Leading letters "PCTG" are not "PC", so the copolyester does not pass as polycarbonate.
    assert reg.base_polymer("PCTG") is None
    assert reg.base_polymer("HIPS") is None
    assert reg.base_polymer("") is None
    assert reg.density("PCTG") is None


def test_density_through_aliases() -> None:
    assert density_for("Silk PLA") == 1.24  # leading letters alone gave None before 0.3.0
    assert density_for("PETG HF") == 1.27
    assert density_for("PA6-CF") is None  # known polymer, no generic density held


def _broken(edit: Any) -> dict[str, Any]:
    data = copy.deepcopy(_raw())
    edit(data)
    return data


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d.pop("printers"), "missing 'printers'"),
        (lambda d: d.update(schema_version=99), "newer"),
        (lambda d: d["printers"][0].update(build_volume_mm=[256, 256]), "build_volume_mm"),
        (lambda d: d["printers"][0].update(build_volume_mm=[256, 0, 256]), "positive"),
        (lambda d: d["printers"][0]["nozzle"].update(included_mm=0.5), "not in options_mm"),
        (lambda d: d["printers"][0]["ams"].update(max_slots=12), "max_slots"),
        (lambda d: d["printers"][0].update(sources=[]), "at least one source"),
        (
            lambda d: d["printers"][0]["sources"][0].update(url="http://example.com"),
            "https",
        ),
        (lambda d: d["printers"][1].update(aliases=["P1S"]), "used by both"),
        (lambda d: d["materials"][1]["aliases"].append("PLA Silk"), "used by both"),
        (lambda d: d["materials"][0].update(key="pla"), "upper-case"),
        (lambda d: d["materials"][0].update(density_g_cm3=-1), "positive"),
        (lambda d: d["printers"][0].update(enclosed="yes"), "wrong type"),
        (lambda d: d["printers"][0]["ams"].update(max_units=-1), ">= 0"),
        (lambda d: d["printers"][0].update(aliases=[""]), "non-empty strings"),
    ],
)
def test_parse_rejects_inconsistent_data(edit: Any, message: str) -> None:
    with pytest.raises(RegistryError, match=message):
        parse_registry(_broken(edit))


def test_parse_rejects_non_object() -> None:
    with pytest.raises(RegistryError):
        parse_registry([])


def test_load_reports_unreadable_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(RegistryError, match=r"bad.json"):
        load_registry(bad)


# ------------------------------------------------------- schema 2: connection facts


def test_slicer_model_ids_are_official_and_sourced() -> None:
    reg = load_registry()
    codes = {}
    for p in reg.printers:
        fact = p.connection.slicer_model_id
        assert fact is not None, p.key
        assert fact.basis == "official"
        assert fact.sources[0].url.startswith("https://github.com/bambulab/BambuStudio/")
        codes[p.key] = fact.value
    assert codes == {"p1s": "C12", "p1p": "C11", "x1c": "BL-P001", "a1": "N2S", "a1-mini": "N1"}


def test_camera_facts_are_community_findings() -> None:
    reg = load_registry()
    cameras = {}
    for p in reg.printers:
        stream, port = p.connection.camera_stream, p.connection.camera_port
        assert stream is not None and port is not None, p.key
        assert stream.basis == port.basis == "community"
        cameras[p.key] = (stream.value, port.value)
    assert cameras == {
        "p1s": ("jpeg-tls", 6000),
        "p1p": ("jpeg-tls", 6000),
        "x1c": ("rtsps", 322),
        "a1": ("jpeg-tls", 6000),
        "a1-mini": ("jpeg-tls", 6000),
    }


def test_uncertain_facts_are_left_out() -> None:
    reg = load_registry()
    by_key = {p.key: p.connection for p in reg.printers}
    # No source settles whether a P1S/P1P reports a usable chamber temperature, and the X1
    # Carbon reports an empty project_name, so these stay unknown rather than guessed.
    assert by_key["p1s"].chamber_temperature is None
    assert by_key["p1p"].chamber_temperature is None
    assert by_key["x1c"].reported_project_name is None
    chamber = {k: c.chamber_temperature.value for k, c in by_key.items() if c.chamber_temperature}
    assert chamber == {"x1c": True, "a1": False, "a1-mini": False}
    note = _raw()["connection_note"]
    assert "DevModel" in note and "chamber" in note


def test_every_fact_has_dated_https_sources() -> None:
    reg = load_registry()
    facts = [
        fact
        for p in reg.printers
        for fact in (
            p.connection.slicer_model_id,
            p.connection.reported_project_name,
            p.connection.camera_stream,
            p.connection.camera_port,
            p.connection.chamber_temperature,
        )
        if fact is not None
    ]
    facts += [m.get_version_module for m in reg.ams_models if m.get_version_module is not None]
    assert len(facts) == 26
    for fact in facts:
        assert fact.sources
        for source in fact.sources:
            assert source.url.startswith("https://")
            assert source.retrieved == "2026-11-25"
            assert source.covers


def test_ams_models_and_their_get_version_modules() -> None:
    reg = load_registry()
    modules = {}
    for model in reg.ams_models:
        assert model.get_version_module is not None
        assert model.get_version_module.basis == "community"
        modules[model.key] = model.get_version_module.value
    assert modules == {"ams": "ams", "ams-lite": "ams_f1", "ams-2-pro": "n3f", "ams-ht": "n3s"}
    lite = reg.ams_model("AMS-Lite")
    assert lite is not None and lite.name == "AMS lite"
    assert reg.ams_model("ams-3") is None


def test_schema_1_data_still_loads_without_connection_facts() -> None:
    data = _raw()
    data["schema_version"] = 1
    data.pop("ams_models")
    for printer in data["printers"]:
        printer.pop("connection")
    reg = parse_registry(data)
    assert reg.schema_version == 1
    assert reg.ams_models == ()
    p1s = reg.printer("P1S")
    assert p1s is not None
    assert p1s.connection == ConnectionFacts()
    assert p1s.connection.camera_port is None


def _fact(d: dict[str, Any], printer: int = 0, name: str = "camera_port") -> dict[str, Any]:
    fact: dict[str, Any] = d["printers"][printer]["connection"][name]
    return fact


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d.update(schema_version=1), "needs schema_version 2"),
        (lambda d: d.update(schema_version=0), "not valid"),
        (lambda d: _fact(d).update(basis="forum"), "official' or 'community"),
        (lambda d: _fact(d).update(sources=[]), "at least one source"),
        (lambda d: _fact(d).update(value="6000"), "wrong type"),
        (lambda d: _fact(d).update(value=True), "wrong type"),
        (lambda d: _fact(d).update(value=70000), "1-65535"),
        (lambda d: _fact(d).update(note=3), "'note' must be a string"),
        (lambda d: _fact(d, name="camera_stream").update(value="mjpeg"), "camera_stream"),
        (lambda d: _fact(d)["sources"][0].update(retrieved="25 Nov"), "YYYY-MM-DD"),
        (lambda d: _fact(d)["sources"][0].update(url="http://x"), "https"),
        (lambda d: d["printers"][0]["connection"].update(wifi={}), "unknown facts"),
        (lambda d: d["printers"][0].update(connection=[]), "wrong type"),
        (lambda d: d["ams_models"][0].update(key="ams-3"), "key must be one of"),
        (lambda d: d["ams_models"][1].update(key="ams"), "duplicate AMS model"),
    ],
)
def test_parse_rejects_bad_connection_facts(edit: Any, message: str) -> None:
    with pytest.raises(RegistryError, match=message):
        parse_registry(_broken(edit))


def test_ams_models_need_schema_2() -> None:
    data = _raw()
    data["schema_version"] = 1
    for printer in data["printers"]:
        printer.pop("connection")
    with pytest.raises(RegistryError, match="'ams_models' needs schema_version 2"):
        parse_registry(data)


def test_registry_is_exported_from_the_package() -> None:
    import gcode_insight

    assert gcode_insight.load_registry is load_registry
    assert gcode_insight.REGISTRY_SCHEMA_VERSION == 2
    for name in ("Registry", "PrinterSpec", "MaterialSpec", "Source", "Fact", "AmsModel"):
        assert name in gcode_insight.__all__
    assert "ConnectionFacts" in gcode_insight.__all__
    assert "RegistryError" in gcode_insight.__all__
