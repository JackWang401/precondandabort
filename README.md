# Precondition & Abort Analyzer

A Windows 11-compatible desktop HMI and command-line tool for classifying AEB abort events in MDF/MF4 measurements. The analyzer reads `swIntfc` and `calParam` from an Excel or Apple Numbers configuration workbook, retrieves the specified speed-dependent thresholds from JSON, identifies abort-event rising edges, and creates an auditable Excel report.

## What is implemented

- Direct `.numbers`, `.xlsx`, and `.xlsm` reading for `swIntfc` and `calParam`
- Calibration lookup from a required VCS CAL JSON and an optional SAFETY CAL JSON, with automatic X/Y binding and optional manual override
- Linear threshold interpolation with endpoint clamping
- A desktop HMI with two JSON selectors, multi-file MDF/MF4 selection, calibration curve visualization, live interpolation, progress, and event preview
- Case-insensitive `swIntfc` signal mapping with documented acronym aliases
- A warning-backed built-in mapping when the supplied workbook has no `swIntfc` sheet
- MDF/MF4 reading through `asammdf`
- Motion and `others` classification, with throttle checks enabled whenever SAFETY CAL is supplied
- A formatted Excel report with two-level `actual / thd / result` comparison groups, plus event, mapping, parameter, and run-detail sheets
- A CLI for repeatable single-file execution
- Windows 11 launch scripts, per-user settings under `%LOCALAPPDATA%`, high-DPI support, and standalone executable packaging

## Windows 11 quick start

The deployment scripts use 64-bit Python 3.12 from python.org. The standard installer must include the Python launcher, `pip`, and Tcl/Tk. Copy or clone the complete project folder to the Windows computer, then:

1. Double-click `setup_windows.bat` once. It creates `.venv` and installs the required packages.
2. Double-click `run_windows.bat` whenever you want to start the HMI.

The launcher works from paths containing spaces. The application stores remembered paths in `%LOCALAPPDATA%\PrecondAbortAnalyzer\state.json`, so its installation folder may be read-only. On Windows, the bundled `PrecondAndAbort.xlsx` workbook is preferred automatically; `.numbers` files remain supported without requiring the Apple Numbers application.

## Standalone Windows executable

To deploy the application to Windows 11 computers that do not have Python installed, build it on a Windows 11 machine:

1. Run `setup_windows.bat`.
2. Run `build_windows.bat`.
3. Distribute `dist\PrecondAbortAnalyzer.exe`.
4. Start the deployed application by double-clicking the executable.

The configuration workbook and Python runtime are embedded in this single executable. The generated executable is unsigned; sign it with your organization's code-signing certificate before broad managed deployment if required by your Windows security policy.

The repository's `Build Windows executable` GitHub Actions workflow also produces a downloadable `PrecondAbortAnalyzer-Windows-x64` artifact whenever packaging-related changes reach `main`, or when the workflow is started manually.

## Manual development installation

Python 3.10 or newer is required. The desktop HMI also requires a Python build with Tk support.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell equivalent:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run the HMI

```bash
source .venv/bin/activate
python run_app.py
```

On Windows, use `run_windows.bat` or run `.\.venv\Scripts\python.exe run_app.py` from PowerShell.

When the HMI starts, all motion and throttle calibratables are visible as placeholder rows. If no previous selection is available, a file-navigation dialog prompts you to locate the required **VCS CAL** JSON file. **SAFETY CAL** is optional and has its own **Browse** control. The application does not assume that either file is in the repository or another fixed location.

The application discovers numeric entries in VCS CAL. When SAFETY CAL is selected, it combines entries from both files, labels each source with its originating filename, and enables throttle checks. It reads each motion parameter and its X/Y entry names from the configuration workbook's `calParam` tab. Throttle parameters are resolved from the names listed in the throttle row of `swIntfc`. Select any calibratable row to preview its curve or constant value. You can choose different entries and select **Use selected X/Y** to override the automatic binding. Use `constant — no X axis` when the selected Y entry is scalar or all of its values are equal.

The **Measurement MDF/MF4 files** selector accepts one or more files in a single selection. Every selected file is analyzed with the same mapping and calibration bindings, and all events are written to one Excel report. The HMI preview and report retain the originating filename for each event. The report path is generated automatically in the measurement folder: `<measurement>_abort_analysis.xlsx` for one file or `combined_<count>_files_abort_analysis.xlsx` for a batch. Batch inputs must be in the same folder.

The HMI remembers the required and optional JSON files, every selected MDF/MF4 file, and the configuration workbook between launches. The output-report path is recalculated from the restored measurement location. On Windows, these selections are stored in `%LOCALAPPDATA%\PrecondAbortAnalyzer\state.json`. In a source checkout on other platforms, they remain in the ignored `.precond_abort_state.json` file beside `run_app.py`. Restored paths are considered before repository sample paths.

Pair validation rejects mismatched point counts and duplicate X values before the analysis starts. With only VCS CAL selected, throttle signals and parameters are not required. Selecting SAFETY CAL makes the throttle and AEB-deceleration-request signals, along with all three throttle parameters, mandatory for that run.

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

The following rows are required when SAFETY CAL is selected:

| acronym | modelLogger | cal_thd |
| --- | --- | --- |
| throttle | rov/PedalPosPro | PedalPosProIncrease_Th; PedalPosPro_Override; PedalPosPro_th |
| aeb_deceleration_request | ndas_di_status/activeSafety/outputs/AEB/accelerationRequest | |

They are optional when SAFETY CAL is absent.

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

The supplied `PrecondAndAbort.xlsx` file is the default on Windows 11. `PrecondAndAbort.numbers` can also be read directly without Apple Numbers. The `swIntfc` tab uses the corrected MDF channels `rov/lateralAcceleration` and `rov/YawrateSuspension`. For compatibility with older workbooks, the former misspellings `rov/lateralAccceleration` and `rov/YawrateSuppression` are still accepted with a visible warning. A workbook that contains `swIntfc` is otherwise validated strictly.

## Analysis behavior

- One event is created for every `0 -> 1` transition of `abort_any_active_event`.
- Signal values use the latest available sample at or before the event timestamp.
- Signed motion signals are compared by magnitude against positive, speed-interpolated thresholds.
- Without SAFETY CAL, throttle signals and thresholds are not loaded; `throttleInc` and `maxThrottle` remain `No`.
- With SAFETY CAL, throttle checks use `PedalPosProIncrease_Th`, `PedalPosPro_Override`, and `PedalPosPro_th`. The documented `LSB_Throttle_Override_Increase` and `LSB_Min_Throttle_Override` JSON aliases are accepted.
- An AEB deceleration request of `-6` or `-15` starts the throttle-increase baseline. The baseline remains applicable while the request is active and for 0.5 seconds after it ends.
- `throttleInc` is `Yes` when the current pedal position reaches the override threshold and its increase from the baseline reaches the increase threshold. `maxThrottle` is `Yes` when the pedal position reaches the speed-dependent maximum threshold.
- `others` is set when none of the applicable motion or throttle reasons is active.

## Excel output layout

The primary `Abort Analysis` worksheet uses a two-row header. `File Name`, `timestamp`, and `speed` are followed by grouped `actual`, `thd`, and `result` columns for steering-wheel angle, steering-wheel-angle speed, yaw rate, lateral acceleration, throttle increase, and maximum throttle. `others` is the final result-only column.

Motion `actual` values are the magnitudes used for threshold comparison. Signed measurements and other audit values remain available in `Event Details`. When SAFETY CAL is absent, throttle `actual` and `thd` cells remain blank and their results remain `No`. When it is present, those columns contain the calculated throttle values, thresholds, and results.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Windows command prompt equivalent:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
