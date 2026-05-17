from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "APP_ERROR"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class InvalidTransitionError(ConflictError):
    code = "INVALID_TRANSITION"


class StaleStateError(ConflictError):
    code = "STALE_STATE"


class DuplicateProjectCodeError(ConflictError):
    code = "DUPLICATE_PROJECT_CODE"


class ImportPreviewError(AppError):
    status_code = 422
    code = "IMPORT_PREVIEW_ERROR"

