# Precondition and Abort Analyzer Requirements

## 1. Human-machine interface (HMI)

1. The HMI shall provide controls for loading:
   - one required calibration JSON file labeled `VCS CAL`;
   - one optional calibration JSON file labeled `SAFETY CAL`;
   - one or more MDF/MF4 measurement files;
   - a configuration workbook in Apple Numbers (`.numbers`) or Excel (`.xlsx` or `.xlsm`) format; and
   - the automatically generated output Excel report path.
2. The HMI shall not assume that either calibration JSON file is stored in a fixed location. When the HMI starts without a restored `VCS CAL` path, it shall open a file-navigation dialog that allows the user to locate that required file. Separate `Browse` controls shall remain available for `VCS CAL` and `SAFETY CAL`.
3. Before `VCS CAL` is loaded, the HMI shall display placeholder rows for the four motion calibratables and the three throttle calibratables: throttle increase, throttle override, and maximum throttle.
4. After `VCS CAL` is loaded, the software shall discover every numeric JSON entry that can be used as calibration data. If `SAFETY CAL` is also loaded, the software shall combine the entries from both files while retaining each entry's originating filename.
5. The `calParam` tab in the configuration workbook shall supply the parameter name and the exact JSON entry names to use as X and Y for every active motion or throttle calibratable.
6. After the configuration workbook and calibration JSON files are loaded, the HMI shall automatically retrieve and bind each applicable X/Y pair specified by `calParam`. When `SAFETY CAL` is present, X and Y may originate from different selected JSON files. The HMI shall continue to allow the user to select a different X or Y entry explicitly.
7. The HMI shall provide a `constant — no X axis` option for scalar Y entries and arrays whose Y values are all equal.
8. Before accepting a selected pair, the software shall verify that X and Y contain the same number of numeric values and that X contains no duplicate values.
9. The analyzer shall use the accepted X/Y binding for its specific calibratable. It shall not silently replace an HMI selection with a predefined parameter.
10. The HMI shall visualize the accepted X/Y pair using the useful features of the existing `cal_thd_intp` tool. At a minimum, it shall display the curve, its breakpoints, units, and the interpolated threshold at a user-specified vehicle speed.
11. The HMI shall display validation messages, analysis progress, the current enabled or disabled state of the throttle checks, and a preview of the detected abort events.
12. The MDF/MF4 `Browse` control shall allow the user to select multiple measurement files. The software shall analyze every selected file and combine the detected events into one output report while retaining the originating filename for each event.
13. The HMI shall remember the required and optional calibration JSON paths, all selected MDF/MF4 paths, and the configuration-workbook path between launches. Restored paths shall take precedence over repository sample-file defaults. The output-report path shall be recalculated from the restored measurement location.

## 2. Signal mapping

1. The software shall read signal definitions from the `swIntfc` tab in the selected configuration workbook. It shall support both `PrecondAndAbort.numbers` and an equivalent Excel export.
2. In `swIntfc`:
   - `modelLogger` contains the signal name used in the MDF/MF4 file;
   - `acronym` contains the logical name used by the software; and
   - `cal_thd` contains the calibration parameter to compare with that signal, when applicable.
3. When `SAFETY CAL` is absent, the analysis requires the following logical signals:
   - vehicle speed;
   - steering-wheel angle;
   - steering-wheel-angle rate;
   - yaw rate;
   - lateral acceleration;
   - and `abort_any_active_event`.
4. When `SAFETY CAL` is present, accelerator-pedal position and `aeb_deceleration_request` shall also be required, and throttle checks shall be enabled.
5. Signal and column-name matching shall be case-insensitive. The supplied workbook shall use the MDF channels `rov/lateralAcceleration` and `rov/YawrateSuspension`. For compatibility with older workbooks, the former misspellings `rov/lateralAccceleration` and `rov/YawrateSuppression` shall resolve to the corrected channels with a visible warning.
6. If `swIntfc` is absent, the software may use its documented built-in mapping for the supplied model-logger signals. It shall display a warning whenever this fallback is used.
7. If `swIntfc` exists but is incomplete or invalid for the selected analysis mode, the software shall stop and report the missing or invalid entries.

## 3. Calibration thresholds

1. The `calParam` tab shall contain one row per parameter and the columns `x` and `y`. The column preceding `x` contains the parameter name, `x` contains the exact JSON X-entry name, and `y` contains the exact JSON Y-entry name.
2. The `cal_thd` value on each motion row in `swIntfc` identifies the parameter row to use from `calParam`. The three throttle parameters are identified by their `calParam` parameter names.
3. The active motion thresholds are:
   - `SteeringWheelAngle_Th` for steering-wheel angle;
   - `AEB_SteeringAngleRate_Override` for steering-wheel-angle rate;
   - `YawrateSuspension_Th` for yaw rate; and
   - `LateralAcceleration_th` for lateral acceleration.
4. When `SAFETY CAL` is present, the software shall load the X/Y pairs specified by the `calParam` rows for `PedalPosProIncrease_Th`, `PedalPosPro_Override`, and `PedalPosPro_th`. Each entry may come from either selected JSON file. The documented JSON aliases `LSB_Throttle_Override_Increase` and `LSB_Min_Throttle_Override` shall remain available for automatic parameter lookup when no explicit X/Y binding is supplied.
5. Curve-based thresholds shall be linearly interpolated against vehicle speed. Values outside the curve's domain shall use the nearest endpoint.
6. Scalar parameters, and arrays whose entries are all equal, shall be treated as constant thresholds.
7. Explicit X/Y bindings selected in the HMI shall take precedence over the entries loaded from `calParam`.

## 4. Data-analysis process

1. The software shall identify each timestamp at which `abort_any_active_event` changes from inactive to active (`0 -> 1`). Each transition represents one abort event.
2. When multiple MDF/MF4 files are selected, the software shall apply the same accepted mapping and calibration bindings to each file and combine the results.
3. At each abort timestamp, the software shall obtain the corresponding signal values and calculate all applicable thresholds for the current vehicle speed.
4. The software shall always compare the following signal/threshold pairs:
   - steering-wheel angle;
   - steering-wheel-angle rate;
   - yaw rate; and
   - lateral acceleration.
5. A motion reason is active when the magnitude of its signal is greater than or equal to its threshold. Every active reason shall be recorded; reasons are not mutually exclusive.
6. The software shall not read throttle signals, resolve throttle parameters, or evaluate `throttleInc` or `maxThrottle` when `SAFETY CAL` is absent.
7. When `SAFETY CAL` is present, the software shall treat an `aeb_deceleration_request` value of `-6` or `-15` as an AEB intervention. For each abort event, it shall use the most recent intervention start that is still active or ended no more than 0.5 seconds before the abort timestamp.
8. The throttle-increase value shall equal the pedal position at the abort timestamp minus the pedal position at the applicable intervention start. `throttleInc` shall be active when the increase is greater than `PedalPosProIncrease_Th` and the magnitude of the current pedal position is greater than `PedalPosPro_Override`.
9. `maxThrottle` shall be active when the magnitude of the current pedal position is greater than the speed-interpolated `PedalPosPro_th` threshold. The enabled throttle reason is therefore `(throttle increase > PedalPosProIncrease_Th AND absolute throttle > PedalPosPro_Override) OR absolute throttle > PedalPosPro_th`.
10. If no motion or enabled throttle reason is active, the software shall mark the reason as `others`.

## 5. Excel output

1. The primary output worksheet shall contain one row per abort event.
2. The first three columns shall be `File Name`, `timestamp`, and `speed`. Their headers shall span both header rows.
3. The following comparison groups shall appear after `speed`:
   - `steering wheel angle`;
   - `steering wheel angle speed`;
   - `yaw rate`;
   - `lateral acceleration`;
   - `throttle increase`; and
   - `maximum throttle`.
4. Each comparison group shall span three subcolumns named `actual`, `thd`, and `result`.
5. The `others` column shall follow the comparison groups and shall span both header rows because it has no measured value or threshold.
6. Motion `actual` values shall contain the magnitudes used by the comparison. Signed raw values shall remain available in the audit details.
7. While throttle checking is disabled, the throttle `actual` and `thd` cells shall remain blank and their `result` cells shall contain `No`.
8. Every `result` cell and the `others` cell shall contain `Yes` or `No`.
9. The report shall include sufficient audit detail to show the signed motion-signal values, calculated thresholds, throttle-check state, and resolved abort reason for each event.
10. The report shall also record the signal mapping, the originating `calParam` row, and the exact X and Y JSON sources used for every active threshold.
11. The workbook shall be formatted for readability. The primary worksheet shall freeze its two header rows and first three columns; applicable audit tables shall include filters and frozen headers.
12. The run-information worksheet shall list every MDF/MF4 file included in a batch report.
13. The output workbook shall be saved in the same folder as the input MDF/MF4 file. When multiple files are selected, they shall be in one shared folder, and the combined report shall be saved in that folder.

## 6. Validation and error handling

1. The software shall reject files with unsupported extensions or unreadable content.
2. Before analysis, it shall report all missing required signals, `calParam` rows, and JSON X/Y entries in one actionable error message whenever possible. Missing throttle data shall not block analysis when `SAFETY CAL` is absent, but it shall block analysis when `SAFETY CAL` is present.
3. Empty signals, invalid calibration curves, nonnumeric required data, and mismatched `_x`/`_y` arrays shall produce clear validation errors. One-dimensional JSON arrays may be encoded directly, as one nested row, or as one nested column.
4. A failed analysis shall not create or overwrite a misleading output report.

## 7. Windows 11 deployment

1. The HMI shall support 64-bit Windows 11. The supported source runtime shall be Python 3.10 or newer, and the standard Windows deployment scripts shall use Python 3.12 with Tcl/Tk.
2. On Windows, the HMI shall store remembered paths under `%LOCALAPPDATA%\PrecondAbortAnalyzer` rather than in the application directory.
3. The Windows HMI shall prefer `PrecondAndAbort.xlsx` as its default configuration workbook while continuing to accept `.xlsx`, `.xlsm`, and `.numbers` files selected by the user.
4. The Windows file-navigation dialogs shall provide compatible filters for JSON, MDF/MF4, and configuration-workbook files.
5. The Windows HMI shall request DPI-aware rendering so that controls remain legible on scaled displays.
6. The project shall provide scripts for installing dependencies, launching from a local virtual environment, and building a single-file Windows executable.
7. A standalone build shall store mutable state in the user's profile and shall not require write access to its installation directory. Analysis reports shall continue to be written beside the selected MDF/MF4 input files.
8. The repository shall provide a Windows CI workflow that runs the automated tests, builds the executable, calculates its SHA-256 checksum, and publishes both files as a downloadable build artifact.
