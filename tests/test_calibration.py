import json
import tempfile
import unittest
from pathlib import Path

from precond_abort.calibration import CalibrationRepository
from precond_abort.errors import CalibrationError


class CalibrationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.document = {
            "configuration": {
                "module": {
                    "Curve_x": {"unit": "km/h", "value": [0, 10, 20]},
                    "Curve_y": {"unit": "deg", "value": [100, 50, 25]},
                    "Constant": {"unit": "%", "value": [20, 20, 20]},
                    "LSB_Throttle_Override_Increase": {"unit": "%", "value": [15, 15]},
                    "ManualSpeed": {"unit": "km/h", "value": [0, 20, 40]},
                    "ManualThreshold": {"unit": "deg", "value": [90, 60, 30]},
                    "ShortThreshold": {"unit": "deg", "value": [90, 60]},
                    "DuplicateSpeed": {"unit": "km/h", "value": [0, 20, 20]},
                }
            }
        }
        self.repository = CalibrationRepository.from_document(self.document)

    def test_combines_xy_and_interpolates(self):
        parameter = self.repository.resolve("Curve")
        self.assertEqual(parameter.x_values, (0.0, 10.0, 20.0))
        self.assertAlmostEqual(parameter.value_at(5), 75)
        self.assertAlmostEqual(parameter.value_at(-1), 100)
        self.assertAlmostEqual(parameter.value_at(99), 25)

    def test_constant_array_is_supported(self):
        parameter = self.repository.resolve("Constant")
        self.assertFalse(parameter.is_curve)
        self.assertEqual(parameter.value_at(123), 20)

    def test_requirement_alias_resolves_supplied_name(self):
        parameter = self.repository.resolve("PedalPosProIncrease_Th")
        self.assertEqual(parameter.name, "LSB_Throttle_Override_Increase")

    def test_user_can_combine_independent_x_and_y_entries(self):
        parameter = self.repository.combine_entries(
            "SteeringWheelAngle_Th",
            "ManualSpeed",
            "ManualThreshold",
        )
        self.assertEqual(parameter.x_values, (0.0, 20.0, 40.0))
        self.assertEqual(parameter.y_values, (90.0, 60.0, 30.0))
        self.assertEqual(parameter.value_at(10), 75)
        self.assertTrue(parameter.x_source.endswith("ManualSpeed"))
        self.assertTrue(parameter.y_source.endswith("ManualThreshold"))

    def test_custom_entries_do_not_require_conventional_xy_names(self):
        repository = CalibrationRepository.from_document(
            {
                "custom": {
                    "VehicleSpeedPoints": {"value": [0, 50, 100]},
                    "DriverAngleLimit": {"value": [300, 150, 75]},
                }
            }
        )
        self.assertEqual(len(repository.parameters), 0)
        parameter = repository.combine_entries(
            "SteeringWheelAngle_Th",
            "VehicleSpeedPoints",
            "DriverAngleLimit",
        )
        self.assertEqual(parameter.value_at(25), 225)

    def test_constant_binding_requires_constant_y_values(self):
        with self.assertRaisesRegex(CalibrationError, "select an X entry"):
            self.repository.combine_entries(
                "SteeringWheelAngle_Th",
                None,
                "ManualThreshold",
            )

    def test_manual_binding_rejects_mismatched_point_counts(self):
        with self.assertRaisesRegex(CalibrationError, "3 values.*2 values"):
            self.repository.combine_entries(
                "SteeringWheelAngle_Th",
                "ManualSpeed",
                "ShortThreshold",
            )

    def test_manual_binding_rejects_duplicate_x_values(self):
        with self.assertRaisesRegex(CalibrationError, "duplicate values"):
            self.repository.combine_entries(
                "SteeringWheelAngle_Th",
                "DuplicateSpeed",
                "ManualThreshold",
            )

    def test_mismatched_curve_is_rejected(self):
        document = {"x": {"Bad_x": {"value": [1, 2]}, "Bad_y": {"value": [3]}}}
        repository = CalibrationRepository.from_document(document)
        with self.assertRaisesRegex(CalibrationError, "2 x values but 1 y values"):
            repository.resolve("Bad")

    def test_loads_entries_from_two_json_files_with_source_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "motion_a.json"
            second = Path(directory) / "motion_b.json"
            first.write_text(
                json.dumps(
                    {"first": {"SpeedPoints": {"unit": "km/h", "value": [0, 50]}}}
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {"second": {"AngleLimit": {"unit": "deg", "value": [100, 20]}}}
                ),
                encoding="utf-8",
            )

            repository = CalibrationRepository.from_json_files((first, second))
            parameter = repository.combine_entries(
                "SteeringWheelAngle_Th",
                "SpeedPoints",
                "AngleLimit",
            )

            self.assertEqual(parameter.value_at(25), 60)
            self.assertTrue(parameter.x_source.startswith("motion_a.json::"))
            self.assertTrue(parameter.y_source.startswith("motion_b.json::"))

    def test_rejects_selecting_the_same_json_file_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(
                json.dumps({"cal": {"Value": {"value": 1}}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CalibrationError, "different calibration JSON files"):
                CalibrationRepository.from_json_files((path, path))


if __name__ == "__main__":
    unittest.main()
