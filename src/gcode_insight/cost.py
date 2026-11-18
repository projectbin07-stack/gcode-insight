"""Per-print and batch cost model.

For one copy::

    filament    = mass_g / 1000 * filament_price_per_kg
    machine     = hours * machine_rate_per_hour
    electricity = power_watts / 1000 * hours * electricity_price_per_kwh
    run_cost    = filament + machine + electricity
    failure     = run_cost * failure_rate / (1 - failure_rate)
    unit_cost   = run_cost + failure + setup_cost / copies
    unit_price  = unit_cost * (1 + margin)

``failure`` is the expected cost of failed attempts per *good* part: with a
failure rate ``f`` you start ``1 / (1 - f)`` prints for every part you keep.
``margin`` is a markup on cost (0.4 means price = cost * 1.4), not a share of
the selling price. ``setup_cost`` is charged once per batch (plate preparation,
handling) and spread over the copies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = ["CostBreakdown", "CostInputs", "compute_cost"]


@dataclass(frozen=True, slots=True)
class CostInputs:
    """Cost parameters. Rates are fractions (0.05 = 5 %); money is unit-less."""

    filament_price_per_kg: float
    machine_rate_per_hour: float = 0.0
    power_watts: float = 0.0
    electricity_price_per_kwh: float = 0.0
    failure_rate: float = 0.0
    margin: float = 0.0
    setup_cost: float = 0.0
    copies: int = 1

    def __post_init__(self) -> None:
        for name in (
            "filament_price_per_kg",
            "machine_rate_per_hour",
            "power_watts",
            "electricity_price_per_kwh",
            "margin",
            "setup_cost",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if not 0.0 <= self.failure_rate < 1.0:
            raise ValueError("failure_rate must be in the range [0, 1)")
        if self.copies < 1:
            raise ValueError("copies must be at least 1")


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Result of :func:`compute_cost`. Per-copy values unless prefixed ``batch_``."""

    mass_g: float
    time_s: float
    copies: int
    filament: float
    machine: float
    electricity: float
    failure_allowance: float
    setup_share: float
    unit_cost: float
    unit_price: float
    batch_cost: float
    batch_price: float
    batch_mass_g: float
    batch_time_s: float

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def compute_cost(mass_g: float, time_s: float, inputs: CostInputs) -> CostBreakdown:
    """Cost one print of ``mass_g`` grams taking ``time_s`` seconds.

    Batch figures assume ``inputs.copies`` separate runs of the same file, so
    batch time and mass are simply multiples of the single-run values.
    """
    if mass_g < 0 or time_s < 0:
        raise ValueError("mass and time must not be negative")
    hours = time_s / 3600.0
    filament = mass_g / 1000.0 * inputs.filament_price_per_kg
    machine = hours * inputs.machine_rate_per_hour
    electricity = inputs.power_watts / 1000.0 * hours * inputs.electricity_price_per_kwh
    run_cost = filament + machine + electricity
    failure = run_cost * inputs.failure_rate / (1.0 - inputs.failure_rate)
    setup_share = inputs.setup_cost / inputs.copies
    unit_cost = run_cost + failure + setup_share
    unit_price = unit_cost * (1.0 + inputs.margin)
    return CostBreakdown(
        mass_g=mass_g,
        time_s=time_s,
        copies=inputs.copies,
        filament=filament,
        machine=machine,
        electricity=electricity,
        failure_allowance=failure,
        setup_share=setup_share,
        unit_cost=unit_cost,
        unit_price=unit_price,
        batch_cost=unit_cost * inputs.copies,
        batch_price=unit_price * inputs.copies,
        batch_mass_g=mass_g * inputs.copies,
        batch_time_s=time_s * inputs.copies,
    )
