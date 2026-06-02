from __future__ import annotations

from typing import Type

from auto_fmu.equipment.base import EquipmentRunner, RunnerContext
from auto_fmu.equipment.fixture import FixtureRunner


RUNNERS: dict[str, Type[EquipmentRunner]] = {}


def register_runner(equipment_type: str, runner: Type[EquipmentRunner]) -> None:
    RUNNERS[equipment_type] = runner


def create_runner(context: RunnerContext) -> EquipmentRunner:
    if context.device.get("runner") == "pump_empirical":
        from auto_fmu.equipment.pump import PumpRunner

        return PumpRunner(context)
    if context.device.get("runner") == "chiller_external":
        from auto_fmu.equipment.chiller import ChillerRunner

        return ChillerRunner(context)
    if context.device.get("runner") == "cooling_tower_external":
        from auto_fmu.equipment.cooling_tower import CoolingTowerRunner

        return CoolingTowerRunner(context)
    if context.device.get("runner") == "heat_exchanger_external":
        from auto_fmu.equipment.heat_exchanger import HeatExchangerRunner

        return HeatExchangerRunner(context)
    runner = RUNNERS.get(context.equipment_type, FixtureRunner)
    return runner(context)
