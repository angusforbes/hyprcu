"""No-op activity beacon.

Upstream writes $XDG_RUNTIME_DIR/hyprcu/state.json for a Waybar indicator
and a panic keybind. hyprcu has no beacon; `pkill -f hyprcu` is the
kill switch.
"""
from __future__ import annotations

from typing import Any


def init(*a: Any, **k: Any) -> None: ...
def touch(what: str = "") -> None: ...
def on_shutdown(*a: Any, **k: Any) -> None: ...
def arm(*a: Any, **k: Any) -> None: ...
