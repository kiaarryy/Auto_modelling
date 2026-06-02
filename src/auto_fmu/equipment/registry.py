from __future__ import annotations

from typing import Type

from auto_fmu.equipment.base import EquipmentRunner, RunnerContext
from auto_fmu.equipment.fixture import FixtureRunner


RUNNERS: dict[str, Type[EquipmentRunner]] = {}


def register_runner(equipment_type: str, runner: Type[EquipmentRunner]) -> None:
    RUNNERS[equipment_type] = runner


def create_runner(context: RunnerContext) -> EquipmentRunner:
    runner = RUNNERS.get(context.equipment_type, FixtureRunner)
    return runner(context)
