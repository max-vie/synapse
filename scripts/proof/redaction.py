"""Secret and private-network redaction for shareable evidence."""

from __future__ import annotations

import re


def redact_sensitive(text: str) -> str:
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._:/+-]+", r"\1[REDACTED]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-[REDACTED]", text)
    text = re.sub(r"(?i)\b(password|passwd|secret)\s+(is)\s+\S+", r"\1 \2 [REDACTED]", text)
    text = re.sub(r"(?i)(token|password|api[_-]?key)(\s*[=:]\s*)\S+", r"\1\2[REDACTED]", text)
    text = re.sub(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "10.x.x.x", text)
    text = re.sub(r"\b192\.168\.\d{1,3}\.\d{1,3}\b", "192.168.x.x", text)
    return re.sub(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b", "172.16.x.x", text)
