"""No-op journal.

Upstream records every tool call as NDJSON and supports dry-run and replay.
hyprdesk logs training data from the pi extension instead; here the
decorator is identity and dry-run is always off.
"""
from __future__ import annotations

from typing import Any, Callable


def journaled(kind: str | Callable[[dict[str, Any]], str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn
    return deco


def dry_run() -> bool:
    return False


def refuse_if_dry(what: str) -> None: ...
def start(*a: Any, **k: Any) -> None: ...
def stop(*a: Any, **k: Any) -> None: ...

# module state upstream tests/conftest.py resets between tests
_broken = False
_origin = ""
_source = ""
def set_source(*a: Any, **k: Any) -> None: ...
