from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from auto_fmu.config import EQUIPMENT_TYPES, load_config, validate_config
from auto_fmu.hygiene import scan_hygiene
from auto_fmu.orchestration import run_batch, run_equipment
from auto_fmu.pipeline import calibrate, prepare, report, validate
from auto_fmu.regression_runner import run_regression


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="auto-fmu")
    commands = root.add_subparsers(dest="command", required=True)
    validate_config_parser = commands.add_parser("validate-config")
    validate_config_parser.add_argument("--config", required=True)
    regression = commands.add_parser("regression")
    regression.add_argument("--config", required=True)
    regression.add_argument("--equipment", default="all", choices=("all", *EQUIPMENT_TYPES))
    regression.add_argument("--run-id", required=True)
    hygiene = commands.add_parser("scan-hygiene")
    hygiene.add_argument("--root", default=".")
    run = commands.add_parser("run")
    run.add_argument("--config", required=True)
    run.add_argument("--equipment", required=True, choices=EQUIPMENT_TYPES)
    run.add_argument("--equipment-id", required=True)
    run.add_argument("--run-id", required=True)
    batch = commands.add_parser("batch")
    batch.add_argument("--config", required=True)
    batch.add_argument("--equipment", default="all", choices=("all", *EQUIPMENT_TYPES))
    batch.add_argument("--run-id", required=True)
    for command in ("prepare", "calibrate", "validate", "report"):
        stage = commands.add_parser(command)
        stage.add_argument("--config", required=True)
        stage.add_argument("--equipment", default="all", choices=("all", *EQUIPMENT_TYPES))
        stage.add_argument("--run-id", required=True)
    return root


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "scan-hygiene":
        return 1 if scan_hygiene(Path(args.root)) else 0
    if args.command == "regression":
        run_regression(Path(args.config), args.equipment, args.run_id)
        return 0
    config = load_config(Path(args.config))
    errors = validate_config(config)
    if errors:
        raise ValueError("\n".join(errors))
    if args.command == "validate-config":
        return 0
    if args.command == "run":
        run_equipment(config, args.equipment, args.equipment_id, args.run_id)
        return 0
    if args.command == "batch":
        run_batch(config, args.equipment, args.run_id)
        return 0
    stages = {"prepare": prepare, "calibrate": calibrate, "validate": validate, "report": report}
    stages[args.command](config, args.equipment, args.run_id)
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
