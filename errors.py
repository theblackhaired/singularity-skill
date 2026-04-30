"""Typed exceptions for the singularity skill (Iter 6 / T6.2).

Used by client.py / pagination.py / derived handlers. cli.py wraps these into
RuntimeError for backward compatibility — see _request error path.
"""


class SingularityError(RuntimeError):
    """Base for all skill-specific errors. Subclass of RuntimeError to keep
    backward compatibility with existing `except RuntimeError:` callers."""


class TransportError(SingularityError):
    """Network-level failure (DNS, TCP, TLS). Should be retryable."""


class HttpError(SingularityError):
    """HTTP non-2xx response after retries. Carries status code + redacted body."""

    def __init__(self, status: int, message: str, *, body: str = ""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.body = body


class RateLimitError(HttpError):
    """HTTP 429. Includes Retry-After hint when available."""

    def __init__(self, retry_after: float | None = None, body: str = ""):
        super().__init__(429, "Too Many Requests", body=body)
        self.retry_after = retry_after


class NotFoundError(HttpError):
    """HTTP 404 for a resource path we expected to exist."""


class AuthError(HttpError):
    """HTTP 401/403."""


class CapabilityError(SingularityError):
    """Endpoint reachable but response shape doesn't match expected contract.

    Used by note_resolver and derived tools to mark `status: "degraded"`
    without losing the diagnostic.
    """


def _error_response(code: str, message: str, **context) -> dict:
    payload = {
        "status": "error",
        "code": code,
        "message": message,
    }
    payload.update(context)
    return payload


class StructuredError(Exception):
    """Exception carrying a JSON error response for --call output."""

    def __init__(self, code: str, message: str, **context):
        self.payload = _error_response(code, message, **context)
        super().__init__(message)


__all__ = [
    "SingularityError",
    "TransportError",
    "HttpError",
    "RateLimitError",
    "NotFoundError",
    "AuthError",
    "CapabilityError",
    "StructuredError",
    "_error_response",
]
