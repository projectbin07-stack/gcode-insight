from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from gcode_insight.materials import density_for
from gcode_insight.registry import (
    REGISTRY_PATH,
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
    assert reg.version == 1
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
