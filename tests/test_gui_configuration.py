import tempfile
import unittest
from pathlib import Path

from precond_abort.errors import InputValidationError
from precond_abort.gui import (
    LOAD_CONFIG_PLACEHOLDER,
    THRESHOLD_BINDING_SPECS,
    analysis_output_path,
    initial_binding_row,
    read_path_state,
    write_path_state,
)


class GuiConfigurationTests(unittest.TestCase):
    def test_all_calibratables_have_placeholder_rows(self):
        roles = [role for role, _, _ in THRESHOLD_BINDING_SPECS]
        self.assertEqual(
            roles,
            [
                "steering_wheel_angle",
                "steering_wheel_angle_rate",
                "yaw_rate",
                "lateral_acceleration",
            ],
        )
        self.assertTrue(LOAD_CONFIG_PLACEHOLDER)
        self.assertEqual(
            initial_binding_row("Steering wheel angle"),
            (
                "Steering wheel angle",
                LOAD_CONFIG_PLACEHOLDER,
                LOAD_CONFIG_PLACEHOLDER,
                "Waiting",
            ),
        )

    def test_previous_file_selections_round_trip(self):
        state = {
            "version": 1,
            "calibration_json_1": "/cal/first.json",
            "calibration_json_2": "/cal/second.json",
            "measurement_files": ["/measurements/one.mf4", "/measurements/two.mdf"],
            "mapping_workbook": "/config/PrecondAndAbort.numbers",
            "output_report": "/reports/abort_analysis.xlsx",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".precond_abort_state.json"
            write_path_state(state, path)
            restored = read_path_state(path)
        self.assertEqual(restored, state)

    def test_invalid_previous_path_state_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".precond_abort_state.json"
            path.write_text("not valid JSON", encoding="utf-8")
            with self.assertRaisesRegex(InputValidationError, "Cannot read saved HMI paths"):
                read_path_state(path)

    def test_single_measurement_report_is_saved_beside_input(self):
        output = analysis_output_path(("/measurements/run_01.mf4",))
        self.assertEqual(output, Path("/measurements/run_01_abort_analysis.xlsx"))

    def test_batch_report_is_saved_in_shared_measurement_folder(self):
        output = analysis_output_path(
            ("/measurements/run_01.mf4", "/measurements/run_02.mdf")
        )
        self.assertEqual(
            output,
            Path("/measurements/combined_2_files_abort_analysis.xlsx"),
        )

    def test_batch_measurements_in_different_folders_are_rejected(self):
        with self.assertRaisesRegex(InputValidationError, "must be in the same folder"):
            analysis_output_path(
                ("/measurements/a/run_01.mf4", "/measurements/b/run_02.mdf")
            )


if __name__ == "__main__":
    unittest.main()
