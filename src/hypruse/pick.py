"""Natural-language window selection via a local kev (Jev-compatible) server.

`window` arguments across the server accept three forms:
  - an address       "0x561283a8e870"        → exact
  - a substring      "Strata", "Slack"       → case-insensitive on class/title
  - a description    "the file browser"      → kev choice over open windows

The chokepoint is `resolve()`. It returns (client, note) where note is "" or
" [kev: NN% in Nms]" for the caller to append to its result text.

Env:
  KEV_URL   default http://127.0.0.1:8009/v1/systemone  (kev, Jev, openjev…)
  KEV_GATE  default 0.5 — below this, resolution fails with a message
            pointing at desktop()/launch, because the app is probably not open.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

KEV_URL = os.environ.get("KEV_URL", "http://127.0.0.1:8009/v1/systemone")
KEV_GATE = float(os.environ.get("KEV_GATE", "0.5"))
KEV_TIMEOUT_S = 3.0

# Human-friendly hints so a text model can match "file browser" → Strata.
# Extend as apps are learned; the pi extension's LESSONS.md is the source.
APP_HINTS: dict[str, str] = {
    "io.github.lgse.Strata": "Strata file browser, file manager",
    "foot": "foot terminal, shell, command line",
    "chromium": "Chromium web browser",
    "brave-origin": "Brave web browser",
    "slack": "Slack chat, messaging",
    "md.obsidian.Obsidian": "Obsidian notes, markdown",
    "org.omarchy.agent": "AI agent pane, Claude Code, assistant chat",
    "imv": "imv image viewer",
}
_TITLE_NOISE = (" - Chromium", " - Brave Origin", " - Google Search", " - Slack")
_ADDR = re.compile(r"^0x", re.I)   # anything address-shaped is an address, even malformed


class ResolveError(ValueError):
    pass


def describe(c: dict[str, Any]) -> str:
    t = str(c.get("title", ""))
    for s in _TITLE_NOISE:
        t = t.replace(s, "")
    t = t.strip(" ✳◑●○").strip()[:60]
    ws = (c.get("workspace") or {}).get("name", "")
    where = f" (workspace {ws})" if ws and not str(ws).startswith("special") else " (scratchpad)" if ws else ""
    return f"{t} — {APP_HINTS.get(c.get('class', ''), c.get('class', ''))}{where}"


def _kev(query: str, clients: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float, int]:
    c, p, ms, _ = _kev_full(query, clients)
    return c, p, ms


def _kev_full(query: str, clients: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float, int, dict[str, float]]:
    """(chosen client, probability, ms, all probabilities). (None, 0, 0, {}) if kev is unreachable."""
    if not clients:
        return None, 0.0, 0, {}
    if len(clients) == 1:
        return clients[0], 1.0, 0, {clients[0]["address"]: 1.0}
    criteria = {c["address"]: describe(c) for c in clients}
    body = {
        "model": "kev",
        "state": f'The user wants to interact with: "{query}"',
        "questions": {"w": {"type": "choice",
                            "instructions": "Which open window best matches what the user described?",
                            "criteria": criteria}},
    }
    req = urllib.request.Request(KEV_URL, json.dumps(body).encode(), {"content-type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=KEV_TIMEOUT_S) as r:
            ans = json.load(r)["answers"]["w"]
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError, TimeoutError):
        return None, 0.0, 0, {}
    ms = int((time.time() - t0) * 1000)
    addr = ans["choice"]
    client = next((c for c in clients if c["address"] == addr), None)
    probs = {k: float(v) for k, v in ans["probabilities"].items()}
    return client, probs.get(addr, 0.0), ms, probs


def resolve(window: str, clients: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Address → substring → kev. Raises ResolveError with an actionable message."""
    q = window.strip()
    if _ADDR.match(q):
        c = next((c for c in clients if c.get("address") == q), None)
        if c is None:
            raise ResolveError(f"window {q!r} not found, call desktop() for current addresses")
        return c, ""
    ql = q.lower()
    hits = [c for c in clients if ql in str(c.get("class", "")).lower() or ql in str(c.get("title", "")).lower()]
    if len(hits) == 1:
        return hits[0], ""
    if len(hits) > 1:
        # several substring matches: let kev break the tie among just those
        c, p, ms, probs = _kev_full(q, hits)
        if c is not None:
            # among N substring hits a 1/N split is the null hypothesis; accept
            # when the winner beats the runner-up by a clear margin, not by
            # the absolute gate (which 8-way splits can never reach)
            ranked = sorted(probs.values(), reverse=True)
            margin = ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0)
            if p >= KEV_GATE or margin >= 0.15:
                return c, f" [kev: {p:.0%} of {len(hits)} matches, {ms}ms]"
        names = "; ".join(f"{h['address']} {describe(h)[:40]}" for h in hits[:6])
        raise ResolveError(f"{q!r} matches {len(hits)} windows — pass an address: {names}")
    # no substring hit: natural language over visible, mapped windows
    visible = [c for c in clients if c.get("mapped", True) and c.get("workspace", {}).get("name") != "special:reprieve"]
    c, p, ms = _kev(q, visible or clients)
    if c is None:
        raise ResolveError(f"no window matches {q!r} and kev is unreachable at {KEV_URL}; pass an address from desktop()")
    if p < KEV_GATE:
        raise ResolveError(f"no confident match for {q!r} (kev best guess {p:.0%} < {KEV_GATE:.0%}: "
                           f"{describe(c)[:50]}). The app may not be open — check desktop() or launch it.")
    return c, f" [kev: {p:.0%} in {ms}ms]"
