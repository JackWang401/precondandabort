# Precondition & Abort Analyzer

A local desktop HMI and command-line tool for classifying AEB abort events in MDF/MF4 measurements. The analyzer reads `swIntfc` and `calParam` directly from an Apple Numbers or Excel configuration workbook, retrieves the specified speed-dependent thresholds from JSON, identifies abort-event rising edges, and creates an auditable Excel report.

## What is implemented

- Direct `.numbers`, `.xlsx`, and `.xlsm` reading for `swIntfc` and `calParam`
- Combined calibration lookup across two user-selected JSON files, with automatic X/Y binding from `calParam` and optional manual override
- Linear threshold interpolation with endpoint clamping
- A desktop HMI with two JSON selectors, multi-file MDF/MF4 selection, calibration curve visualization, live interpolation, progress, and event preview
- Case-insensitive `swIntfc` signal mapping with documented acronym aliases
- A warning-backed built-in mapping when the supplied workbook has no `swIntfc` sheet
- MDF/MF4 reading through `asammdf`
- Motion and `others` classification; throttle checks are temporarily disabled
- A formatted Excel report with two-level `actual / thd / result` comparison groups, plus event, mapping, parameter, and run-detail sheets
- A CLI for repeatable single-file execution

## Installation

Python 3.10 or newer is required. The desktop HMI also requires a Python build with Tk support.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run the HMI

```bash
source .venv/bin/activate
python run_app.py
```

When the HMI starts, the four active motion calibratables are visible as placeholder rows, and file-navigation dialogs prompt you to locate two calibration JSON files. The application does not assume that either file is in the repository or another fixed location. If a dialog is cancelled, use the separate **Browse** control beside **Calibration JSON 1** or **Calibration JSON 2** when you are ready.

The application combines the numeric entries from both JSON files and labels each source with its originating filename. It then reads each motion parameter and its X/Y entry names from the configuration workbook's `calParam` tab. X and Y may come from different JSON files. Matching pairs are retrieved automatically and marked **calParam** in the HMI. Select a row to preview its curve and interpolated threshold. You can still choose different entries and select **Use selected X/Y** to override that row. Use `constant — no X axis` when the selected Y entry is scalar or all of its values are equal.

The **Measurement MDF/MF4 files** selector accepts one or more files in a single selection. Every selected file is analyzed with the same mapping and calibration bindings, and all events are written to one Excel report. The HMI preview and report retain the originating filename for each event.

The analyzer currently uses bindings for steering-wheel angle, steering-wheel-angle speed, yaw rate, and lateral acceleration. Pair validation rejects mismatched point counts and duplicate X values before the analysis starts. Throttle signals and parameters are not required until the missing throttle parameter has been added to `calParam`.

## Run from the command line

```bash
source .venv/bin/activate
python -m precond_abort.cli analyze \
  --json AADT-202904_1_000_DADC_COLLECTIONS_CCPLEX_ORIN_CCPLEX_JLR_CAL.json \
  --mdf MODEL_LOGGER_AADT-146546_1_000_DADC_COLLECTIONS_model_logger_modelLogger_session_19_0.mf4 \
  --mapping PrecondAndAbort.numbers \
  --output outputs/abort_analysis.xlsx
```

The command returns exit code `0` on success and `2` for an actionable input or analysis error.

## Configuration workbook

The software searches the workbook for tabs named `swIntfc` and `calParam` without regard to case. `swIntfc` requires these columns:

| acronym | modelLogger | cal_thd |
| --- | --- | --- |
| vehicleSpeed | rov/vehicleSpeed | |
| steeringWheelAngle | rov/SteeringWheelAngle | SteeringWheelAngle_Th |
| steeringWheelAngleRate | rov/SteeringWheelAngleRate | AEB_SteeringAngleRate_Override |
| yawRate | rov/YawrateSuspension | YawrateSuspension_Th |
| lateralAcceleration | rov/lateralAcceleration | LateralAcceleration_th |
| abort_any_active_event | settingsRequest/AEB/abortAnyActiveEvents | |

Throttle and deceleration-request rows may remain in `swIntfc`, but they are optional while throttle checking is disabled.

The active `calParam` rows are:

| parameter | x | y |
| --- | --- | --- |
| AEB_SteeringAngleRate_Override | AEB_SteeringAngleRate_Override_x | AEB_SteeringAngleRate_Override_y |
| SteeringWheelAngle_Th | SteeringWheelAngle_Th_x | SteeringWheelAngle_Th_y |
| LateralAcceleration_th | LateralAcceleration_th_x | LateralAcceleration_th_y |
| YawrateSuspension_Th | YawrateSuspension_Th_x | YawrateSuspension_Th_y |

Create a clean template with:

```bash
python -m precond_abort.cli mapping-template mapping_template.xlsx
```

The supplied `PrecondAndAbort.numbers` file is read directly; no Excel export is required. Its `swIntfc` tab uses the corrected MDF channels `rov/lateralAcceleration` and `rov/YawrateSuspension`. For compatibility with older workbooks, the former misspellings `rov/lateralAccceleration` and `rov/YawrateSuppression` are still accepted with a visible warning. A workbook that contains `swIntfc` is otherwise validated strictly.

## Analysis behavior

- One event is created for every `0 -> 1` transition of `abort_any_active_event`.
- Signal values use the latest available sample at or before the event timestamp.
- Signed motion signals are compared by magnitude against positive, speed-interpolated thresholds.
- Throttle signals and thresholds are not loaded or evaluated in this version.
- `throttleInc` and `maxThrottle` remain `No`.
- `others` is set when none of the four motion reasons is active.

## Excel output layout

The primary `Abort Analysis` worksheet uses a two-row header. `File Name`, `timestamp`, and `speed` are followed by grouped `actual`, `thd`, and `result` columns for steering-wheel angle, steering-wheel-angle speed, yaw rate, lateral acceleration, throttle increase, and maximum throttle. `others` is the final result-only column.

Motion `actual` values are the magnitudes used for threshold comparison. Signed measurements and other audit values remain available in `Event Details`. While throttle checking is disabled, throttle `actual` and `thd` cells remain blank and their results remain `No`.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```
