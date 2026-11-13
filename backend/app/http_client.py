"""Shared HTTP client factory using the OS trust store with full TLS verification."""

from __future__ import annotations

import ssl

import httpx

DEFAULT_USER_AGENT = "HighSchoolInternshipScreener/1.0"


def build_http_client(
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> httpx.Client:
    """Create an httpx.Client verified against the host OS certificate store."""
    merged_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        merged_headers.update(headers)
    return httpx.Client(
        timeout=timeout,
        headers=merged_headers,
        follow_redirects=follow_redirects,
        verify=ssl.create_default_context(),
    )
