import tempfile
import unittest
from pathlib import Path

from precond_abort.errors import InputValidationError
from precond_abort.gui import (
    LOAD_CONFIG_PLACEHOLDER,
    SAFETY_CAL_LABEL,
    THRESHOLD_BINDING_SPECS,
    VCS_CAL_LABEL,
    analysis_output_path,
    default_mapping_workbook,
    default_path_state_path,
    enable_windows_dpi_awareness,
    initial_binding_row,
    read_path_state,
    selected_calibration_paths,
    write_path_state,
)


class GuiConfigurationTests(unittest.TestCase):
    def test_calibration_file_labels_are_domain_specific(self):
        self.assertEqual(VCS_CAL_LABEL, "VCS CAL")
        self.assertEqual(SAFETY_CAL_LABEL, "SAFETY CAL")

    def test_vcs_cal_is_required_and_safety_cal_is_optional(self):
        self.assertEqual(selected_calibration_paths("", "/cal/safety.json"), ())
        vcs_path = str(Path("/cal/vcs.json").resolve())
        safety_path = str(Path("/cal/safety.json").resolve())
        self.assertEqual(
            selected_calibration_paths("/cal/vcs.json"),
            (vcs_path,),
        )
        self.assertEqual(
            selected_calibration_paths("/cal/vcs.json", "/cal/safety.json"),
            (vcs_path, safety_path),
        )

    def test_windows_state_is_saved_under_local_app_data(self):
        path = default_path_state_path(
            platform_name="nt",
            environment={"LOCALAPPDATA": "/windows/LocalAppData"},
        )
        self.assertEqual(
            path,
            Path("/windows/LocalAppData/PrecondAbortAnalyzer/state.json"),
        )

    def test_windows_state_path_has_a_home_directory_fallback(self):
        path = default_path_state_path(
            platform_name="nt",
            environment={},
            home_directory="/windows/User",
        )
        self.assertEqual(
            path,
            Path("/windows/User/AppData/Local/PrecondAbortAnalyzer/state.json"),
        )

    def test_windows_prefers_excel_mapping_workbook(self):
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first_root = Path(first_directory)
            second_root = Path(second_directory)
            numbers = first_root / "PrecondAndAbort.numbers"
            excel = second_root / "PrecondAndAbort.xlsx"
            numbers.touch()
            excel.touch()

            self.assertEqual(
                default_mapping_workbook(
                    (first_root, second_root),
                    platform_name="nt",
                ),
                excel.resolve(),
            )
            self.assertEqual(
                default_mapping_workbook(
                    (first_root, second_root),
                    platform_name="posix",
                ),
                numbers.resolve(),
            )

    def test_windows_dpi_helper_is_a_noop_on_other_platforms(self):
        self.assertFalse(enable_windows_dpi_awareness(platform_name="posix"))

    def test_all_calibratables_have_placeholder_rows(self):
        roles = [role for role, _, _ in THRESHOLD_BINDING_SPECS]
        self.assertEqual(
            roles,
            [
                "steering_wheel_angle",
                "steering_wheel_angle_rate",
                "yaw_rate",
                "lateral_acceleration",
                "throttle_increase",
                "throttle_override",
                "throttle_max",
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = analysis_output_path((str(root / "run_01.mf4"),))
        self.assertEqual(output, root / "run_01_abort_analysis.xlsx")

    def test_batch_report_is_saved_in_shared_measurement_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = analysis_output_path(
                (str(root / "run_01.mf4"), str(root / "run_02.mdf"))
            )
        self.assertEqual(
            output,
            root / "combined_2_files_abort_analysis.xlsx",
        )

    def test_batch_measurements_in_different_folders_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a" / "run_01.mf4"
            second = root / "b" / "run_02.mdf"
            with self.assertRaisesRegex(InputValidationError, "must be in the same folder"):
                analysis_output_path((str(first), str(second)))


if __name__ == "__main__":
    unittest.main()
