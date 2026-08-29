"""Alpaca CLI adapter is not importable on the Opticycle live profile.

Official paper execution is alpaca-mcp-server==2.3.0 MLEG only.
This module is not imported by the live Opticycle profile and is not
an execution channel.
"""

from __future__ import annotations

raise ImportError(
    "Alpaca CLI is not importable on the Opticycle live profile; "
    "it is not a live execution channel"
)
