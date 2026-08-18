"""Upstream error type for safe error handling.

UpstreamError carries both a stable client-safe ``error_code`` and a
``detail`` string for internal diagnostics. The service layer returns only the
generic code to API clients and does not print the detail, so internal URLs,
hostnames, ports, and upstream response bodies are not leaked.
"""

from __future__ import annotations


class UpstreamError(RuntimeError):
    """An upstream HTTP call failed.

    Parameters
    ----------
    error_code : str
        Stable, generic identifier returned to API clients
        (e.g. ``"upstream_qdrant_unavailable"``).
    detail : str
        Full diagnostic information retained on the exception for internal
        handling. Must never be included in API responses or logs.
    """

    def __init__(self, error_code: str, detail: str) -> None:
        self.error_code = error_code
        self.detail = detail
        super().__init__(detail)
