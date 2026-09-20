"""No-op trust layer.

hyprdesk is dialog-free by design: the agent has the seat, full stop.
Upstream hypruse gates every action through confinement, auth-dialog
detection, seat-ownership and session-lock checks. This module keeps the
same names so server.py / input.py are unmodified, but every guard is a
pass-through. Guards return None (no note) or raise nothing.
"""
from __future__ import annotations

from typing import Any


class TrustError(RuntimeError):  # kept for `except TrustError` sites
    pass


# ── seat / capture bookkeeping ──────────────────────────────────────────
def remember_seat() -> None: ...
def notify_capture() -> None: ...
def init_marking() -> None: ...
def note_launched(address: str, label: str = "") -> None: ...


# ── guards: all pass ────────────────────────────────────────────────────
def guard_seat() -> None: ...
def guard_pointer(x: Any = None, y: Any = None, allow_auth: bool = False) -> None: ...
def guard_client(address: str) -> None: ...
def guard_window(address: str) -> None: ...
def guard_auth_client(address: str, allow_auth: bool = False) -> None: ...
def guard_use_bind() -> None: ...
def guard_password_field(*a: Any, **k: Any) -> None: ...


def guard_session_lock(window_given: bool = False, allow_auth: bool = False) -> str:
    return ""   # upstream: "" = no note; a non-empty string is appended to the result


def guard_keyboard_layer(window_given: bool = False, allow_auth: bool = False) -> str:
    return ""


def guard_covering_layer(x: Any, y: Any) -> None: ...


# ── queries ─────────────────────────────────────────────────────────────
def guards_window_input() -> bool:
    return False


def session_locked() -> bool:
    return False


def covering_layer(x: Any, y: Any) -> None:
    return None
