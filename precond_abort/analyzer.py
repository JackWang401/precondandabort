from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol

import numpy as np

from .calibration import CalibrationRepository
from .errors import InputValidationError
from .mapping import MOTION_LOGICAL_NAMES
from .models import (
    AbortEvent,
    AnalysisResult,
    CalibrationParameter,
    MappingConfiguration,
    SignalSeries,
)


class SignalSource(Protocol):
    def read_many(self, requested_names) -> dict[str, SignalSeries]: ...


MOTION_RULES = (
    ("strAng", "steering_wheel_angle", "SteeringWheelAngle_Th"),
    ("strAngSpd", "steering_wheel_angle_rate", "AEB_SteeringAngleRate_Override"),
    ("yawRate", "yaw_rate", "YawrateSuspension_Th"),
    ("latAccel", "lateral_acceleration", "LateralAcceleration_th"),
)

ANALYSIS_LOGICAL_NAMES = (
    "vehicle_speed",
    *MOTION_LOGICAL_NAMES,
    "abort_any_active_event",
)
THROTTLE_DISABLED_WARNING = (
    "Throttle checks are temporarily disabled because the calParam worksheet does not "
    "provide the complete throttle parameter set."
)


class AbortAnalyzer:
    def __init__(self, deceleration_end_tolerance_seconds: float = 0.5):
        self.deceleration_end_tolerance_seconds = deceleration_end_tolerance_seconds

    def analyze(
        self,
        source: SignalSource,
        mapping: MappingConfiguration,
        calibrations: CalibrationRepository,
        input_file: str | Path,
        parameter_overrides: Mapping[str, CalibrationParameter] | None = None,
    ) -> AnalysisResult:
        requested = [mapping.signal(name).model_logger for name in ANALYSIS_LOGICAL_NAMES]
        by_requested_name = source.read_many(requested)
        signals = {
            logical_name: by_requested_name[mapping.signal(logical_name).model_logger]
            for logical_name in ANALYSIS_LOGICAL_NAMES
        }
        parameter_names = self._parameter_names(mapping)
        overrides = parameter_overrides or {}
        automatically_resolved = calibrations.resolve_many(
            requested_name
            for role, requested_name in parameter_names.items()
            if role not in overrides
        )
        parameters = {
            role: overrides.get(role, automatically_resolved.get(requested_name))
            for role, requested_name in parameter_names.items()
        }
        if any(parameter is None for parameter in parameters.values()):
            raise InputValidationError("One or more calibration parameter bindings are missing")

        abort = signals["abort_any_active_event"]
        active = abort.samples >= 0.5
        rising_indices = np.flatnonzero(active & np.r_[True, ~active[:-1]])
        events = tuple(
            self._analyse_event(
                timestamp=float(abort.timestamps[index]),
                filename=Path(input_file).name,
                signals=signals,
                parameters=parameters,
                parameter_names=parameter_names,
            )
            for index in rising_indices
        )
        warnings = tuple(item for item in (mapping.warning, THROTTLE_DISABLED_WARNING) if item)
        used_parameters = {
            requested_name: parameters[role]
            for role, requested_name in parameter_names.items()
        }
        return AnalysisResult(
            input_file=Path(input_file),
            events=events,
            mapping=mapping,
            parameters=used_parameters,
            warnings=warnings,
        )

    def _parameter_names(self, mapping: MappingConfiguration) -> dict[str, str]:
        names: dict[str, str] = {}
        for _, logical_name, default_name in MOTION_RULES:
            configured = mapping.signal(logical_name).calibrations
            names[logical_name] = configured[0] if configured else default_name
        return names

    def _analyse_event(
        self,
        timestamp: float,
        filename: str,
        signals: Mapping[str, SignalSeries],
        parameters: Mapping[str, CalibrationParameter],
        parameter_names: Mapping[str, str],
    ) -> AbortEvent:
        speed = signals["vehicle_speed"].value_at(timestamp)
        values = {
            logical_name: series.value_at(timestamp)
            for logical_name, series in signals.items()
            if logical_name != "abort_any_active_event"
        }
        thresholds: dict[str, float] = {}
        flags = {
            "strAng": False,
            "strAngSpd": False,
            "yawRate": False,
            "latAccel": False,
            "throttleInc": False,
            "maxThrottle": False,
            "others": False,
        }
        for output_name, logical_name, _ in MOTION_RULES:
            threshold = parameters[logical_name].value_at(speed)
            thresholds[logical_name] = threshold
            flags[output_name] = abs(values[logical_name]) >= threshold

        flags["others"] = not any(value for name, value in flags.items() if name != "others")

        return AbortEvent(
            filename=filename,
            timestamp=timestamp,
            flags=flags,
            signal_values=values,
            thresholds=thresholds,
            vehicle_speed=speed,
            throttle_baseline=None,
            throttle_increase=None,
            deceleration_start=None,
        )
