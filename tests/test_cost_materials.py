from __future__ import annotations

import math

import pytest

from gcode_insight.cost import CostInputs, compute_cost
from gcode_insight.materials import (
    MATERIAL_DENSITIES,
    density_for,
    filament_mass_g,
    filament_volume_mm3,
)


def test_density_table_and_lookup() -> None:
    assert set(MATERIAL_DENSITIES) == {"PLA", "PETG", "ABS", "ASA", "TPU"}
    assert density_for("PLA") == 1.24
    assert density_for(" petg ") == 1.27
    assert density_for("PLA+") == 1.24
    assert density_for("PETG-CF") == 1.27
    assert density_for("TPU 95A") == 1.21
    assert density_for("Nylon") is None
    assert density_for("") is None


def test_volume_and_mass_of_one_metre() -> None:
    # 1000 mm of 1.75 mm filament: pi * 0.875^2 * 1000 = 2405.28 mm^3 -> 2.9825 g of PLA.
    assert filament_volume_mm3(1000.0) == pytest.approx(math.pi * 0.765625 * 1000.0)
    assert filament_volume_mm3(1000.0) == pytest.approx(2405.28, abs=0.01)
    assert filament_mass_g(1000.0) == pytest.approx(2.9825, abs=1e-4)
    assert filament_mass_g(1000.0, 2.85, 1.04) == pytest.approx(math.pi * 1.425**2 * 1.04)


def test_volume_and_mass_reject_bad_inputs() -> None:
    with pytest.raises(ValueError):
        filament_volume_mm3(10.0, 0.0)
    with pytest.raises(ValueError):
        filament_mass_g(10.0, 1.75, -1.0)


def test_cost_worked_example() -> None:
    # 50 g at 20/kg = 1.00; 2 h at 1.50/h = 3.00; 100 W for 2 h at 0.25/kWh = 0.05.
    # Run cost 4.05; 10 % failures -> 4.05 / 0.9 = 4.50 (allowance 0.45);
    # setup 5.00 over 10 copies = 0.50; unit cost 5.00; 40 % markup -> 7.00.
    inputs = CostInputs(
        filament_price_per_kg=20.0,
        machine_rate_per_hour=1.5,
        power_watts=100.0,
        electricity_price_per_kwh=0.25,
        failure_rate=0.10,
        margin=0.40,
        setup_cost=5.0,
        copies=10,
    )
    cost = compute_cost(50.0, 7200.0, inputs)
    assert cost.filament == pytest.approx(1.00)
    assert cost.machine == pytest.approx(3.00)
    assert cost.electricity == pytest.approx(0.05)
    assert cost.failure_allowance == pytest.approx(0.45)
    assert cost.setup_share == pytest.approx(0.50)
    assert cost.unit_cost == pytest.approx(5.00)
    assert cost.unit_price == pytest.approx(7.00)
    assert cost.batch_cost == pytest.approx(50.0)
    assert cost.batch_price == pytest.approx(70.0)
    assert cost.batch_mass_g == pytest.approx(500.0)
    assert cost.batch_time_s == pytest.approx(72000.0)
    assert cost.to_dict()["copies"] == 10


def test_cost_filament_only_defaults() -> None:
    cost = compute_cost(250.0, 3600.0, CostInputs(filament_price_per_kg=24.0))
    assert cost.unit_cost == pytest.approx(6.0)
    assert cost.unit_price == pytest.approx(6.0)
    assert cost.batch_cost == pytest.approx(6.0)
    assert cost.failure_allowance == 0.0


def test_cost_input_validation() -> None:
    with pytest.raises(ValueError):
        CostInputs(filament_price_per_kg=-1.0)
    with pytest.raises(ValueError):
        CostInputs(filament_price_per_kg=20.0, failure_rate=1.0)
    with pytest.raises(ValueError):
        CostInputs(filament_price_per_kg=20.0, failure_rate=-0.1)
    with pytest.raises(ValueError):
        CostInputs(filament_price_per_kg=20.0, copies=0)
    with pytest.raises(ValueError):
        CostInputs(filament_price_per_kg=20.0, margin=-0.5)


def test_cost_rejects_negative_mass_or_time() -> None:
    inputs = CostInputs(filament_price_per_kg=20.0)
    with pytest.raises(ValueError):
        compute_cost(-1.0, 10.0, inputs)
    with pytest.raises(ValueError):
        compute_cost(1.0, -10.0, inputs)
