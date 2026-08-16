# Precondition and Abort Analyzer Requirements

## 1. Human-machine interface (HMI)

1. The HMI shall provide controls for loading:
   - a calibration JSON file;
   - an MDF/MF4 measurement file;
   - a configuration workbook in Apple Numbers (`.numbers`) or Excel (`.xlsx` or `.xlsm`) format; and
   - the output Excel report path.
2. The HMI shall not assume that the calibration JSON file is stored in a fixed location. When the HMI starts, it shall open a file-navigation dialog that allows the user to locate the JSON file. The same dialog shall remain available through the JSON `Browse` control.
3. Before a calibration JSON file is loaded, the HMI shall display placeholder rows for the four active motion calibratables: steering-wheel angle, steering-wheel-angle speed, yaw rate, and lateral acceleration.
4. After a calibration JSON file is loaded, the software shall discover every numeric JSON entry that can be used as calibration data.
5. The `calParam` tab in the configuration workbook shall supply the parameter name and the exact JSON entry names to use as X and Y for each motion calibratable.
6. After both the configuration workbook and JSON file are loaded, the HMI shall automatically retrieve and bind each motion X/Y pair specified by `calParam`. The HMI shall continue to allow the user to select a different X or Y entry explicitly.
7. The HMI shall provide a `constant — no X axis` option for scalar Y entries and arrays whose Y values are all equal.
8. Before accepting a selected pair, the software shall verify that X and Y contain the same number of numeric values and that X contains no duplicate values.
9. The analyzer shall use the accepted X/Y binding for its specific calibratable. It shall not silently replace an HMI selection with a predefined parameter.
10. The HMI shall visualize the accepted X/Y pair using the useful features of the existing `cal_thd_intp` tool. At a minimum, it shall display the curve, its breakpoints, units, and the interpolated threshold at a user-specified vehicle speed.
11. The HMI shall display validation messages, analysis progress, a visible notice that throttle checks are disabled, and a preview of the detected abort events.

## 2. Signal mapping

1. The software shall read signal definitions from the `swIntfc` tab in the selected configuration workbook. It shall support both `PrecondAndAbort.numbers` and an equivalent Excel export.
2. In `swIntfc`:
   - `modelLogger` contains the signal name used in the MDF/MF4 file;
   - `acronym` contains the logical name used by the software; and
   - `cal_thd` contains the calibration parameter to compare with that signal, when applicable.
3. While throttle checking is disabled, the analysis requires the following logical signals:
   - vehicle speed;
   - steering-wheel angle;
   - steering-wheel-angle rate;
   - yaw rate;
   - lateral acceleration;
   - and `abort_any_active_event`.
4. Accelerator-pedal position and `aeb_deceleration_request` are optional until throttle checking is restored.
5. Signal and column-name matching shall be case-insensitive and shall accept the documented aliases used by the supplied model-logger data. The known workbook spellings `rov/lateralAccceleration` and `rov/YawrateSuppression` shall resolve to the supplied MDF channels `rov/lateralAcceleration` and `rov/YawrateSuspension`, respectively, with a visible warning.
6. If `swIntfc` is absent, the software may use its documented built-in mapping for the supplied model-logger signals. It shall display a warning whenever this fallback is used.
7. If `swIntfc` exists but is incomplete or invalid for the active motion analysis, the software shall stop and report the missing or invalid entries.

## 3. Calibration thresholds

1. The `calParam` tab shall contain one row per parameter and the columns `x` and `y`. The column preceding `x` contains the parameter name, `x` contains the exact JSON X-entry name, and `y` contains the exact JSON Y-entry name.
2. The `cal_thd` value on each applicable `swIntfc` row identifies the parameter row to use from `calParam`.
3. The active motion thresholds are:
   - `SteeringWheelAngle_Th` for steering-wheel angle;
   - `AEB_SteeringAngleRate_Override` for steering-wheel-angle rate;
   - `YawrateSuspension_Th` for yaw rate; and
   - `LateralAcceleration_th` for lateral acceleration.
4. Throttle calibrations and throttle classification shall be skipped until `calParam` contains the complete required throttle parameter set, including the missing throttle-increase pair.
5. Curve-based thresholds shall be linearly interpolated against vehicle speed. Values outside the curve's domain shall use the nearest endpoint.
6. Scalar parameters, and arrays whose entries are all equal, shall be treated as constant thresholds.
7. Explicit X/Y bindings selected in the HMI shall take precedence over the entries loaded from `calParam`.

## 4. Data-analysis process

1. The software shall identify each timestamp at which `abort_any_active_event` changes from inactive to active (`0 -> 1`). Each transition represents one abort event.
2. At each abort timestamp, the software shall obtain the corresponding signal values and calculate all applicable thresholds for the current vehicle speed.
3. The software shall compare the following signal/threshold pairs:
   - steering-wheel angle;
   - steering-wheel-angle rate;
   - yaw rate; and
   - lateral acceleration.
4. A motion reason is active when the magnitude of its signal is greater than or equal to its threshold. Every active reason shall be recorded; reasons are not mutually exclusive.
5. The software shall not read throttle signals, resolve throttle parameters, or evaluate `throttleInc` or `maxThrottle` while throttle checking is disabled.
6. If none of the four motion reasons is active, the software shall mark the reason as `others`.

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
8. Every motion `result` cell and the `others` cell shall contain `Yes` or `No`.
9. The report shall include sufficient audit detail to show the signed motion-signal values, calculated motion thresholds, disabled throttle state, and resolved abort reason for each event.
10. The report shall also record the signal mapping, the originating `calParam` row, and the exact X and Y JSON sources used for every active motion threshold.
11. The workbook shall be formatted for readability. The primary worksheet shall freeze its two header rows and first three columns; applicable audit tables shall include filters and frozen headers.

## 6. Validation and error handling

1. The software shall reject files with unsupported extensions or unreadable content.
2. Before analysis, it shall report all missing motion signals, `calParam` rows, and JSON X/Y entries in one actionable error message whenever possible. Missing throttle data shall not block analysis while throttle checking is disabled.
3. Empty signals, invalid calibration curves, nonnumeric required data, and mismatched `_x`/`_y` arrays shall produce clear validation errors.
4. A failed analysis shall not create or overwrite a misleading output report.
