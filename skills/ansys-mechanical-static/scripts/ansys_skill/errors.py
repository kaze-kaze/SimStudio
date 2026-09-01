"""Domain errors and stable process exit codes."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    VALIDATION_FAILED = 2
    ENVIRONMENT_UNAVAILABLE = 3
    MECHANICAL_FAILED = 4
    POSTPROCESSING_FAILED = 5
    VERIFICATION_FAILED = 6


class AnsysSimError(Exception):
    """Base error carrying a stable CLI exit code."""

    exit_code = ExitCode.VALIDATION_FAILED
    error_type = "ansys_sim_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class SpecValidationError(AnsysSimError):
    error_type = "spec_validation_error"


class UnsupportedFeatureError(SpecValidationError):
    error_type = "unsupported_feature"


class PathSafetyError(SpecValidationError):
    error_type = "path_safety_error"


class EnvironmentUnavailableError(AnsysSimError):
    exit_code = ExitCode.ENVIRONMENT_UNAVAILABLE
    error_type = "environment_unavailable"


class MechanicalExecutionError(AnsysSimError):
    exit_code = ExitCode.MECHANICAL_FAILED
    error_type = "mechanical_execution_error"


class PostprocessingError(AnsysSimError):
    exit_code = ExitCode.POSTPROCESSING_FAILED
    error_type = "postprocessing_error"


class VerificationError(AnsysSimError):
    exit_code = ExitCode.VERIFICATION_FAILED
    error_type = "verification_error"
