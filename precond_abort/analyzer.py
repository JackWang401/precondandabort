from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol

import numpy as np

from .calibration import CalibrationRepository
from .errors import InputValidationError
from .mapping import MOTION_LOGICAL_NAMES, THROTTLE_PARAMETER_BY_ROLE
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
THROTTLE_LOGICAL_NAMES = ("throttle", "aeb_deceleration_request")
THROTTLE_PARAMETER_DEFAULTS = THROTTLE_PARAMETER_BY_ROLE
THROTTLE_DISABLED_WARNING = (
    "Throttle checks are disabled because no SAFETY CAL JSON file was selected."
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
        enable_throttle_checks: bool = False,
    ) -> AnalysisResult:
        logical_names = ANALYSIS_LOGICAL_NAMES + (
            THROTTLE_LOGICAL_NAMES if enable_throttle_checks else ()
        )
        self._validate_mapping(mapping, logical_names, enable_throttle_checks)
        requested = [mapping.signal(name).model_logger for name in logical_names]
        by_requested_name = source.read_many(requested)
        signals = {
            logical_name: by_requested_name[mapping.signal(logical_name).model_logger]
            for logical_name in logical_names
        }
        parameter_names = self._parameter_names(mapping, enable_throttle_checks)
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
                enable_throttle_checks=enable_throttle_checks,
            )
            for index in rising_indices
        )
        warnings = tuple(
            item
            for item in (
                mapping.warning,
                None if enable_throttle_checks else THROTTLE_DISABLED_WARNING,
            )
            if item
        )
        used_parameters = {
            requested_name: parameters[role]
            for role, requested_name in parameter_names.items()
        }
        return AnalysisResult(
            input_file=Path(input_file),
            events=events,
            mapping=mapping,
            parameters=used_parameters,
            input_files=(Path(input_file),),
            warnings=warnings,
            throttle_checks_enabled=enable_throttle_checks,
        )

    def _validate_mapping(
        self,
        mapping: MappingConfiguration,
        logical_names: tuple[str, ...],
        enable_throttle_checks: bool,
    ) -> None:
        missing = [
            logical_name
            for logical_name in logical_names
            if logical_name not in mapping.signals
            or not mapping.signals[logical_name].model_logger
        ]
        if missing:
            mode = "Throttle checks require" if enable_throttle_checks else "Analysis requires"
            raise InputValidationError(
                f"{mode} these swIntfc signal mappings:\n- " + "\n- ".join(missing)
            )

    def _parameter_names(
        self,
        mapping: MappingConfiguration,
        enable_throttle_checks: bool,
    ) -> dict[str, str]:
        names: dict[str, str] = {}
        for _, logical_name, default_name in MOTION_RULES:
            configured = mapping.signal(logical_name).calibrations
            names[logical_name] = configured[0] if configured else default_name
        if enable_throttle_checks:
            names.update(THROTTLE_PARAMETER_DEFAULTS)
        return names

    def _analyse_event(
        self,
        timestamp: float,
        filename: str,
        signals: Mapping[str, SignalSeries],
        parameters: Mapping[str, CalibrationParameter],
        enable_throttle_checks: bool,
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

        throttle_baseline = None
        throttle_increase = None
        deceleration_start = None
        if enable_throttle_checks:
            throttle = values["throttle"]
            absolute_throttle = abs(throttle)
            thresholds.update(
                {
                    role: parameters[role].value_at(speed)
                    for role in THROTTLE_PARAMETER_DEFAULTS
                }
            )
            deceleration_start = self._deceleration_start_at(
                timestamp,
                signals["aeb_deceleration_request"],
            )
            if deceleration_start is not None:
                throttle_baseline = signals["throttle"].value_at(deceleration_start)
                throttle_increase = throttle - throttle_baseline
                flags["throttleInc"] = (
                    throttle_increase > thresholds["throttle_increase"]
                    and absolute_throttle > thresholds["throttle_override"]
                )
            flags["maxThrottle"] = absolute_throttle > thresholds["throttle_max"]

        flags["others"] = not any(value for name, value in flags.items() if name != "others")

        return AbortEvent(
            filename=filename,
            timestamp=timestamp,
            flags=flags,
            signal_values=values,
            thresholds=thresholds,
            vehicle_speed=speed,
            throttle_baseline=throttle_baseline,
            throttle_increase=throttle_increase,
            deceleration_start=deceleration_start,
        )

    def _deceleration_start_at(
        self,
        timestamp: float,
        request: SignalSeries,
    ) -> float | None:
        """Return the active/recent AEB intervention start for an abort event."""

        intervention = np.isclose(request.samples, -6.0) | np.isclose(
            request.samples,
            -15.0,
        )
        start_indices = np.flatnonzero(intervention & np.r_[True, ~intervention[:-1]])
        for start_index in reversed(start_indices):
            start_time = float(request.timestamps[start_index])
            if start_time > timestamp:
                continue
            following_inactive = np.flatnonzero(~intervention[start_index + 1 :])
            if len(following_inactive) == 0:
                return start_time
            end_index = start_index + 1 + int(following_inactive[0])
            end_time = float(request.timestamps[end_index])
            if timestamp <= end_time + self.deceleration_end_tolerance_seconds:
                return start_time
            return None
        return None


def combine_analysis_results(results: tuple[AnalysisResult, ...]) -> AnalysisResult:
    """Combine per-measurement results for one batch report."""

    if not results:
        raise InputValidationError("Select at least one MDF/MF4 measurement file")
    first = results[0]
    if any(
        result.throttle_checks_enabled != first.throttle_checks_enabled
        for result in results[1:]
    ):
        raise InputValidationError(
            "All measurements in a batch must use the same throttle-check mode"
        )
    return AnalysisResult(
        input_file=first.input_file,
        input_files=tuple(
            input_file
            for result in results
            for input_file in result.source_files
        ),
        events=tuple(event for result in results for event in result.events),
        mapping=first.mapping,
        parameters=first.parameters,
        warnings=tuple(
            dict.fromkeys(warning for result in results for warning in result.warnings)
        ),
        throttle_checks_enabled=first.throttle_checks_enabled,
    )
