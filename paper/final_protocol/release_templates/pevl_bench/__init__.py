"""Executable trace-validation conformance and admission package."""

from __future__ import annotations

from .admission import AdmissionProtocol, AdmissionProtocolError
from .evidence import verify_and_admit


__all__ = ["AdmissionProtocol", "AdmissionProtocolError", "verify_and_admit"]
__version__ = "2026.08-review"
