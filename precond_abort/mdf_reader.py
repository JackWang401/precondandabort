from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

from .errors import SignalError
from .models import SignalSeries


class MDFSignalSource:
    """Reads required channels from an MDF/MF4 file via asammdf."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._mdf = None
        self._available: tuple[str, ...] = ()

    def __enter__(self) -> "MDFSignalSource":
        if self.path.suffix.lower() not in {".mf4", ".mdf"}:
            raise SignalError(f"Measurement file must be .mf4 or .mdf: {self.path}")
        try:
            from asammdf import MDF

            self._mdf = MDF(self.path)
            self._available = tuple(self._mdf.channels_db)
        except Exception as exc:
            raise SignalError(f"Cannot open measurement file {self.path}: {exc}") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._mdf is not None:
            self._mdf.close()
        self._mdf = None

    def read_many(self, requested_names: Iterable[str]) -> dict[str, SignalSeries]:
        if self._mdf is None:
            raise RuntimeError("MDFSignalSource must be used as a context manager")
        resolved: dict[str, str] = {}
        missing: list[str] = []
        for requested in dict.fromkeys(requested_names):
            try:
                resolved[requested] = self._resolve_name(requested)
            except SignalError as exc:
                missing.append(str(exc))
        if missing:
            raise SignalError("Missing MDF/MF4 signals:\n- " + "\n- ".join(missing))

        series: dict[str, SignalSeries] = {}
        invalid: list[str] = []
        for requested, actual in resolved.items():
            try:
                signal = self._mdf.get(actual)
                timestamps = np.asarray(signal.timestamps, dtype=float)
                samples = np.asarray(signal.samples, dtype=float)
                if timestamps.ndim != 1 or samples.ndim != 1 or len(timestamps) != len(samples):
                    raise ValueError("expected one-dimensional timestamps and samples")
                if len(timestamps) == 0:
                    raise ValueError("signal is empty")
                finite = np.isfinite(timestamps) & np.isfinite(samples)
                if not finite.all():
                    timestamps = timestamps[finite]
                    samples = samples[finite]
                if len(timestamps) == 0:
                    raise ValueError("signal contains no finite values")
                series[requested] = SignalSeries(
                    timestamps=timestamps,
                    samples=samples,
                    unit=str(signal.unit or ""),
                    source_name=actual,
                )
            except Exception as exc:
                invalid.append(f"{requested} ({actual}): {exc}")
        if invalid:
            raise SignalError("Invalid MDF/MF4 signals:\n- " + "\n- ".join(invalid))
        return series

    def _resolve_name(self, requested: str) -> str:
        if requested in self._available:
            return requested
        requested_lower = requested.lower()
        case_insensitive = [name for name in self._available if name.lower() == requested_lower]
        if case_insensitive:
            return min(case_insensitive, key=len)
        suffixes = [
            name
            for name in self._available
            if name.lower().endswith(requested_lower)
            and (
                len(name) == len(requested)
                or name[-len(requested) - 1] in {".", "/"}
            )
        ]
        if suffixes:
            return min(suffixes, key=len)
        raise SignalError(f"{requested!r} was not found")

