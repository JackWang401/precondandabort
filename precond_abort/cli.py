from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import AbortAnalyzer
from .calibration import CalibrationRepository
from .errors import PrecondAbortError
from .mapping import (
    create_mapping_template,
    load_calibration_specs,
    load_mapping,
    match_motion_calibration_specs,
)
from .mdf_reader import MDFSignalSource
from .report import write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="precond-abort",
        description="Analyze AEB abort events in MDF/MF4 measurements.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Run the analysis and create an Excel report")
    analyze.add_argument("--json", required=True, type=Path, help="Calibration JSON file")
    analyze.add_argument("--mdf", required=True, type=Path, help="Input MDF/MF4 file")
    analyze.add_argument(
        "--mapping",
        required=True,
        type=Path,
        help="Configuration workbook (.numbers, .xlsx, or .xlsm)",
    )
    analyze.add_argument("--output", required=True, type=Path, help="Output .xlsx report")

    template = subparsers.add_parser("mapping-template", help="Create an swIntfc mapping template")
    template.add_argument("output", type=Path, help="Output .xlsx path")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "mapping-template":
            output = create_mapping_template(arguments.output)
            print(f"Created mapping template: {output}")
            return 0
        calibrations = CalibrationRepository.from_json(arguments.json)
        mapping = load_mapping(arguments.mapping)
        binding_specs = match_motion_calibration_specs(
            mapping,
            load_calibration_specs(arguments.mapping),
        )
        parameter_overrides = {
            logical_name: calibrations.combine_spec(spec)
            for logical_name, spec in binding_specs.items()
        }
        with MDFSignalSource(arguments.mdf) as source:
            result = AbortAnalyzer().analyze(
                source,
                mapping,
                calibrations,
                arguments.mdf,
                parameter_overrides=parameter_overrides,
            )
        output = write_report(result, arguments.output)
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        print(f"Analyzed {len(result.events)} abort events")
        print(f"Report: {output}")
        return 0
    except PrecondAbortError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
