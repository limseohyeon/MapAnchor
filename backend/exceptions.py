class DrawingError(Exception):
    """Base exception for drawing processing errors."""

    status_code = 400

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class InvalidDwgError(DrawingError):
    status_code = 422


class InsufficientStorageError(DrawingError):
    status_code = 507


class DrawingNotFoundError(DrawingError):
    status_code = 404


class MetadataError(DrawingError):
    status_code = 500


class ConversionInProgressError(DrawingError):
    status_code = 409


class ConversionError(DrawingError):
    status_code = 422


class PreviewInProgressError(DrawingError):
    status_code = 409


class PreviewError(DrawingError):
    status_code = 422


class AddressSearchError(DrawingError):
    status_code = 502

    def __init__(
        self,
        message: str,
        code: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, code)
        if status_code is not None:
            self.status_code = status_code


class CoordinateError(DrawingError):
    status_code = 422
