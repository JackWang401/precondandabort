from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import numpy as np


@dataclass(frozen=True)
class SignalMapping:
    logical_name: str
    model_logger: str
    calibrations: tuple[str, ...] = ()


@dataclass(frozen=True)
class MappingConfiguration:
    signals: Mapping[str, SignalMapping]
    source: str
    warning: str | None = None

    def signal(self, logical_name: str) -> SignalMapping:
        return self.signals[logical_name]


@dataclass(frozen=True)
class CalibrationEntry:
    name: str
    source: str
    values: tuple[float, ...]
    unit: str = ""


@dataclass(frozen=True)
class CalibrationBindingSpec:
    parameter_name: str
    x_entry_name: str
    y_entry_name: str
    source: str


@dataclass(frozen=True)
class CalibrationParameter:
    name: str
    source: str
    x_values: tuple[float, ...]
    y_values: tuple[float, ...]
    x_unit: str = ""
    y_unit: str = ""
    x_source: str = ""
    y_source: str = ""

    @property
    def is_curve(self) -> bool:
        return len(self.x_values) > 1

    def value_at(self, x_value: float) -> float:
        if not self.y_values:
            raise ValueError(f"Calibration parameter {self.name!r} has no values")
        if len(self.y_values) == 1:
            return self.y_values[0]
        return float(np.interp(float(x_value), self.x_values, self.y_values))


@dataclass(frozen=True)
class SignalSeries:
    timestamps: np.ndarray
    samples: np.ndarray
    unit: str = ""
    source_name: str = ""

    def value_at(self, timestamp: float) -> float:
        if len(self.timestamps) == 0:
            raise ValueError(f"Signal {self.source_name!r} is empty")
        index = int(np.searchsorted(self.timestamps, timestamp, side="right") - 1)
        index = max(0, min(index, len(self.samples) - 1))
        return float(self.samples[index])


@dataclass(frozen=True)
class AbortEvent:
    filename: str
    timestamp: float
    flags: Mapping[str, bool]
    signal_values: Mapping[str, float]
    thresholds: Mapping[str, float]
    vehicle_speed: float
    throttle_baseline: float | None = None
    throttle_increase: float | None = None
    deceleration_start: float | None = None

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(name for name, active in self.flags.items() if active)

    def output_row(self) -> list[object]:
        yes_no = lambda name: "Yes" if self.flags[name] else "No"
        return [
            self.filename,
            self.timestamp,
            self.vehicle_speed,
            abs(self.signal_values["steering_wheel_angle"]),
            self.thresholds["steering_wheel_angle"],
            yes_no("strAng"),
            abs(self.signal_values["steering_wheel_angle_rate"]),
            self.thresholds["steering_wheel_angle_rate"],
            yes_no("strAngSpd"),
            abs(self.signal_values["yaw_rate"]),
            self.thresholds["yaw_rate"],
            yes_no("yawRate"),
            abs(self.signal_values["lateral_acceleration"]),
            self.thresholds["lateral_acceleration"],
            yes_no("latAccel"),
            self.throttle_increase,
            self.thresholds.get("throttle_increase"),
            yes_no("throttleInc"),
            self.signal_values.get("throttle"),
            self.thresholds.get("throttle_max"),
            yes_no("maxThrottle"),
            yes_no("others"),
        ]


@dataclass(frozen=True)
class AnalysisResult:
    input_file: Path
    events: tuple[AbortEvent, ...]
    mapping: MappingConfiguration
    parameters: Mapping[str, CalibrationParameter]
    input_files: tuple[Path, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def source_files(self) -> tuple[Path, ...]:
        return self.input_files or (self.input_file,)
