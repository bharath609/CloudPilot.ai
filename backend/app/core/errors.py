"""Application error taxonomy and the API error envelope."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for errors that map to a structured HTTP response."""

    status_code = 400
    code = "app_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class EmptyUploadError(AppError):
    status_code = 422
    code = "file_empty"


class DuplicateImportError(AppError):
    status_code = 409
    code = "duplicate_import"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
