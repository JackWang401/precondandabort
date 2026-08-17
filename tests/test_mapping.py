import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from precond_abort.errors import MappingError
from precond_abort.mapping import (
    DEFAULT_SIGNAL_ROWS,
    MOTION_LOGICAL_NAMES,
    load_calibration_specs,
    load_mapping,
    match_calibration_specs,
    match_motion_calibration_specs,
)


class MappingTests(unittest.TestCase):
    def _workbook(self, directory: Path, include_sheet=True, omit=None) -> Path:
        path = directory / "mapping.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "swIntfc" if include_sheet else "general"
        sheet.append(["acronym", "modelLogger", "cal_thd"])
        labels = {
            "vehicle_speed": "vehicleSpeed",
            "steering_wheel_angle": "steeringWheelAngle",
            "steering_wheel_angle_rate": "steeringWheelAngleSpeed",
            "yaw_rate": "yawRate",
            "lateral_acceleration": "lateralAcceleration",
            "throttle": "PedalPosPro",
            "abort_any_active_event": "abort_any_active_event",
            "aeb_deceleration_request": "aeb_deceleration_request",
        }
        for row in DEFAULT_SIGNAL_ROWS:
            if row.logical_name == omit:
                continue
            sheet.append([labels[row.logical_name], row.model_logger, "; ".join(row.calibrations)])
        parameters = workbook.create_sheet("calParam")
        parameters.append(["parameter", "x", "y"])
        for row in DEFAULT_SIGNAL_ROWS:
            if row.logical_name not in MOTION_LOGICAL_NAMES:
                continue
            parameter = row.calibrations[0]
            parameters.append([parameter, f"{parameter}_x", f"{parameter}_y"])
        workbook.save(path)
        workbook.close()
        return path

    def test_reads_valid_swintfc(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_mapping(self._workbook(Path(directory)))
        self.assertIsNone(config.warning)
        self.assertEqual(config.signal("steering_wheel_angle_rate").model_logger, "rov/SteeringWheelAngleRate")

    def test_missing_swintfc_uses_visible_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_mapping(self._workbook(Path(directory), include_sheet=False))
        self.assertIn("does not contain", config.warning)
        self.assertEqual(config.signal("vehicle_speed").model_logger, "rov/vehicleSpeed")

    def test_incomplete_swintfc_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MappingError, "missing acronym for yaw_rate"):
                load_mapping(self._workbook(Path(directory), omit="yaw_rate"))

    def test_calparam_rows_match_the_motion_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._workbook(Path(directory))
            mapping = load_mapping(path)
            specs = load_calibration_specs(path)
            matched = match_motion_calibration_specs(mapping, specs)
        self.assertEqual(set(matched), set(MOTION_LOGICAL_NAMES))
        self.assertEqual(
            matched["steering_wheel_angle"].x_entry_name,
            "SteeringWheelAngle_Th_x",
        )

    def test_throttle_calparam_rows_are_required_when_safety_cal_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._workbook(Path(directory))
            mapping = load_mapping(path)
            specs = load_calibration_specs(path)
            with self.assertRaisesRegex(
                MappingError,
                "required throttle parameters",
            ):
                match_calibration_specs(mapping, specs, require_throttle=True)

    def test_throttle_mapping_is_optional_while_checks_are_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_mapping(self._workbook(Path(directory), omit="throttle"))
        self.assertNotIn("throttle", config.signals)

    def test_supplied_windows_excel_workbook_is_complete(self):
        workbook = Path(__file__).resolve().parents[1] / "PrecondAndAbort.xlsx"
        if not workbook.exists():
            self.skipTest("The supplied Windows workbook is not available")
        mapping = load_mapping(workbook)
        matched = match_motion_calibration_specs(
            mapping,
            load_calibration_specs(workbook),
        )
        self.assertEqual(set(matched), set(MOTION_LOGICAL_NAMES))
        self.assertIn("throttle", mapping.signals)

        all_matched = match_calibration_specs(
            mapping,
            load_calibration_specs(workbook),
            require_throttle=True,
        )
        self.assertEqual(
            set(all_matched) - set(MOTION_LOGICAL_NAMES),
            {"throttle_increase", "throttle_override", "throttle_max"},
        )


if __name__ == "__main__":
    unittest.main()
