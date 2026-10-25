"""Who may change things: write modes, the write token, and the Host check.

Reads are always open. Anything that changes state or costs money (saving docs,
accepting a proposal, commenting, AI calls) is a non-GET request under ``/api``, and
:class:`WriteGuard` checks every one of those, so a new endpoint is protected by default.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

WriteMode = Literal["open", "token", "off"]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::"})
_TRUE = {"1", "true", "yes", "on"}


def is_loopback_host(host: str) -> bool:
    """True for ``localhost`` and loopback IPs such as 127.0.0.1 and ::1."""
    host = host.strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class WriteSettings:
    mode: WriteMode
    token: str | None = None
    generated: bool = False
    """True when the token was made up at startup and must be shown to the person."""


def resolve_write_mode(host: str, token: str | None, read_only: bool) -> WriteSettings:
    """Pick the write mode for ``openpipeline serve``.

    ``--read-only`` wins. A token means token mode. With no token, a loopback host
    stays open (the local dev experience), and anything else gets a random token so
    a public bind is never open.
    """
    token = token or None
    if read_only:
        return WriteSettings("off")
    if token:
        return WriteSettings("token", token)
    if is_loopback_host(host):
        return WriteSettings("open")
    return WriteSettings("token", secrets.token_urlsafe(24), generated=True)


def settings_from_env() -> tuple[str, int, WriteSettings]:
    """The same rules, read from the environment for ``uvicorn openpipeline.app:app``."""
    host = os.environ.get("OPENPIPELINE_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENPIPELINE_PORT", "8484"))
    read_only = os.environ.get("OPENPIPELINE_READ_ONLY", "").lower() in _TRUE
    return host, port, resolve_write_mode(host, os.environ.get("OPENPIPELINE_TOKEN"), read_only)


def browser_url(host: str, port: int, token: str | None = None) -> str:
    """A URL a person can open. Wildcard binds are shown as ``localhost``."""
    shown = "localhost" if host in _WILDCARD_HOSTS else host
    if ":" in shown and not shown.startswith("["):
        shown = f"[{shown}]"
    url = f"http://{shown}:{port}/"
    return f"{url}?token={token}" if token else url


def split_host_header(value: str) -> tuple[str, int | None]:
    """``'[::1]:8484'`` -> ``('::1', 8484)``. A missing port gives ``None``."""
    value = value.strip()
    if value.startswith("["):
        name, _, rest = value[1:].partition("]")
        port_text = rest.removeprefix(":")
    else:
        name, _, port_text = value.partition(":")
    return name.lower(), int(port_text) if port_text.isdigit() else None


def bearer_token(request: Request) -> str | None:
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


def token_matches(supplied: str | None, expected: str) -> bool:
    if supplied is None:
        return False
    return secrets.compare_digest(supplied.encode(), expected.encode())


def _reject(status: int, detail: str, headers: dict[str, str] | None = None) -> Response:
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


class WriteGuard:
    """Decides whether a request may write, and whether its Host header is acceptable."""

    def __init__(
        self,
        mode: WriteMode,
        token: str | None = None,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        allowed_hosts: Collection[str] = (),
    ) -> None:
        if mode == "token" and not token:
            raise ValueError("Write mode 'token' needs a non-empty token.")
        if mode == "open" and not is_loopback_host(host):
            raise ValueError(
                f"Write mode 'open' is only allowed on a loopback address, not {host!r}. "
                "Use a token or read-only mode."
            )
        self.mode: WriteMode = mode
        self.token = token
        self.port = port
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)

    def token_valid(self, request: Request) -> bool:
        return self.token is not None and token_matches(bearer_token(request), self.token)

    def host_allowed(self, request: Request) -> bool:
        name, port = split_host_header(request.headers.get("host", ""))
        if name in self.allowed_hosts:
            return True
        if not is_loopback_host(name):
            return False
        return self.port is None or (port if port is not None else 80) == self.port

    def check(self, request: Request) -> Response | None:
        """A rejection for this request, or ``None`` if it may go ahead."""
        path = request.url.path
        if not (path == "/api" or path.startswith("/api/")):
            return None
        if self.mode == "open" and not self.host_allowed(request):
            return _reject(
                403, "This Host header is not allowed. Open the server as localhost or 127.0.0.1."
            )
        if request.method in SAFE_METHODS:
            return None
        if self.mode == "off":
            return _reject(403, "This server is read-only. Restart it without --read-only to edit.")
        if self.mode == "token" and not self.token_valid(request):
            return _reject(
                401,
                "A write token is required. Send 'Authorization: Bearer <token>'.",
                headers={"WWW-Authenticate": 'Bearer realm="openpipeline"'},
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return _reject(415, "Writes must be sent with 'Content-Type: application/json'.")
        return None


class BearerTokenMiddleware:
    """ASGI wrapper that requires the token on every HTTP request (MCP over HTTP)."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not token_matches(bearer_token(Request(scope)), self.token):
            response = _reject(
                401,
                "A token is required. Send 'Authorization: Bearer <token>'.",
                headers={"WWW-Authenticate": 'Bearer realm="openpipeline"'},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
