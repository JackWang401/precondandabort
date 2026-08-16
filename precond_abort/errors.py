class PrecondAbortError(Exception):
    """Base class for actionable application errors."""


class InputValidationError(PrecondAbortError):
    """Raised when an input file or required input value is invalid."""


class CalibrationError(InputValidationError):
    """Raised when calibration data cannot be resolved or interpolated."""


class MappingError(InputValidationError):
    """Raised when signal mapping data is missing or invalid."""


class SignalError(InputValidationError):
    """Raised when a required MDF/MF4 signal cannot be read."""
