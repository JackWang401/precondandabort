import unittest
from pathlib import Path

import numpy as np

from precond_abort.analyzer import AbortAnalyzer, combine_analysis_results
from precond_abort.calibration import CalibrationRepository
from precond_abort.mapping import default_mapping
from precond_abort.models import SignalSeries
from precond_abort.models import CalibrationParameter


class FakeSignalSource:
    def __init__(self, series):
        self.series = series

    def read_many(self, requested_names):
        return {name: self.series[name] for name in requested_names}


def series(timestamps, samples):
    return SignalSeries(np.asarray(timestamps, dtype=float), np.asarray(samples, dtype=float))


class AbortAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.mapping = default_mapping()
        document = {
            "cals": {
                "SteeringWheelAngle_Th_x": {"value": [0, 100]},
                "SteeringWheelAngle_Th_y": {"value": [10, 10]},
                "AEB_SteeringAngleRate_Override_x": {"value": [0, 100]},
                "AEB_SteeringAngleRate_Override_y": {"value": [20, 20]},
                "YawrateSuspension_Th_x": {"value": [0, 100]},
                "YawrateSuspension_Th_y": {"value": [30, 30]},
                "LateralAcceleration_th_x": {"value": [0, 100]},
                "LateralAcceleration_th_y": {"value": [4, 4]},
                "LSB_Throttle_Override_Increase": {"value": [20, 20, 20]},
                "LSB_Min_Throttle_Override": {"value": [50, 50, 50]},
                "PedalPosPro_th_x": {"value": [0, 100]},
                "PedalPosPro_th_y": {"value": [85, 85]},
            }
        }
        self.calibrations = CalibrationRepository.from_document(document)

    def _source(self):
        logical = {
            "vehicle_speed": series([0, 1, 2, 3, 4, 5, 6], [10] * 7),
            "steering_wheel_angle": series([0, 1, 2, 3, 4, 5, 6], [0, -11, 0, 0, 0, 0, 0]),
            "steering_wheel_angle_rate": series([0, 1, 2, 3, 4, 5, 6], [0] * 7),
            "yaw_rate": series([0, 1, 2, 3, 4, 5, 6], [0] * 7),
            "lateral_acceleration": series([0, 1, 2, 3, 4, 5, 6], [0] * 7),
            "throttle": series([0, 1, 2, 3, 4, 5, 6], [0, 0, 0, 10, 70, 90, 1]),
            "abort_any_active_event": series([0, 1, 2, 3, 4, 5, 6], [0, 1, 1, 0, 1, 0, 1]),
            "aeb_deceleration_request": series([0, 1, 2, 3, 4, 5, 6], [0, 0, 0, -6, -6, 0, 0]),
        }
        by_requested = {
            self.mapping.signal(name).model_logger: value for name, value in logical.items()
        }
        return FakeSignalSource(by_requested)

    def test_classifies_motion_and_marks_non_motion_events_as_others(self):
        result = AbortAnalyzer().analyze(
            self._source(),
            self.mapping,
            self.calibrations,
            Path("input.mf4"),
        )
        self.assertEqual(len(result.events), 3)
        self.assertTrue(result.events[0].flags["strAng"])
        self.assertEqual(result.events[0].reasons, ("strAng",))
        self.assertTrue(result.events[1].flags["others"])
        self.assertFalse(result.events[1].flags["throttleInc"])
        self.assertFalse(result.events[1].flags["maxThrottle"])
        self.assertTrue(result.events[2].flags["others"])
        self.assertIn("Throttle checks are disabled", result.warnings[-1])

    def test_throttle_signals_and_parameters_are_not_required(self):
        result = AbortAnalyzer().analyze(
            self._source(), self.mapping, self.calibrations, "input.mf4"
        )
        second = result.events[1]
        self.assertFalse(second.flags["maxThrottle"])
        self.assertFalse(second.flags["throttleInc"])
        self.assertNotIn("throttle", second.signal_values)
        self.assertNotIn("throttle_max", second.thresholds)

    def test_safety_cal_mode_enables_throttle_checks(self):
        result = AbortAnalyzer().analyze(
            self._source(),
            self.mapping,
            self.calibrations,
            "input.mf4",
            enable_throttle_checks=True,
        )

        second = result.events[1]
        self.assertTrue(result.throttle_checks_enabled)
        self.assertEqual(second.deceleration_start, 3)
        self.assertEqual(second.throttle_baseline, 10)
        self.assertEqual(second.throttle_increase, 60)
        self.assertEqual(second.thresholds["throttle_increase"], 20)
        self.assertEqual(second.thresholds["throttle_override"], 50)
        self.assertEqual(second.thresholds["throttle_max"], 85)
        self.assertTrue(second.flags["throttleInc"])
        self.assertFalse(second.flags["maxThrottle"])
        self.assertFalse(second.flags["others"])
        self.assertNotIn("Throttle checks are disabled", "\n".join(result.warnings))

        third = result.events[2]
        self.assertIsNone(third.deceleration_start)
        self.assertIsNone(third.throttle_baseline)
        self.assertIsNone(third.throttle_increase)
        self.assertTrue(third.flags["others"])

    def test_enabled_max_throttle_check_uses_speed_threshold(self):
        source = self._source()
        throttle_name = self.mapping.signal("throttle").model_logger
        source.series[throttle_name] = series(
            [0, 1, 2, 3, 4, 5, 6],
            [0, 0, 0, 10, 90, 90, 1],
        )
        result = AbortAnalyzer().analyze(
            source,
            self.mapping,
            self.calibrations,
            "input.mf4",
            enable_throttle_checks=True,
        )

        self.assertTrue(result.events[1].flags["maxThrottle"])
        self.assertEqual(result.events[1].signal_values["throttle"], 90)

    def test_throttle_checks_use_strict_above_threshold_comparisons(self):
        source = self._source()
        throttle_name = self.mapping.signal("throttle").model_logger
        source.series[throttle_name] = series(
            [0, 1, 2, 3, 4, 5, 6],
            [0, 0, 0, 65, 85, 85, 1],
        )
        result = AbortAnalyzer().analyze(
            source,
            self.mapping,
            self.calibrations,
            "input.mf4",
            enable_throttle_checks=True,
        )

        event = result.events[1]
        self.assertEqual(event.throttle_increase, 20)
        self.assertFalse(event.flags["throttleInc"])
        self.assertFalse(event.flags["maxThrottle"])
        self.assertTrue(event.flags["others"])

    def test_absolute_throttle_can_activate_the_or_condition(self):
        source = self._source()
        throttle_name = self.mapping.signal("throttle").model_logger
        source.series[throttle_name] = series(
            [0, 1, 2, 3, 4, 5, 6],
            [0, 0, 0, -10, -90, -90, 1],
        )
        result = AbortAnalyzer().analyze(
            source,
            self.mapping,
            self.calibrations,
            "input.mf4",
            enable_throttle_checks=True,
        )

        event = result.events[1]
        self.assertFalse(event.flags["throttleInc"])
        self.assertTrue(event.flags["maxThrottle"])
        self.assertFalse(event.flags["others"])
        self.assertEqual(event.output_row()[18], 90)

    def test_explicit_parameter_binding_overrides_default_parameter(self):
        override = CalibrationParameter(
            name="UserSelectedAngleThreshold",
            source="manual:user.x + user.y",
            x_values=(0.0, 100.0),
            y_values=(100.0, 100.0),
            x_source="user.x",
            y_source="user.y",
        )
        result = AbortAnalyzer().analyze(
            self._source(),
            self.mapping,
            self.calibrations,
            "input.mf4",
            parameter_overrides={"steering_wheel_angle": override},
        )
        self.assertFalse(result.events[0].flags["strAng"])
        self.assertEqual(result.events[0].thresholds["steering_wheel_angle"], 100)
        self.assertEqual(
            result.parameters["SteeringWheelAngle_Th"].source,
            "manual:user.x + user.y",
        )

    def test_combines_events_from_multiple_measurements(self):
        first = AbortAnalyzer().analyze(
            self._source(), self.mapping, self.calibrations, "first.mf4"
        )
        second = AbortAnalyzer().analyze(
            self._source(), self.mapping, self.calibrations, "second.mdf"
        )

        combined = combine_analysis_results((first, second))

        self.assertEqual(combined.source_files, (Path("first.mf4"), Path("second.mdf")))
        self.assertEqual(len(combined.events), 6)
        self.assertEqual(combined.events[0].filename, "first.mf4")
        self.assertEqual(combined.events[3].filename, "second.mdf")
        self.assertEqual(len(combined.warnings), len(first.warnings))


if __name__ == "__main__":
    unittest.main()
