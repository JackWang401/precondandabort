import unittest
from collections import Counter
from pathlib import Path

from precond_abort.analyzer import AbortAnalyzer
from precond_abort.calibration import CalibrationRepository
from precond_abort.mapping import (
    load_calibration_specs,
    load_mapping,
    match_motion_calibration_specs,
)
from precond_abort.mdf_reader import MDFSignalSource


ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "AADT-202904_1_000_DADC_COLLECTIONS_CCPLEX_ORIN_CCPLEX_JLR_CAL.json"
MDF_PATH = ROOT / "MODEL_LOGGER_AADT-146546_1_000_DADC_COLLECTIONS_model_logger_modelLogger_session_19_0.mf4"
MAPPING_PATH = ROOT / "PrecondAndAbort.numbers"


@unittest.skipUnless(
    JSON_PATH.exists() and MDF_PATH.exists() and MAPPING_PATH.exists(),
    "supplied sample artifacts are not available",
)
class SuppliedSampleIntegrationTests(unittest.TestCase):
    def test_supplied_sample_detects_expected_events_and_reasons(self):
        calibrations = CalibrationRepository.from_json(JSON_PATH)
        mapping = load_mapping(MAPPING_PATH)
        specs = match_motion_calibration_specs(mapping, load_calibration_specs(MAPPING_PATH))
        overrides = {
            logical_name: calibrations.combine_spec(spec)
            for logical_name, spec in specs.items()
        }
        with MDFSignalSource(MDF_PATH) as source:
            result = AbortAnalyzer().analyze(
                source,
                mapping,
                calibrations,
                MDF_PATH,
                parameter_overrides=overrides,
            )

        self.assertEqual(len(result.events), 34)
        self.assertAlmostEqual(result.events[0].timestamp, 81.301378169)
        self.assertAlmostEqual(result.events[-1].timestamp, 2204.734212797)
        counts = Counter(
            reason
            for event in result.events
            for reason, active in event.flags.items()
            if active
        )
        self.assertEqual(
            counts,
            {
                "strAng": 2,
                "strAngSpd": 4,
                "yawRate": 7,
                "others": 21,
            },
        )
        self.assertTrue(all(not event.flags["throttleInc"] for event in result.events))
        self.assertTrue(all(not event.flags["maxThrottle"] for event in result.events))
        self.assertTrue(
            all("calParam row" in parameter.source for parameter in result.parameters.values())
        )


if __name__ == "__main__":
    unittest.main()
