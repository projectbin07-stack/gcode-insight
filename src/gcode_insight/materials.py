"""Filament geometry helpers and a small material density table."""

from __future__ import annotations

import math
import re

__all__ = [
    "DEFAULT_DENSITY",
    "DEFAULT_FILAMENT_DIAMETER",
    "MATERIAL_DENSITIES",
    "density_for",
    "filament_mass_g",
    "filament_volume_mm3",
]

#: Typical solid densities in g/cm^3. Real spools vary by a few percent between
#: brands and colours; pass an explicit density when the spool's datasheet has one.
MATERIAL_DENSITIES: dict[str, float] = {
    "PLA": 1.24,
    "PETG": 1.27,
    "ABS": 1.04,
    "ASA": 1.07,
    "TPU": 1.21,
}

DEFAULT_FILAMENT_DIAMETER = 1.75
DEFAULT_DENSITY = MATERIAL_DENSITIES["PLA"]

_LEADING_LETTERS = re.compile(r"[A-Z]+")


def density_for(material: str) -> float | None:
    """Look up a density for a material name such as ``"PLA"`` or ``"PETG-CF"``.

    Matching uses the leading letters only, so ``"PLA+"``, ``"pla basic"`` and
    ``"PLA-CF"`` all resolve to PLA. Filled variants really are slightly denser
    than the base polymer; that difference is ignored here. Returns ``None`` for
    unknown materials.
    """
    match = _LEADING_LETTERS.match(material.strip().upper())
    if match is None:
        return None
    return MATERIAL_DENSITIES.get(match.group(0))


def filament_volume_mm3(length_mm: float, diameter_mm: float = DEFAULT_FILAMENT_DIAMETER) -> float:
    """Volume of a filament strand of the given length, in mm^3."""
    if diameter_mm <= 0:
        raise ValueError("filament diameter must be positive")
    return length_mm * math.pi * (diameter_mm / 2.0) ** 2


def filament_mass_g(
    length_mm: float,
    diameter_mm: float = DEFAULT_FILAMENT_DIAMETER,
    density_g_cm3: float = DEFAULT_DENSITY,
) -> float:
    """Mass in grams of a filament strand of the given length."""
    if density_g_cm3 <= 0:
        raise ValueError("density must be positive")
    return filament_volume_mm3(length_mm, diameter_mm) / 1000.0 * density_g_cm3
