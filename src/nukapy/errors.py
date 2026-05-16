"""Nukapy exception hierarchy."""

from collections.abc import Mapping


class NukapyError(Exception):
    """Base exception for all nukapy errors."""

    def __init__(self, message: str) -> None:
        """Create a nukapy error."""
        self.message = message
        super().__init__(message)


class TransportError(NukapyError):
    """I/O layer error raised before an HTTP response is available."""

    def __init__(self, message: str, *, request_url: str) -> None:
        """Create a transport error."""
        self.request_url = request_url
        super().__init__(message)


class ConnectError(TransportError):
    """Connection establishment failed."""


class TimeoutError(TransportError):
    """Request timed out."""


class NetworkError(TransportError):
    """Network I/O failed."""


class HTTPError(NukapyError):
    """HTTP status-code error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        request_url: str,
        response_body: str = "",
        response_headers: Mapping[str, str] | None = None,
    ) -> None:
        """Create an HTTP status-code error."""
        self.status_code = status_code
        self.request_url = request_url
        self.response_body = response_body
        self.response_headers = dict(response_headers or {})
        super().__init__(message)


class ClientError(HTTPError):
    """HTTP 4xx error."""


class BadRequestError(ClientError):
    """HTTP 400 bad request."""


class AuthenticationError(ClientError):
    """HTTP 401 authentication failure."""


class ForbiddenError(ClientError):
    """HTTP 403 forbidden."""


class NotFoundError(ClientError):
    """HTTP 404 not found."""


class RateLimitError(ClientError):
    """HTTP 429 rate limit exceeded."""


class ServerError(HTTPError):
    """HTTP 5xx error."""


class BadGatewayError(ServerError):
    """HTTP 502 bad gateway."""


class ServiceUnavailableError(ServerError):
    """HTTP 503 service unavailable."""


class GatewayTimeoutError(ServerError):
    """HTTP 504 gateway timeout."""


__all__ = [
    "AuthenticationError",
    "BadGatewayError",
    "BadRequestError",
    "ClientError",
    "ConnectError",
    "ForbiddenError",
    "GatewayTimeoutError",
    "HTTPError",
    "NetworkError",
    "NotFoundError",
    "NukapyError",
    "RateLimitError",
    "ServerError",
    "ServiceUnavailableError",
    "TimeoutError",
    "TransportError",
]
