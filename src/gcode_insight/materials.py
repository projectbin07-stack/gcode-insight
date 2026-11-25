"""Filament geometry helpers and a small material density table."""

from __future__ import annotations

import math

from .registry import load_registry

__all__ = [
    "DEFAULT_DENSITY",
    "DEFAULT_FILAMENT_DIAMETER",
    "MATERIAL_DENSITIES",
    "density_for",
    "filament_mass_g",
    "filament_volume_mm3",
]

#: Generic solid densities in g/cm^3, from the shared registry (``print_registry.json``).
#: They are not datasheet figures: real spools vary by a few percent between brands and
#: colours, so pass an explicit density when the spool's datasheet has one.
MATERIAL_DENSITIES: dict[str, float] = {
    m.key: m.density_g_cm3 for m in load_registry().materials if m.density_g_cm3 is not None
}

DEFAULT_FILAMENT_DIAMETER = 1.75
DEFAULT_DENSITY = MATERIAL_DENSITIES["PLA"]


def density_for(material: str) -> float | None:
    """Look up a density for a material name such as ``"PLA"`` or ``"PETG-CF"``.

    The shared registry resolves the name to its base polymer, first through its aliases
    (``"Silk PLA"``, ``"PLA+"``, ``"PETG HF"``), then by its leading letters, so
    ``"pla basic"`` and ``"PLA-CF"`` both resolve to PLA. Filled variants really are slightly
    denser than the base polymer; that difference is ignored here. Returns ``None`` for unknown
    materials and for polymers without a generic density (PA, PC, PET, PVA).
    """
    return load_registry().density(material)


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
