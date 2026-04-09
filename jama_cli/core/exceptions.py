"""Exception hierarchy for the Jama API client.

Replaces py_jama_rest_client exceptions with a clean hierarchy that preserves
the same class names for backward compatibility.
"""

from __future__ import annotations


class JamaException(Exception):
    """Base exception for all Jama client errors."""

    def __init__(self, message: str, status_code: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class CoreException(JamaException):
    """Transport-level errors (connection, timeout, DNS)."""


class APIException(JamaException):
    """Generic API error (non-2xx response)."""


class APIClientException(APIException):
    """Client error (4xx)."""


class APIServerException(APIException):
    """Server error (5xx)."""


class UnauthorizedException(APIClientException):
    """401 Unauthorized."""


class ResourceNotFoundException(APIClientException):
    """404 Not Found."""


class AlreadyExistsException(APIClientException):
    """409 Conflict / resource already exists."""


class TooManyRequestsException(APIClientException):
    """429 Too Many Requests."""

    def __init__(
        self,
        message: str,
        status_code: int = 429,
        reason: str | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message, status_code, reason)
        self.retry_after = retry_after
