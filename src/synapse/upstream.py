"""Upstream error type for safe error handling.

UpstreamError carries both a stable client-safe ``error_code`` and a
``detail`` string for server-side logging. The service layer logs the
detail and returns only the generic code to API clients so internal
URLs, hostnames, ports, and upstream response bodies are never leaked.
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
        Full diagnostic information for server-side logging.
        Must never be included in API responses.
    """

    def __init__(self, error_code: str, detail: str) -> None:
        self.error_code = error_code
        self.detail = detail
        super().__init__(detail)
