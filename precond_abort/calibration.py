from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .errors import CalibrationError
from .models import CalibrationBindingSpec, CalibrationEntry, CalibrationParameter


THRESHOLD_ALIASES: dict[str, tuple[str, ...]] = {
    "pedalposproincrease_th": (
        "PedalPosProIncrease_Th",
        "LSB_Throttle_Override_Increase",
    ),
    "pedalpospro_override": (
        "PedalPosPro_Override",
        "LSB_Min_Throttle_Override",
    ),
}


def _normalise(name: str) -> str:
    return "".join(character.lower() for character in name if character.isalnum() or character == "_")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _numeric_values(value: Any) -> tuple[float, ...] | None:
    if _is_number(value):
        return (float(value),)
    if isinstance(value, list) and value and all(_is_number(item) for item in value):
        return tuple(float(item) for item in value)
    return None


class CalibrationRepository:
    """Discovers constant and one-dimensional curve calibrations in JSON data."""

    def __init__(
        self,
        parameters: Iterable[CalibrationParameter],
        source_path: Path | None = None,
        invalid_parameters: dict[str, str] | None = None,
        entries: Iterable[CalibrationEntry] = (),
    ):
        self.source_path = source_path
        self._parameters = tuple(parameters)
        self._invalid_parameters = invalid_parameters or {}
        self._entries = tuple(entries)
        by_name: dict[str, list[CalibrationParameter]] = defaultdict(list)
        for parameter in self._parameters:
            by_name[_normalise(parameter.name)].append(parameter)
            by_name[_normalise(parameter.source)].append(parameter)
        self._by_name = dict(by_name)
        entries_by_name: dict[str, list[CalibrationEntry]] = defaultdict(list)
        for entry in self._entries:
            entries_by_name[_normalise(entry.name)].append(entry)
            entries_by_name[_normalise(entry.source)].append(entry)
        self._entries_by_name = dict(entries_by_name)

    @classmethod
    def from_json(cls, path: str | Path) -> "CalibrationRepository":
        source_path = Path(path)
        if source_path.suffix.lower() != ".json":
            raise CalibrationError(f"Calibration file must be JSON: {source_path}")
        try:
            with source_path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationError(f"Cannot read calibration JSON {source_path}: {exc}") from exc
        return cls.from_document(document, source_path=source_path)

    @classmethod
    def from_json_files(cls, paths: Iterable[str | Path]) -> "CalibrationRepository":
        """Load calibration entries from one or more JSON files.

        Sources are namespaced with their originating filename when multiple files
        are loaded. This preserves provenance in the HMI and output report while
        still allowing calParam to resolve an entry by its leaf name.
        """

        source_paths = tuple(Path(path).expanduser().resolve() for path in paths)
        if not source_paths:
            raise CalibrationError("Select at least one calibration JSON file")
        if len(set(source_paths)) != len(source_paths):
            raise CalibrationError("Select different calibration JSON files")
        repositories = tuple(cls.from_json(path) for path in source_paths)
        if len(repositories) == 1:
            return repositories[0]

        filename_counts = Counter(path.name for path in source_paths)
        parameters: list[CalibrationParameter] = []
        entries: list[CalibrationEntry] = []
        invalid_parameters: dict[str, str] = {}

        for path, repository in zip(source_paths, repositories):
            label = path.name if filename_counts[path.name] == 1 else str(path)

            def scoped(source: str) -> str:
                return f"{label}::{source}" if source else ""

            entries.extend(
                CalibrationEntry(
                    name=entry.name,
                    source=scoped(entry.source),
                    values=entry.values,
                    unit=entry.unit,
                )
                for entry in repository._entries
            )
            parameters.extend(
                CalibrationParameter(
                    name=parameter.name,
                    source=scoped(parameter.source),
                    x_values=parameter.x_values,
                    y_values=parameter.y_values,
                    x_unit=parameter.x_unit,
                    y_unit=parameter.y_unit,
                    x_source=scoped(parameter.x_source),
                    y_source=scoped(parameter.y_source),
                )
                for parameter in repository._parameters
            )
            for key, message in repository._invalid_parameters.items():
                invalid_parameters.setdefault(key, f"{label}: {message}")

        return cls(
            parameters,
            invalid_parameters=invalid_parameters,
            entries=entries,
        )

    @classmethod
    def from_document(
        cls,
        document: Any,
        source_path: Path | None = None,
    ) -> "CalibrationRepository":
        leaves: dict[tuple[str, ...], dict[str, Any]] = {}

        def visit(node: Any, path: tuple[str, ...]) -> None:
            if not isinstance(node, dict):
                return
            for key, value in node.items():
                next_path = (*path, str(key))
                if isinstance(value, dict) and "value" in value:
                    leaves[next_path] = value
                elif isinstance(value, dict):
                    visit(value, next_path)

        visit(document, ())
        if not leaves:
            raise CalibrationError("The calibration JSON contains no objects with a 'value' field")

        entries = [
            CalibrationEntry(
                name=path[-1],
                source=".".join(path),
                values=values,
                unit=str(entry.get("unit", "")),
            )
            for path, entry in leaves.items()
            if (values := _numeric_values(entry.get("value"))) is not None
        ]
        parameters: list[CalibrationParameter] = []
        invalid_parameters: dict[str, str] = {}
        consumed: set[tuple[str, ...]] = set()
        for path, entry in leaves.items():
            leaf_name = path[-1]
            if not leaf_name.lower().endswith("_x"):
                continue
            base_name = leaf_name[:-2]
            y_path = (*path[:-1], f"{base_name}_y")
            y_entry = leaves.get(y_path)
            if y_entry is None:
                continue
            x_values = _numeric_values(entry.get("value"))
            y_values = _numeric_values(y_entry.get("value"))
            if x_values is None or y_values is None:
                continue
            source = ".".join((*path[:-1], base_name))
            if len(x_values) != len(y_values):
                message = (
                    f"Calibration curve {source!r} has {len(x_values)} x values "
                    f"but {len(y_values)} y values"
                )
                invalid_parameters[_normalise(base_name)] = message
                invalid_parameters[_normalise(source)] = message
                consumed.update((path, y_path, (*path[:-1], base_name)))
                continue
            if len(x_values) == 0:
                message = f"Calibration curve {source!r} is empty"
                invalid_parameters[_normalise(base_name)] = message
                invalid_parameters[_normalise(source)] = message
                consumed.update((path, y_path, (*path[:-1], base_name)))
                continue
            pairs = sorted(zip(x_values, y_values), key=lambda pair: pair[0])
            if any(pairs[index][0] == pairs[index - 1][0] for index in range(1, len(pairs))):
                message = f"Calibration curve {source!r} contains duplicate x values"
                invalid_parameters[_normalise(base_name)] = message
                invalid_parameters[_normalise(source)] = message
                consumed.update((path, y_path, (*path[:-1], base_name)))
                continue
            parameters.append(
                CalibrationParameter(
                    name=base_name,
                    source=source,
                    x_values=tuple(pair[0] for pair in pairs),
                    y_values=tuple(pair[1] for pair in pairs),
                    x_unit=str(entry.get("unit", "")),
                    y_unit=str(y_entry.get("unit", "")),
                    x_source=".".join(path),
                    y_source=".".join(y_path),
                )
            )
            consumed.update((path, y_path, (*path[:-1], base_name)))

        for path, entry in leaves.items():
            if path in consumed or path[-1].lower().endswith(("_x", "_y")):
                continue
            values = _numeric_values(entry.get("value"))
            if values is None:
                continue
            if len(values) > 1 and not all(value == values[0] for value in values[1:]):
                continue
            parameters.append(
                CalibrationParameter(
                    name=path[-1],
                    source=".".join(path),
                    x_values=(0.0,),
                    y_values=(values[0],),
                    y_unit=str(entry.get("unit", "")),
                    y_source=".".join(path),
                )
            )

        if not entries:
            raise CalibrationError("The calibration JSON contains no numeric calibration entries")
        return cls(
            parameters,
            source_path=source_path,
            invalid_parameters=invalid_parameters,
            entries=entries,
        )

    @property
    def parameters(self) -> tuple[CalibrationParameter, ...]:
        return tuple(sorted(self._parameters, key=lambda item: (item.name.lower(), item.source.lower())))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters)

    @property
    def entries(self) -> tuple[CalibrationEntry, ...]:
        return tuple(sorted(self._entries, key=lambda item: (item.name.lower(), item.source.lower())))

    def resolve(self, requested_name: str) -> CalibrationParameter:
        candidates = self._resolve_direct(requested_name)
        if not candidates:
            for alias in THRESHOLD_ALIASES.get(_normalise(requested_name), (requested_name,)):
                candidates = self._resolve_direct(alias)
                if candidates:
                    break
        if not candidates:
            invalid = self._invalid_parameters.get(_normalise(requested_name))
            if invalid:
                raise CalibrationError(invalid)
            raise CalibrationError(f"Calibration parameter {requested_name!r} was not found")
        unique = {parameter.source: parameter for parameter in candidates}
        if len(unique) > 1:
            sources = ", ".join(sorted(unique))
            raise CalibrationError(
                f"Calibration parameter {requested_name!r} is ambiguous; use a full path: {sources}"
            )
        return next(iter(unique.values()))

    def _resolve_direct(self, name: str) -> list[CalibrationParameter]:
        normalised = _normalise(name)
        direct = self._by_name.get(normalised, [])
        if direct:
            return list(direct)
        suffix = f".{name}".lower()
        return [parameter for parameter in self._parameters if parameter.source.lower().endswith(suffix)]

    def resolve_entry(self, requested_name: str) -> CalibrationEntry:
        normalised = _normalise(requested_name)
        candidates = self._entries_by_name.get(normalised, [])
        if not candidates:
            suffix = f".{requested_name}".lower()
            candidates = [entry for entry in self._entries if entry.source.lower().endswith(suffix)]
        unique = {entry.source: entry for entry in candidates}
        if not unique:
            raise CalibrationError(f"Numeric calibration entry {requested_name!r} was not found")
        if len(unique) > 1:
            sources = ", ".join(sorted(unique))
            raise CalibrationError(
                f"Numeric calibration entry {requested_name!r} is ambiguous; use a full path: {sources}"
            )
        return next(iter(unique.values()))

    def combine_entries(
        self,
        parameter_name: str,
        x_source: str | None,
        y_source: str,
    ) -> CalibrationParameter:
        y_entry = self.resolve_entry(y_source)
        if not x_source:
            if len(y_entry.values) > 1 and not all(
                value == y_entry.values[0] for value in y_entry.values[1:]
            ):
                raise CalibrationError(
                    f"{y_entry.source!r} contains multiple different Y values; select an X entry"
                )
            return CalibrationParameter(
                name=parameter_name,
                source=f"manual:{y_entry.source}",
                x_values=(0.0,),
                y_values=(y_entry.values[0],),
                y_unit=y_entry.unit,
                y_source=y_entry.source,
            )

        x_entry = self.resolve_entry(x_source)
        if len(x_entry.values) != len(y_entry.values):
            raise CalibrationError(
                f"Selected X entry has {len(x_entry.values)} values but selected Y entry has "
                f"{len(y_entry.values)} values"
            )
        pairs = sorted(zip(x_entry.values, y_entry.values), key=lambda pair: pair[0])
        if any(pairs[index][0] == pairs[index - 1][0] for index in range(1, len(pairs))):
            raise CalibrationError("The selected X entry contains duplicate values")
        return CalibrationParameter(
            name=parameter_name,
            source=f"manual:{x_entry.source} + {y_entry.source}",
            x_values=tuple(pair[0] for pair in pairs),
            y_values=tuple(pair[1] for pair in pairs),
            x_unit=x_entry.unit,
            y_unit=y_entry.unit,
            x_source=x_entry.source,
            y_source=y_entry.source,
        )

    def combine_spec(self, spec: CalibrationBindingSpec) -> CalibrationParameter:
        parameter = self.combine_entries(
            spec.parameter_name,
            spec.x_entry_name,
            spec.y_entry_name,
        )
        return CalibrationParameter(
            name=parameter.name,
            source=f"{spec.source} -> {parameter.source}",
            x_values=parameter.x_values,
            y_values=parameter.y_values,
            x_unit=parameter.x_unit,
            y_unit=parameter.y_unit,
            x_source=parameter.x_source,
            y_source=parameter.y_source,
        )

    def resolve_many(self, names: Iterable[str]) -> dict[str, CalibrationParameter]:
        resolved: dict[str, CalibrationParameter] = {}
        missing: list[str] = []
        for name in dict.fromkeys(names):
            try:
                resolved[name] = self.resolve(name)
            except CalibrationError as exc:
                missing.append(str(exc))
        if missing:
            raise CalibrationError("Missing or invalid calibration parameters:\n- " + "\n- ".join(missing))
        return resolved
