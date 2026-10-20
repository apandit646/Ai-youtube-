"""Domain exceptions mapped to HTTP responses by a central handler."""


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ConfigurationError(AppError):
    status_code = 412
    code = "not_configured"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"


class InvalidStateError(AppError):
    status_code = 409
    code = "invalid_state"
