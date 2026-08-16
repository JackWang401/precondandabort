import unittest

from precond_abort.gui import (
    LOAD_CONFIG_PLACEHOLDER,
    THRESHOLD_BINDING_SPECS,
    initial_binding_row,
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


if __name__ == "__main__":
    unittest.main()
