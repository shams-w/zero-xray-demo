"""SSRF-safe validation helpers for user-supplied OpenAPI/Swagger URLs."""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import parse_qsl, urlparse


class UnsafeUrlError(ValueError):
    pass


def _allow_private_targets() -> bool:
    return os.getenv("ZX_OPENAPI_ALLOW_PRIVATE_HOSTS", "0").strip().lower() in {"1", "true", "yes"}


def _allow_http() -> bool:
    return os.getenv("ZX_OPENAPI_ALLOW_HTTP", "0").strip().lower() in {"1", "true", "yes"}


def _unsafe_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return any((
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_unspecified,
        ip.is_reserved,
        ip.is_private,
    ))


def assert_safe_target_url(url: str) -> str:
    """Validate scheme/host and DNS resolution before an outbound fetch.

    Private/internal hosts are rejected by default. Operators may explicitly
    opt in for trusted internal staging networks with
    ZX_OPENAPI_ALLOW_PRIVATE_HOSTS=1.
    """
    value = str(url or "").strip()
    if not value:
        raise UnsafeUrlError("OpenAPI URL is required.")
    parsed = urlparse(value)
    allowed = {"https"}
    if _allow_http():
        allowed.add("http")
    if parsed.scheme.lower() not in allowed:
        raise UnsafeUrlError("OpenAPI URL must use HTTPS.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("OpenAPI URL must contain a safe hostname and no embedded credentials.")
    sensitive_query_keys = {"token", "access_token", "api_key", "apikey", "key", "password", "secret", "authorization", "auth"}
    if any(str(key).strip().lower() in sensitive_query_keys for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise UnsafeUrlError("Credentials or secret tokens must not be placed in the OpenAPI URL.")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise UnsafeUrlError("Localhost targets are not allowed.")

    try:
        # Literal IP first.
        ipaddress.ip_address(host)
        addresses = {host}
    except ValueError:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise UnsafeUrlError("OpenAPI hostname could not be resolved safely.") from exc

    if not addresses:
        raise UnsafeUrlError("OpenAPI hostname could not be resolved safely.")
    if not _allow_private_targets():
        for address in addresses:
            try:
                if _unsafe_ip(address):
                    raise UnsafeUrlError("Private, loopback, link-local, or reserved network targets are not allowed.")
            except ValueError as exc:
                raise UnsafeUrlError("OpenAPI hostname resolved to an invalid address.") from exc
    return value
