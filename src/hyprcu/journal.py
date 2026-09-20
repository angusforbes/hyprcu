"""Training-data log (replaces upstream's audit journal).

Upstream's journal recorded every call as NDJSON for audit/replay and
implemented dry-run. hyprcu keeps the decorator seam and uses it for one
thing: appending acting calls to a JSONL file that can later be labelled
and used to fine-tune kev (window/element selection). Observation tools
(desktop, screenshot, ui…) are not logged — they carry no decision signal.

Each row: ts, tool, args (as passed), the desktop's window list at the time
(the candidate set kev chose from), result text, error flag, and — when the
target was resolved by kev — the query, chosen address and probability.

  HYPRCU_LOG      path (default ~/.local/share/hyprcu/actions.jsonl)
  HYPRCU_LOG=0    disable

`correct` is left absent: a human (or a later verification step) sets it.
Rows without it are unlabelled and must not be trained on as-is.
"""
from __future__ import annotations

import functools
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

_PATH = os.environ.get("HYPRCU_LOG", str(Path.home() / ".local/share/hyprcu/actions.jsonl"))
_ENABLED = _PATH not in ("0", "", "off", "false")
_KEV = re.compile(r"\[kev: (\d+)% (?:of \d+ matches, |in )(\d+)ms\]")


def _windows() -> list[dict[str, Any]]:
    try:
        from hyprcu import hyprctl
        return [{"address": c.get("address"), "class": c.get("class"), "title": (c.get("title") or "")[:80],
                 "workspace": (c.get("workspace") or {}).get("name")}
                for c in hyprctl.query("clients") if c.get("mapped", True)]
    except Exception:  # noqa: BLE001 — logging must never break a tool
        return []


def _text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        for blk in result:
            t = getattr(blk, "text", None)
            if t: return t
    if isinstance(result, dict):
        return json.dumps(result)[:300]
    return str(result)[:300]


def _append(row: dict[str, Any]) -> None:
    try:
        p = Path(_PATH); p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _log(tool: str, kwargs: dict[str, Any], txt: str, err: bool, t0: float) -> None:
    """Build and append one row. Window snapshot is taken AFTER the action so a
    stubbed/failed hyprctl in tests cannot stall the tool; any failure here is
    swallowed — logging must never change a tool's behaviour."""
    try:
        row: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool,
            "args": {k: v for k, v in kwargs.items() if v not in (None, "", False)},
            "windows": _windows(), "result": txt[:300], "is_error": err,
            "ms": int((time.time() - t0) * 1000),
        }
        m = _KEV.search(txt); q = kwargs.get("window") or kwargs.get("target")
        if m and q:
            row["kev"] = {"query": q, "p": int(m.group(1)) / 100, "ms": int(m.group(2))}
        _append(row)
    except Exception:  # noqa: BLE001
        pass


def journaled(kind: str | Callable[[dict[str, Any]], str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Log acting tools. `kind` is upstream's 'act'/'observe' tag (or a fn)."""
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not _ENABLED or kind != "act":
            return fn
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.time()
            try:
                out = fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                _log(fn.__name__, kwargs, f"{type(e).__name__}: {e}", True, t0)
                raise
            _log(fn.__name__, kwargs, _text(out), False, t0)
            return out   # untouched: launch returns a dict, others str/list
        return wrapper
    return deco


# ── upstream surface kept as no-ops ────────────────────────────────────────
def dry_run() -> bool: return False
def refuse_if_dry(what: str) -> None: ...
def start(*a: Any, **k: Any) -> None: ...
def stop(*a: Any, **k: Any) -> None: ...
def set_source(*a: Any, **k: Any) -> None: ...

# module state upstream tests/conftest.py resets between tests
_broken = False
_origin = ""
_source = ""
