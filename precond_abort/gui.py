from __future__ import annotations

import json
import os
import queue
import sys
import threading
from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .analyzer import AbortAnalyzer, combine_analysis_results
from .calibration import CalibrationRepository
from .errors import InputValidationError, PrecondAbortError
from .mapping import load_calibration_specs, load_mapping, match_motion_calibration_specs
from .mdf_reader import MDFSignalSource
from .models import AnalysisResult, CalibrationBindingSpec, CalibrationParameter
from .report import OUTPUT_PREVIEW_HEADERS, OUTPUT_REASON_FLAGS, write_report


BG = "#F3F6F8"
CARD = "#FFFFFF"
NAVY = "#17324D"
TEAL = "#197C83"
MUTED = "#5E7282"
LINE = "#D7E0E6"
WARNING = "#9A5B00"
CONSTANT_X_OPTION = "(constant — no X axis)"
LOAD_CONFIG_PLACEHOLDER = "Load calParam first"
VCS_CAL_LABEL = "VCS CAL"
SAFETY_CAL_LABEL = "SAFETY CAL"
PATH_STATE_VERSION = 1
APPLICATION_NAME = "PrecondAbortAnalyzer"


def default_path_state_path(
    platform_name: str | None = None,
    environment: dict[str, str] | None = None,
    home_directory: str | Path | None = None,
) -> Path:
    """Return a writable per-user state path for the current platform."""

    active_platform = platform_name or os.name
    if active_platform == "nt":
        active_environment = os.environ if environment is None else environment
        local_app_data = active_environment.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            base = Path(local_app_data)
        else:
            home = Path(home_directory) if home_directory is not None else Path.home()
            base = home / "AppData" / "Local"
        return base / APPLICATION_NAME / "state.json"
    return Path(__file__).resolve().parent.parent / ".precond_abort_state.json"


def application_resource_directory() -> Path:
    """Return the source or PyInstaller resource directory."""

    bundled_directory = getattr(sys, "_MEIPASS", None)
    if bundled_directory:
        return Path(bundled_directory)
    return Path(__file__).resolve().parent.parent


def default_mapping_workbook(
    directories: tuple[Path, ...],
    platform_name: str | None = None,
) -> Path | None:
    """Find the bundled/sample workbook, preferring Excel on Windows."""

    active_platform = platform_name or os.name
    filenames = (
        ("PrecondAndAbort.xlsx", "PrecondAndAbort.xlsm", "PrecondAndAbort.numbers")
        if active_platform == "nt"
        else ("PrecondAndAbort.numbers", "PrecondAndAbort.xlsx", "PrecondAndAbort.xlsm")
    )
    resolved_directories = tuple(
        dict.fromkeys(path.resolve() for path in directories)
    )
    for filename in filenames:
        for directory in resolved_directories:
            candidate = directory / filename
            if candidate.exists():
                return candidate
    return None


def enable_windows_dpi_awareness(platform_name: str | None = None) -> bool:
    """Ask Windows to render Tk controls sharply on high-DPI displays."""

    if (platform_name or os.name) != "nt":
        return False
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        return False
    return True


PATH_STATE_PATH = default_path_state_path()

THRESHOLD_BINDING_SPECS = (
    ("steering_wheel_angle", "Steering wheel angle", "SteeringWheelAngle_Th"),
    ("steering_wheel_angle_rate", "Steering wheel angle speed", "AEB_SteeringAngleRate_Override"),
    ("yaw_rate", "Yaw rate", "YawrateSuspension_Th"),
    ("lateral_acceleration", "Lateral acceleration", "LateralAcceleration_th"),
    ("throttle_increase", "Throttle increase", "PedalPosProIncrease_Th"),
    ("throttle_override", "Throttle override", "PedalPosPro_Override"),
    ("throttle_max", "Maximum throttle", "PedalPosPro_th"),
)
MOTION_BINDING_ROLES = tuple(role for role, _, _ in THRESHOLD_BINDING_SPECS[:4])
THROTTLE_BINDING_ROLES = tuple(role for role, _, _ in THRESHOLD_BINDING_SPECS[4:])
ROLE_BY_LABEL = {label: role for role, label, _ in THRESHOLD_BINDING_SPECS}
LABEL_BY_ROLE = {role: label for role, label, _ in THRESHOLD_BINDING_SPECS}
DEFAULT_PARAMETER_NAME_BY_ROLE = {role: parameter for role, _, parameter in THRESHOLD_BINDING_SPECS}


def initial_binding_row(label: str) -> tuple[str, str, str, str]:
    return (label, LOAD_CONFIG_PLACEHOLDER, LOAD_CONFIG_PLACEHOLDER, "Waiting")


def selected_calibration_paths(vcs_cal: str, safety_cal: str = "") -> tuple[str, ...]:
    """Return the mandatory VCS CAL and the optional SAFETY CAL, when supplied."""

    if not vcs_cal.strip():
        return ()
    paths = [str(Path(vcs_cal).expanduser().resolve())]
    if safety_cal.strip():
        paths.append(str(Path(safety_cal).expanduser().resolve()))
    return tuple(paths)


def with_json_provenance(
    parameter: CalibrationParameter,
    json_path: str | Path,
) -> CalibrationParameter:
    """Add the selected JSON filename to an automatically resolved binding."""

    label = Path(json_path).name

    def scoped(source: str) -> str:
        return f"{label}::{source}" if source else ""

    return replace(
        parameter,
        source=f"{parameter.source} [{label}]",
        x_source=scoped(parameter.x_source),
        y_source=scoped(parameter.y_source),
    )


def analysis_output_path(measurement_paths: tuple[str, ...]) -> Path:
    if not measurement_paths:
        raise InputValidationError("Select at least one MDF/MF4 measurement file")
    measurements = tuple(
        Path(path).expanduser().resolve() for path in measurement_paths
    )
    parent_directories = {path.parent for path in measurements}
    if len(parent_directories) != 1:
        raise InputValidationError(
            "All selected MDF/MF4 files must be in the same folder so the combined "
            "report can be saved beside them"
        )
    if len(measurements) == 1:
        filename = f"{measurements[0].stem}_abort_analysis.xlsx"
    else:
        filename = f"combined_{len(measurements)}_files_abort_analysis.xlsx"
    return measurements[0].parent / filename


def read_path_state(path: str | Path | None = None) -> dict[str, object]:
    state_path = Path(path) if path is not None else PATH_STATE_PATH
    if not state_path.exists():
        return {}
    try:
        document = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"Cannot read saved HMI paths from {state_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise InputValidationError(f"Saved HMI paths in {state_path} must be a JSON object")

    def text_value(key: str) -> str:
        value = document.get(key, "")
        return value if isinstance(value, str) else ""

    measurements = document.get("measurement_files", [])
    if not isinstance(measurements, list):
        measurements = []
    return {
        "version": document.get("version", PATH_STATE_VERSION),
        "calibration_json_1": text_value("calibration_json_1"),
        "calibration_json_2": text_value("calibration_json_2"),
        "measurement_files": [value for value in measurements if isinstance(value, str)],
        "mapping_workbook": text_value("mapping_workbook"),
        "output_report": text_value("output_report"),
    }


def write_path_state(state: dict[str, object], path: str | Path | None = None) -> Path:
    state_path = Path(path) if path is not None else PATH_STATE_PATH
    temporary = state_path.with_name(f"{state_path.name}.tmp")
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(state_path)
    except OSError as exc:
        if temporary.exists():
            temporary.unlink()
        raise InputValidationError(f"Cannot save HMI paths to {state_path}: {exc}") from exc
    return state_path


class AnalyzerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Precondition & Abort Analyzer")
        self.root.geometry("1320x850")
        self.root.minsize(1080, 720)
        self.root.configure(background=BG)

        self.calibration_path_1 = tk.StringVar()
        self.calibration_path_2 = tk.StringVar()
        self.measurement_path = tk.StringVar()
        self.mapping_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.threshold_role = tk.StringVar(value=THRESHOLD_BINDING_SPECS[0][1])
        self.x_entry_selection = tk.StringVar()
        self.y_entry_selection = tk.StringVar()
        self.interpolation_speed = tk.StringVar(value="50")
        self.status = tk.StringVar(value="Ready — select the input files to begin")
        self.mapping_status = tk.StringVar(value="Mapping not loaded")
        self.throttle_status = tk.StringVar(
            value=f"{SAFETY_CAL_LABEL} is optional; throttle checks are disabled."
        )
        self.parameter_value = tk.StringVar(value="Select a calibration parameter")
        self._calibrations: CalibrationRepository | None = None
        self._vcs_calibrations: CalibrationRepository | None = None
        self._safety_calibrations: CalibrationRepository | None = None
        self._loaded_calibration_paths: tuple[str, ...] | None = None
        self._measurement_paths: tuple[str, ...] = ()
        self._entry_by_display = {}
        self._display_by_source: dict[str, str] = {}
        self._calibration_specs: dict[str, CalibrationBindingSpec] = {}
        self._calibration_bindings: dict[str, CalibrationParameter] = {}
        self._analysis_overrides: dict[str, CalibrationParameter] = {}
        self._analysis_calibration_paths: tuple[str, ...] = ()
        self._analysis_throttle_checks_enabled = False
        self._analysis_measurement_paths: tuple[str, ...] = ()
        self._analysis_mapping_path = ""
        self._analysis_output_path = ""
        self._worker_messages: queue.Queue = queue.Queue()
        self._result: AnalysisResult | None = None

        self._configure_style()
        self._build_ui()
        self._restore_path_state()
        self._populate_sample_paths()
        self._load_initial_inputs()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._poll_worker)
        self.root.after(250, self._prompt_for_calibration)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD, relief="flat")
        style.configure("Header.TLabel", background=NAVY, foreground="white", font=("Aptos Display", 22, "bold"))
        style.configure("HeaderSub.TLabel", background=NAVY, foreground="#DCE9EE", font=("Aptos", 10))
        style.configure("Section.TLabel", background=CARD, foreground=NAVY, font=("Aptos", 12, "bold"))
        style.configure("Body.TLabel", background=CARD, foreground="#24333F", font=("Aptos", 10))
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Aptos", 9))
        style.configure("Warning.TLabel", background=CARD, foreground=WARNING, font=("Aptos", 9))
        style.configure("Primary.TButton", background=TEAL, foreground="white", font=("Aptos", 10, "bold"), padding=(18, 10))
        style.map("Primary.TButton", background=[("active", "#126B71"), ("disabled", "#9EB6B8")])
        style.configure("Secondary.TButton", background="#E8F0F3", foreground=NAVY, padding=(11, 7))
        style.map("Secondary.TButton", background=[("active", "#DCE8EC")])
        style.configure("Treeview", rowheight=28, font=("Aptos", 9), background=CARD, fieldbackground=CARD)
        style.configure("Treeview.Heading", background=NAVY, foreground="white", font=("Aptos", 9, "bold"), padding=(5, 8))
        style.map("Treeview.Heading", background=[("active", "#244760")])

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=NAVY, height=84)
        header.pack(fill="x")
        header.pack_propagate(False)
        ttk.Label(header, text="Precondition & Abort Analyzer", style="Header.TLabel").pack(anchor="w", padx=26, pady=(15, 0))
        ttk.Label(
            header,
            text="Load motion thresholds from calParam, classify AEB abort events, and export an auditable Excel report.",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", padx=27, pady=(2, 0))

        main = ttk.Frame(self.root, padding=18)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=4)
        main.columnconfigure(1, weight=5)
        main.rowconfigure(1, weight=1)

        files = ttk.Frame(main, style="Card.TFrame", padding=16)
        files.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        files.columnconfigure(1, weight=1)
        ttk.Label(files, text="1  Input files", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._file_row(files, 1, f"{VCS_CAL_LABEL} (required)", self.calibration_path_1, "json_1")
        self._file_row(files, 2, f"{SAFETY_CAL_LABEL} (optional)", self.calibration_path_2, "json_2")
        self._file_row(files, 3, "Measurement MDF/MF4 files", self.measurement_path, "mdf", readonly=True)
        self._file_row(files, 4, "Configuration workbook", self.mapping_path, "mapping")
        self._file_row(
            files,
            5,
            "Output Excel report",
            self.output_path,
            "output",
            readonly=True,
            browse=False,
        )
        ttk.Label(files, textvariable=self.mapping_status, style="Warning.TLabel").grid(
            row=6, column=1, columnspan=2, sticky="w", pady=(5, 0)
        )

        explorer = ttk.Frame(main, style="Card.TFrame", padding=16)
        explorer.grid(row=1, column=0, sticky="nsew", padx=(0, 7))
        explorer.columnconfigure(0, weight=1)
        explorer.rowconfigure(5, weight=1)
        ttk.Label(explorer, text="2  Calibration explorer", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            explorer,
            textvariable=self.throttle_status,
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 9))

        binding_columns = ("calibratable", "x_entry", "y_entry", "status")
        self.binding_tree = ttk.Treeview(
            explorer,
            columns=binding_columns,
            show="headings",
            height=len(THRESHOLD_BINDING_SPECS),
            selectmode="browse",
        )
        for column, heading, width in (
            ("calibratable", "Calibratable", 176),
            ("x_entry", "X entry", 138),
            ("y_entry", "Y entry", 138),
            ("status", "Status", 90),
        ):
            self.binding_tree.heading(column, text=heading)
            self.binding_tree.column(column, width=width, minwidth=75, stretch=True)
        for role, label, _ in THRESHOLD_BINDING_SPECS:
            self.binding_tree.insert(
                "",
                "end",
                iid=role,
                values=initial_binding_row(label),
            )
        first_role = THRESHOLD_BINDING_SPECS[0][0]
        self.binding_tree.selection_set(first_role)
        self.binding_tree.focus(first_role)
        self.binding_tree.bind("<<TreeviewSelect>>", self._on_binding_row_selected)
        self.binding_tree.grid(row=2, column=0, sticky="ew")

        binding_grid = ttk.Frame(explorer, style="Card.TFrame")
        binding_grid.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        binding_grid.columnconfigure(1, weight=1)
        ttk.Label(binding_grid, textvariable=self.threshold_role, style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(binding_grid, text="X entry", style="Body.TLabel", width=12).grid(row=1, column=0, sticky="w", pady=2)
        self.x_entry_box = ttk.Combobox(binding_grid, textvariable=self.x_entry_selection, state="readonly")
        self.x_entry_box.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(binding_grid, text="Y entry", style="Body.TLabel", width=12).grid(row=2, column=0, sticky="w", pady=2)
        self.y_entry_box = ttk.Combobox(binding_grid, textvariable=self.y_entry_selection, state="readonly")
        self.y_entry_box.grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Button(
            binding_grid,
            text="Use selected X/Y",
            style="Secondary.TButton",
            command=self._apply_selected_binding,
        ).grid(row=3, column=1, sticky="e", pady=(5, 0))

        speed_row = ttk.Frame(explorer, style="Card.TFrame")
        speed_row.grid(row=4, column=0, sticky="ew", pady=9)
        ttk.Label(speed_row, text="Vehicle speed", style="Body.TLabel").pack(side="left")
        speed_entry = ttk.Entry(speed_row, textvariable=self.interpolation_speed, width=10)
        speed_entry.pack(side="left", padx=(8, 4))
        speed_entry.bind("<Return>", lambda _event: self._draw_selected_parameter())
        ttk.Label(speed_row, text="km/h", style="Muted.TLabel").pack(side="left")
        ttk.Button(speed_row, text="Interpolate", style="Secondary.TButton", command=self._draw_selected_parameter).pack(side="right")
        self.curve_canvas = tk.Canvas(explorer, background="#F8FAFB", highlightthickness=1, highlightbackground=LINE)
        self.curve_canvas.grid(row=5, column=0, sticky="nsew")
        self.curve_canvas.bind("<Configure>", lambda _event: self._draw_selected_parameter())
        ttk.Label(explorer, textvariable=self.parameter_value, style="Body.TLabel", wraplength=480).grid(
            row=6, column=0, sticky="w", pady=(9, 0)
        )

        analysis = ttk.Frame(main, style="Card.TFrame", padding=16)
        analysis.grid(row=1, column=1, sticky="nsew", padx=(7, 0))
        analysis.columnconfigure(0, weight=1)
        analysis.rowconfigure(3, weight=1)
        title_row = ttk.Frame(analysis, style="Card.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.columnconfigure(0, weight=1)
        ttk.Label(title_row, text="3  Abort analysis", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(title_row, text="Run analysis", style="Primary.TButton", command=self._run_analysis)
        self.run_button.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(title_row, textvariable=self.status, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.progress = ttk.Progressbar(analysis, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        self.summary = ttk.Label(analysis, text="No results yet", style="Body.TLabel")
        self.summary.grid(row=2, column=0, sticky="w", pady=(0, 8))

        tree_frame = ttk.Frame(analysis, style="Card.TFrame")
        tree_frame.grid(row=3, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(tree_frame, columns=OUTPUT_PREVIEW_HEADERS, show="headings")
        for heading in OUTPUT_PREVIEW_HEADERS:
            if heading == "File Name":
                width = 180
            elif heading == "timestamp":
                width = 108
            elif heading == "speed" or heading == "others":
                width = 76
            elif heading.endswith("result"):
                width = 88
            else:
                width = 106
            self.results_tree.heading(heading, text=heading)
            self.results_tree.column(heading, width=width, minwidth=70, anchor="center", stretch=True)
        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.results_tree.yview)
        x_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.results_tree.xview)
        self.results_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

    def _file_row(
        self,
        parent,
        row: int,
        label: str,
        variable: tk.StringVar,
        kind: str,
        readonly: bool = False,
        browse: bool = True,
    ) -> None:
        ttk.Label(parent, text=label, style="Body.TLabel", width=24).grid(row=row, column=0, sticky="w", pady=3)
        entry = ttk.Entry(parent, textvariable=variable, state="readonly" if readonly else "normal")
        entry.grid(row=row, column=1, sticky="ew", padx=(6, 8), pady=3)
        if not readonly:
            entry.bind("<FocusOut>", lambda _event: self._save_path_state())
            entry.bind("<Return>", lambda _event: self._save_path_state())
        if browse:
            ttk.Button(parent, text="Browse", style="Secondary.TButton", command=lambda: self._browse(kind)).grid(
                row=row, column=2, pady=3
            )
        else:
            ttk.Label(parent, text="Automatic", style="Muted.TLabel").grid(
                row=row, column=2, padx=(4, 7), pady=3
            )

    def _restore_path_state(self) -> None:
        try:
            state = read_path_state()
        except InputValidationError as exc:
            self.mapping_status.set(str(exc))
            return
        if not state:
            return
        vcs_cal = str(state["calibration_json_1"])
        safety_cal = str(state["calibration_json_2"])
        self.calibration_path_1.set(vcs_cal)
        # Earlier versions required two files, so the same file was sometimes
        # saved in both fields. Treat that legacy state as no optional Safety CAL.
        if vcs_cal and safety_cal and Path(vcs_cal).expanduser() == Path(safety_cal).expanduser():
            safety_cal = ""
        self.calibration_path_2.set(safety_cal)
        measurement_files = tuple(str(value) for value in state["measurement_files"])
        if measurement_files:
            self._set_measurement_paths(measurement_files)
        self.mapping_path.set(str(state["mapping_workbook"]))
        saved_output = str(state["output_report"])
        if saved_output and not measurement_files:
            self.output_path.set(saved_output)
        self.status.set("Restored the previous file selections")

    def _save_path_state(self) -> bool:
        state = {
            "version": PATH_STATE_VERSION,
            "calibration_json_1": self.calibration_path_1.get().strip(),
            "calibration_json_2": self.calibration_path_2.get().strip(),
            "measurement_files": list(self._measurement_paths),
            "mapping_workbook": self.mapping_path.get().strip(),
            "output_report": self.output_path.get().strip(),
        }
        try:
            write_path_state(state)
        except InputValidationError as exc:
            self.mapping_status.set(str(exc))
            return False
        return True

    def _close(self) -> None:
        self._save_path_state()
        self.root.destroy()

    def _populate_sample_paths(self) -> None:
        cwd = Path.cwd()
        mdf_files = sorted((*cwd.glob("*.mf4"), *cwd.glob("*.mdf")))
        workbook = default_mapping_workbook(
            (cwd, application_resource_directory())
        )
        if mdf_files and not self._measurement_paths:
            self._set_measurement_paths(tuple(str(path) for path in mdf_files))
        if workbook is not None and not self.mapping_path.get().strip():
            self.mapping_path.set(str(workbook))

    def _load_initial_inputs(self) -> None:
        if self.mapping_path.get().strip():
            self._load_mapping_status()
        if self._selected_calibration_paths():
            self._load_calibrations(show_error=False)

    def _prompt_for_calibration(self) -> None:
        if self.calibration_path_1.get().strip():
            return
        self.status.set(f"Select the mandatory {VCS_CAL_LABEL} JSON file")
        self._browse("json_1")
        if not self._selected_calibration_paths():
            self.status.set(f"Waiting for {VCS_CAL_LABEL} — use Browse when ready")

    def _selected_calibration_paths(self) -> tuple[str, ...]:
        return selected_calibration_paths(
            self.calibration_path_1.get(),
            self.calibration_path_2.get(),
        )

    def _set_measurement_paths(self, paths: tuple[str, ...]) -> None:
        self._measurement_paths = tuple(
            str(Path(path).expanduser().resolve()) for path in paths
        )
        self.measurement_path.set("; ".join(self._measurement_paths))
        if not self._measurement_paths:
            self.output_path.set("")
            return
        try:
            self.output_path.set(str(analysis_output_path(self._measurement_paths)))
        except InputValidationError as exc:
            self.output_path.set("")
            self.mapping_status.set(str(exc))

    def _browse(self, kind: str) -> None:
        if kind in {"json_1", "json_2"}:
            label = VCS_CAL_LABEL if kind == "json_1" else SAFETY_CAL_LABEL
            selected = filedialog.askopenfilename(
                title=f"Select {label} JSON file",
                filetypes=[("JSON files", "*.json")],
            )
            if selected:
                target = self.calibration_path_1 if kind == "json_1" else self.calibration_path_2
                target.set(selected)
                self._save_path_state()
                if self._selected_calibration_paths():
                    self._load_calibrations()
                else:
                    self.status.set(f"Select the mandatory {VCS_CAL_LABEL} JSON file")
        elif kind == "mdf":
            selected = filedialog.askopenfilenames(
                title="Select one or more measurement files",
                filetypes=[
                    ("MDF measurements", ("*.mf4", "*.mdf")),
                    ("All files", "*"),
                ],
            )
            if selected:
                self._set_measurement_paths(tuple(selected))
                self._save_path_state()
        elif kind == "mapping":
            selected = filedialog.askopenfilename(
                title="Select configuration workbook",
                filetypes=[
                    ("Configuration workbooks", ("*.xlsx", "*.xlsm", "*.numbers")),
                    ("Excel workbooks", ("*.xlsx", "*.xlsm")),
                    ("Apple Numbers", "*.numbers"),
                ],
            )
            if selected:
                self.mapping_path.set(selected)
                self._save_path_state()
                self._load_mapping_status()

    def _load_calibrations(self, show_error: bool = True) -> None:
        try:
            calibration_paths = self._selected_calibration_paths()
            if not calibration_paths:
                raise InputValidationError(f"Select the mandatory {VCS_CAL_LABEL} JSON file")
            self._vcs_calibrations = CalibrationRepository.from_json(
                calibration_paths[0]
            )
            self._safety_calibrations = (
                CalibrationRepository.from_json(calibration_paths[1])
                if len(calibration_paths) == 2
                else None
            )
            self._calibrations = CalibrationRepository.from_json_files(calibration_paths)
            self._loaded_calibration_paths = calibration_paths
            self._entry_by_display = {
                f"{entry.name}  —  {entry.source}  [{len(entry.values)} value{'s' if len(entry.values) != 1 else ''}]": entry
                for entry in self._calibrations.entries
            }
            self._display_by_source = {
                entry.source: display for display, entry in self._entry_by_display.items()
            }
            displays = tuple(self._entry_by_display)
            self.x_entry_box["values"] = (CONSTANT_X_OPTION, *displays)
            self.y_entry_box["values"] = displays
            self._calibration_bindings = {}
            all_bound = self._bind_from_cal_param(show_error=show_error)
            first_role, first_label, _ = THRESHOLD_BINDING_SPECS[0]
            self.threshold_role.set(first_label)
            self.binding_tree.selection_set(first_role)
            self.binding_tree.focus(first_role)
            self._refresh_binding_table()
            self._show_selected_binding()
            throttle_enabled = len(calibration_paths) == 2
            self.throttle_status.set(
                f"{SAFETY_CAL_LABEL} loaded; throttle checks are enabled."
                if throttle_enabled
                else f"{SAFETY_CAL_LABEL} is optional; throttle checks are disabled."
            )
            file_description = (
                f"{VCS_CAL_LABEL} and {SAFETY_CAL_LABEL}"
                if throttle_enabled
                else VCS_CAL_LABEL
            )
            binding_description = (
                "four calParam motion pairs and three throttle parameters"
                if throttle_enabled
                else "four calParam motion pairs"
            )
            if all_bound:
                self.status.set(
                    f"Loaded {len(displays)} numeric entries from {file_description} and applied {binding_description}"
                )
            else:
                self.status.set(
                    f"Loaded {len(displays)} numeric entries from {file_description}; load or correct the calParam workbook"
                )
        except PrecondAbortError as exc:
            self._calibrations = None
            self._vcs_calibrations = None
            self._safety_calibrations = None
            self._loaded_calibration_paths = None
            self._entry_by_display = {}
            self._display_by_source = {}
            self._calibration_bindings = {}
            self.throttle_status.set(
                f"{SAFETY_CAL_LABEL} is optional; throttle checks are disabled."
            )
            self.x_entry_box["values"] = ()
            self.y_entry_box["values"] = ()
            self.x_entry_selection.set("")
            self.y_entry_selection.set("")
            self._refresh_binding_table()
            if show_error:
                messagebox.showerror("Calibration JSON files", str(exc), parent=self.root)
            else:
                self.mapping_status.set(f"Saved calibration paths could not be loaded: {exc}")

    def _on_binding_row_selected(self, _event=None) -> None:
        selected = self.binding_tree.selection()
        if not selected:
            return
        role = selected[0]
        label = LABEL_BY_ROLE.get(role)
        if label is None:
            return
        self.threshold_role.set(label)
        self._show_selected_binding()

    def _entry_name(self, source: str) -> str:
        display = self._display_by_source.get(source)
        entry = self._entry_by_display.get(display or "")
        return entry.name if entry else source.rsplit(".", 1)[-1]

    def _refresh_binding_table(self) -> None:
        for role, label, _ in THRESHOLD_BINDING_SPECS:
            spec = self._calibration_specs.get(role)
            parameter = self._calibration_bindings.get(role)
            if parameter is not None:
                x_name = self._entry_name(parameter.x_source) if parameter.x_source else "Constant"
                y_name = self._entry_name(parameter.y_source)
                status = (
                    "Manual"
                    if parameter.source.startswith("manual:")
                    else "calParam" if spec is not None else "Automatic"
                )
                values = (label, x_name, y_name, status)
            elif role in THROTTLE_BINDING_ROLES and len(self._selected_calibration_paths()) < 2:
                values = (label, "SAFETY CAL", "SAFETY CAL", "Disabled")
            elif spec is None:
                values = (label, LOAD_CONFIG_PLACEHOLDER, LOAD_CONFIG_PLACEHOLDER, "Waiting")
            elif self._calibrations is None:
                values = (label, spec.x_entry_name, spec.y_entry_name, "Load JSON")
            else:
                values = (label, spec.x_entry_name, spec.y_entry_name, "Missing JSON")
            self.binding_tree.item(role, values=values)

    def _show_selected_binding(self) -> None:
        role = ROLE_BY_LABEL.get(self.threshold_role.get())
        parameter = self._calibration_bindings.get(role or "")
        if parameter is None:
            spec = self._calibration_specs.get(role or "")
            x_entry = None
            y_entry = None
            if self._calibrations is not None and spec is not None:
                try:
                    x_entry = self._calibrations.resolve_entry(spec.x_entry_name)
                except PrecondAbortError:
                    pass
                try:
                    y_entry = self._calibrations.resolve_entry(spec.y_entry_name)
                except PrecondAbortError:
                    pass
            self.x_entry_selection.set(
                self._display_by_source.get(x_entry.source, "") if x_entry else CONSTANT_X_OPTION
            )
            self.y_entry_selection.set(
                self._display_by_source.get(y_entry.source, "") if y_entry else ""
            )
            if self._calibrations is None:
                self.parameter_value.set(f"Load the mandatory {VCS_CAL_LABEL} JSON file to enable X/Y selection.")
            elif role in THROTTLE_BINDING_ROLES and len(self._selected_calibration_paths()) < 2:
                self.parameter_value.set(
                    f"Load the optional {SAFETY_CAL_LABEL} JSON file to enable this throttle check."
                )
            elif spec is None:
                self.parameter_value.set(
                    "This throttle parameter could not be resolved from the selected calibration files."
                    if role in THROTTLE_BINDING_ROLES
                    else "Load a workbook with a valid calParam tab."
                )
            else:
                self.parameter_value.set(
                    f"calParam requested X={spec.x_entry_name} and Y={spec.y_entry_name}, "
                    "but one or both entries were not found in the JSON file."
                )
        else:
            self.x_entry_selection.set(
                self._display_by_source.get(parameter.x_source, CONSTANT_X_OPTION)
                if parameter.x_source
                else CONSTANT_X_OPTION
            )
            self.y_entry_selection.set(self._display_by_source.get(parameter.y_source, ""))
        self._draw_selected_parameter()

    def _apply_selected_binding(self, show_error: bool = True) -> bool:
        if self._calibrations is None:
            if show_error:
                messagebox.showerror(
                    "Calibration binding",
                    f"Load the mandatory {VCS_CAL_LABEL} JSON file first.",
                    parent=self.root,
                )
            return False
        role = ROLE_BY_LABEL.get(self.threshold_role.get())
        if role is None:
            return False
        y_entry = self._entry_by_display.get(self.y_entry_selection.get())
        if y_entry is None:
            if show_error:
                messagebox.showerror(
                    "Calibration binding",
                    "Select a numeric Y entry.",
                    parent=self.root,
                )
            return False
        x_display = self.x_entry_selection.get()
        x_entry = None if x_display == CONSTANT_X_OPTION else self._entry_by_display.get(x_display)
        if x_display != CONSTANT_X_OPTION and x_entry is None:
            if show_error:
                messagebox.showerror(
                    "Calibration binding",
                    "Select a numeric X entry or the constant option.",
                    parent=self.root,
                )
            return False
        try:
            spec = self._calibration_specs.get(role)
            parameter = self._calibrations.combine_entries(
                spec.parameter_name if spec else DEFAULT_PARAMETER_NAME_BY_ROLE[role],
                x_entry.source if x_entry else None,
                y_entry.source,
            )
        except PrecondAbortError as exc:
            if show_error:
                messagebox.showerror("Invalid X/Y pair", str(exc), parent=self.root)
            return False
        self._calibration_bindings[role] = parameter
        self._refresh_binding_table()
        self.status.set(
            f"Bound {LABEL_BY_ROLE[role]} to "
            f"X={x_entry.name if x_entry else 'constant'}, Y={y_entry.name}"
        )
        self._draw_selected_parameter()
        return True

    def _load_mapping_status(self) -> None:
        try:
            mapping = load_mapping(self.mapping_path.get())
            specs = load_calibration_specs(self.mapping_path.get())
            self._calibration_specs = match_motion_calibration_specs(mapping, specs)
            if self._calibrations is not None:
                self._bind_from_cal_param(show_error=True)
            self._refresh_binding_table()
            self._show_selected_binding()
            prefix = f"Mapping and {len(self._calibration_specs)} motion pairs ready"
            self.mapping_status.set(f"{prefix}. {mapping.warning}" if mapping.warning else prefix)
        except PrecondAbortError as exc:
            self._calibration_specs = {}
            self._calibration_bindings = {}
            self._refresh_binding_table()
            self.mapping_status.set(str(exc))

    def _bind_from_cal_param(self, show_error: bool) -> bool:
        self._calibration_bindings = {}
        if (
            self._calibrations is None
            or self._vcs_calibrations is None
            or not self._calibration_specs
        ):
            self._refresh_binding_table()
            return False
        errors: list[str] = []
        for role, spec in self._calibration_specs.items():
            try:
                parameter = self._vcs_calibrations.combine_spec(spec)
                if len(self._selected_calibration_paths()) == 2:
                    parameter = with_json_provenance(
                        parameter,
                        self._selected_calibration_paths()[0],
                    )
                self._calibration_bindings[role] = parameter
            except PrecondAbortError as exc:
                errors.append(f"{LABEL_BY_ROLE[role]}: {exc}")
        if len(self._selected_calibration_paths()) == 2:
            for role in THROTTLE_BINDING_ROLES:
                requested_name = DEFAULT_PARAMETER_NAME_BY_ROLE[role]
                resolution_errors: list[str] = []
                for repository, json_path in (
                    (self._safety_calibrations, self._selected_calibration_paths()[1]),
                    (self._vcs_calibrations, self._selected_calibration_paths()[0]),
                ):
                    if repository is None:
                        continue
                    try:
                        parameter = repository.resolve(requested_name)
                        self._calibration_bindings[role] = with_json_provenance(
                            parameter,
                            json_path,
                        )
                        break
                    except PrecondAbortError as exc:
                        resolution_errors.append(str(exc))
                else:
                    errors.append(
                        f"{LABEL_BY_ROLE[role]}: not found in {SAFETY_CAL_LABEL} or "
                        f"{VCS_CAL_LABEL} ({'; '.join(resolution_errors)})"
                    )
        self._refresh_binding_table()
        if errors and show_error:
            messagebox.showerror(
                "calParam JSON lookup",
                "The following calParam entries could not be loaded from the selected JSON files:\n- "
                + "\n- ".join(errors),
                parent=self.root,
            )
        return not errors

    def _draw_selected_parameter(self) -> None:
        canvas = self.curve_canvas
        canvas.delete("all")
        role = ROLE_BY_LABEL.get(self.threshold_role.get())
        parameter = self._calibration_bindings.get(role or "")
        if parameter is None:
            canvas.create_text(
                20,
                20,
                anchor="nw",
                text="Select and apply X/Y entries for this threshold.",
                fill=MUTED,
            )
            return
        try:
            speed = float(self.interpolation_speed.get())
        except ValueError:
            self.parameter_value.set("Vehicle speed must be numeric.")
            return
        width = max(canvas.winfo_width(), 480)
        height = max(canvas.winfo_height(), 280)
        left, right, top, bottom = 58, width - 24, 24, height - 46
        x_values = parameter.x_values if parameter.is_curve else (0.0, max(speed, 1.0))
        y_values = parameter.y_values if parameter.is_curve else (parameter.y_values[0], parameter.y_values[0])
        x_min, x_max = min(x_values), max(x_values)
        y_min, y_max = min(y_values), max(y_values)
        if x_max == x_min:
            x_max = x_min + 1
        if y_max == y_min:
            padding = max(abs(y_min) * 0.1, 1.0)
            y_min -= padding
            y_max += padding

        def point(x_value: float, y_value: float) -> tuple[float, float]:
            x_pos = left + (x_value - x_min) / (x_max - x_min) * (right - left)
            y_pos = bottom - (y_value - y_min) / (y_max - y_min) * (bottom - top)
            return x_pos, y_pos

        canvas.create_line(left, top, left, bottom, fill=NAVY, width=1)
        canvas.create_line(left, bottom, right, bottom, fill=NAVY, width=1)
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x_value = x_min + fraction * (x_max - x_min)
            x_pos, _ = point(x_value, y_min)
            canvas.create_line(x_pos, bottom, x_pos, top, fill="#E6ECEF")
            canvas.create_text(x_pos, bottom + 18, text=f"{x_value:g}", fill=MUTED, font=("Aptos", 8))
            y_value = y_min + fraction * (y_max - y_min)
            _, y_pos = point(x_min, y_value)
            canvas.create_line(left, y_pos, right, y_pos, fill="#E6ECEF")
            canvas.create_text(left - 8, y_pos, anchor="e", text=f"{y_value:g}", fill=MUTED, font=("Aptos", 8))
        coordinates = [coordinate for pair in zip(x_values, y_values) for coordinate in point(*pair)]
        canvas.create_line(*coordinates, fill=TEAL, width=3, smooth=False)
        for x_value, y_value in zip(x_values, y_values):
            x_pos, y_pos = point(x_value, y_value)
            canvas.create_oval(x_pos - 4, y_pos - 4, x_pos + 4, y_pos + 4, fill=CARD, outline=TEAL, width=2)
        threshold = parameter.value_at(speed)
        marker_x = min(max(speed, x_min), x_max)
        marker_y = parameter.value_at(marker_x)
        x_pos, y_pos = point(marker_x, marker_y)
        canvas.create_line(x_pos, bottom, x_pos, y_pos, fill="#E08B26", dash=(4, 3), width=2)
        canvas.create_oval(x_pos - 5, y_pos - 5, x_pos + 5, y_pos + 5, fill="#E08B26", outline="#A85F12")
        canvas.create_text(right, 8, anchor="ne", text=parameter.name, fill=NAVY, font=("Aptos", 10, "bold"))
        canvas.create_text((left + right) / 2, height - 8, text=parameter.x_unit or "Input", fill=MUTED, font=("Aptos", 9))
        breakpoint_text = ", ".join(
            f"{x_value:g}→{y_value:g}"
            for x_value, y_value in zip(parameter.x_values, parameter.y_values)
        )
        self.parameter_value.set(
            f"At {speed:g} {parameter.x_unit or 'input units'}, the threshold is "
            f"{threshold:g} {parameter.y_unit}.  Breakpoints: {breakpoint_text}.  "
            f"Source: {parameter.source}"
        )

    def _run_analysis(self) -> None:
        paths = {
            VCS_CAL_LABEL: self.calibration_path_1.get(),
            "Configuration workbook": self.mapping_path.get(),
        }
        missing = [label for label, value in paths.items() if not value.strip()]
        if not self._measurement_paths:
            missing.append("Measurement MDF/MF4 file(s)")
        if missing:
            messagebox.showerror("Missing input", "Select the following files:\n- " + "\n- ".join(missing), parent=self.root)
            return
        try:
            output_path = analysis_output_path(self._measurement_paths)
        except InputValidationError as exc:
            messagebox.showerror("Measurement locations", str(exc), parent=self.root)
            return
        self.output_path.set(str(output_path))
        self._save_path_state()
        selected_calibration_paths = self._selected_calibration_paths()
        if self._loaded_calibration_paths != selected_calibration_paths:
            self._load_calibrations()
        if self._calibrations is None or self._loaded_calibration_paths != selected_calibration_paths:
            return
        required_roles = MOTION_BINDING_ROLES + (
            THROTTLE_BINDING_ROLES if len(selected_calibration_paths) == 2 else ()
        )
        unbound = [
            label
            for role, label, _ in THRESHOLD_BINDING_SPECS
            if role in required_roles and role not in self._calibration_bindings
        ]
        if unbound:
            messagebox.showerror(
                "Missing calibration bindings",
                "Select X and Y entries for:\n- " + "\n- ".join(unbound),
                parent=self.root,
            )
            return
        self._analysis_overrides = dict(self._calibration_bindings)
        self._analysis_calibration_paths = selected_calibration_paths
        self._analysis_throttle_checks_enabled = len(selected_calibration_paths) == 2
        self._analysis_measurement_paths = self._measurement_paths
        self._analysis_mapping_path = paths["Configuration workbook"].strip()
        self._analysis_output_path = str(output_path)
        self.run_button.configure(state="disabled")
        self.progress.start(12)
        count = len(self._analysis_measurement_paths)
        self.status.set(f"Analyzing {count} measurement file{'s' if count != 1 else ''}…")
        self.summary.configure(text="Analysis in progress")
        worker = threading.Thread(target=self._analysis_worker, daemon=True)
        worker.start()

    def _analysis_worker(self) -> None:
        try:
            calibrations = CalibrationRepository.from_json_files(
                self._analysis_calibration_paths
            )
            mapping = load_mapping(self._analysis_mapping_path)
            results: list[AnalysisResult] = []
            for measurement_path in self._analysis_measurement_paths:
                try:
                    with MDFSignalSource(measurement_path) as source:
                        results.append(
                            AbortAnalyzer().analyze(
                                source,
                                mapping,
                                calibrations,
                                measurement_path,
                                parameter_overrides=self._analysis_overrides,
                                enable_throttle_checks=self._analysis_throttle_checks_enabled,
                            )
                        )
                except PrecondAbortError as exc:
                    raise InputValidationError(
                        f"{Path(measurement_path).name}: {exc}"
                    ) from exc
            result = combine_analysis_results(tuple(results))
            output = write_report(result, self._analysis_output_path)
            self._worker_messages.put(("success", result, output))
        except Exception as exc:
            self._worker_messages.put(("error", exc))

    def _poll_worker(self) -> None:
        try:
            while True:
                message = self._worker_messages.get_nowait()
                if message[0] == "success":
                    _, result, output = message
                    self._show_result(result, output)
                else:
                    self._show_error(message[1])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_worker)

    def _show_result(self, result: AnalysisResult, output: Path) -> None:
        self._result = result
        self.progress.stop()
        self.run_button.configure(state="normal")
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        for event in result.events:
            row = event.output_row()
            preview = []
            for index, value in enumerate(row):
                if value is None:
                    preview.append("")
                elif isinstance(value, float):
                    preview.append(f"{value:.6f}" if index == 1 else f"{value:.3f}")
                else:
                    preview.append(value)
            self.results_tree.insert("", "end", values=preview)
        counts = {
            name: sum(event.flags[name] for event in result.events)
            for name in OUTPUT_REASON_FLAGS
        }
        reason_text = " · ".join(f"{name}: {count}" for name, count in counts.items() if count)
        file_count = len(result.source_files)
        self.summary.configure(
            text=(
                f"{file_count} measurement file{'s' if file_count != 1 else ''} · "
                f"{len(result.events)} abort events  |  {reason_text or 'No active reasons'}"
            )
        )
        self.status.set(f"Complete — report saved to {output}")
        throttle_mode = "Throttle checks enabled" if result.throttle_checks_enabled else "Throttle checks disabled"
        mapping_message = result.mapping.warning or f"Mapping used: {result.mapping.source}"
        self.mapping_status.set(f"{throttle_mode}. {mapping_message}")

    def _show_error(self, error: Exception) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.status.set("Analysis failed — correct the inputs and try again")
        self.summary.configure(text="No report was created")
        if isinstance(error, PrecondAbortError):
            details = str(error)
        else:
            details = f"Unexpected error: {error}"
        messagebox.showerror("Analysis failed", details, parent=self.root)


def launch() -> None:
    enable_windows_dpi_awareness()
    root = tk.Tk()
    AnalyzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
