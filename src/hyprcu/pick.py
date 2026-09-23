"""Natural-language window (and control) selection via a System One chooser:
Jev (TypeSafe cloud) or a local kev (Jev-compatible) server.

`window` arguments across the server accept three forms:
  - an address       "0x561283a8e870"        → exact
  - a substring      "Strata", "Slack"       → case-insensitive on class/title
  - a description    "the file browser"      → chooser over open windows

The chokepoint is `resolve()`. It returns (client, note) where note is "" or
" [jev: NN% in Nms]" for the caller to append to its result text.
`choose_control()` does the same for a window's accessible controls, so
click_ui can take "submit the form" as well as "Send message".

Env:
  HYPRCU_CHOOSER  jev (default) | kev. Jev sends window titles and control
                  names to TypeSafe's API and needs TYPESAFE_API_KEY; kev is
                  the local, offline alternative. Measured (tools/choice_bench.py,
                  29 synthetic queries): Jev with an explicit NONE option 28/29 at
                  ~0.6 s; kev-4b 25/29 at 1.7-2.8 s (grows with option count).
  TYPESAFE_API_KEY  required for jev (read from the environment only)
  JEV_URL / JEV_MODEL  default https://api.typesafe.ai/v1/systemone, jev-latest
  KEV_URL   default http://127.0.0.1:8009/v1/systemone  (kev, openjev…)
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
KEV_TIMEOUT_S = 6.0  # kev-4b NF4 takes ~2.8 s for ~20 options on the laptop GPU
JEV_URL = os.environ.get("JEV_URL", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL = os.environ.get("JEV_MODEL", "jev-latest")
JEV_TIMEOUT_S = 8.0
NONE = "NONE"  # the explicit abstain option offered to Jev
# resolve() sentinel: the chooser answered "none of these" (distinct from unreachable)
ABSTAINED: dict[str, Any] = {"address": NONE}


def chooser() -> str:
    """The configured backend, read per call so tests/env changes apply."""
    return "kev" if os.environ.get("HYPRCU_CHOOSER", "jev").strip().lower() == "kev" else "jev"


def _unreachable(what: str) -> str:
    """Why the chooser could not answer, and what to do about it."""
    if chooser() == "jev" and not os.environ.get("TYPESAFE_API_KEY"):
        return (
            f"{what} and the jev chooser is unreachable: TYPESAFE_API_KEY is not set "
            "(get a key from TypeSafe, or set HYPRCU_CHOOSER=kev for the local model)"
        )
    return f"{what} and the {chooser()} chooser is unreachable at {backend_url()}"


def backend_url() -> str:
    return JEV_URL if chooser() == "jev" else KEV_URL


def choose(
    state: str, instructions: str, criteria: dict[str, str], none_label: str = ""
) -> dict[str, Any] | None:
    """One System One choice. With Jev and a none_label, offers an explicit
    NONE option (Jev abstains well with one; kev over-abstains, so kev keeps the
    probability gate instead). Returns {backend, choice, p, ms, probs}, or None
    when the backend is unreachable or misconfigured."""
    backend = chooser()
    crit = dict(criteria)
    if backend == "jev" and none_label:
        crit[NONE] = none_label
        instructions += " If none of them fits, choose NONE."
    headers = {"content-type": "application/json"}
    if backend == "jev":
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if not key:
            return None
        headers["authorization"] = f"Bearer {key}"
    body = {
        "model": JEV_MODEL if backend == "jev" else "kev",
        "state": state,
        "questions": {"q": {"type": "choice", "instructions": instructions, "criteria": crit}},
    }
    req = urllib.request.Request(backend_url(), json.dumps(body).encode(), headers)
    t0 = time.time()
    try:
        timeout = JEV_TIMEOUT_S if backend == "jev" else KEV_TIMEOUT_S
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ans = json.load(r)["answers"]["q"]
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError, TimeoutError):
        return None
    probs = {k: float(v) for k, v in ans["probabilities"].items()}
    return {
        "backend": backend,
        "choice": ans["choice"],
        "p": probs.get(ans["choice"], 0.0),
        "ms": int((time.time() - t0) * 1000),
        "probs": probs,
    }

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
    if not ws:
        where = ""
    elif str(ws).startswith("special"):
        where = " (scratchpad)"
    else:
        where = f" (workspace {ws})"
    return f"{t} — {APP_HINTS.get(c.get('class', ''), c.get('class', ''))}{where}"


def _kev(query: str, clients: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float, int]:
    c, p, ms, _ = _kev_full(query, clients, allow_none=True)
    return c, p, ms


def _kev_full(
    query: str, clients: list[dict[str, Any]], allow_none: bool = False
) -> tuple[dict[str, Any] | None, float, int, dict[str, float]]:
    """(chosen client, probability, ms, all probabilities) from the chooser.

    (None, 0, 0, {}) if the chooser is unreachable; (ABSTAINED, p, ms, probs)
    when allow_none and it answered "none of these". (Name kept from the
    kev-only days; it uses whichever backend chooser() selects.)
    """
    if not clients:
        return None, 0.0, 0, {}
    if len(clients) == 1 and not allow_none:
        return clients[0], 1.0, 0, {clients[0]["address"]: 1.0}
    ans = choose(
        f'The user wants to interact with: "{query}"',
        "Which open window best matches what the user described?",
        {c["address"]: describe(c) for c in clients},
        none_label="None of the open windows match this description" if allow_none else "",
    )
    if ans is None:
        return None, 0.0, 0, {}
    if ans["choice"] == NONE:
        return ABSTAINED, ans["p"], ans["ms"], ans["probs"]
    client = next((c for c in clients if c["address"] == ans["choice"]), None)
    return client, ans["p"], ans["ms"], ans["probs"]


def resolve(window: str, clients: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Address → substring → kev. Raises ResolveError with an actionable message."""
    q = window.strip()
    if _ADDR.match(q):
        c = next((c for c in clients if c.get("address") == q), None)
        if c is None:
            raise ResolveError(f"window {q!r} not found, call desktop() for current addresses")
        return c, ""
    ql = q.lower()
    hits = [c for c in clients
            if ql in str(c.get("class", "")).lower() or ql in str(c.get("title", "")).lower()]
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
                return c, f" [{chooser()}: {p:.0%} of {len(hits)} matches, {ms}ms]"
        names = "; ".join(f"{h['address']} {describe(h)[:40]}" for h in hits[:6])
        raise ResolveError(f"{q!r} matches {len(hits)} windows — pass an address: {names}")
    # no substring hit: natural language over visible, mapped windows
    visible = [c for c in clients if c.get("mapped", True)
               and c.get("workspace", {}).get("name") != "special:reprieve"]
    c, p, ms = _kev(q, visible or clients)
    who = chooser()
    if c is None:
        raise ResolveError(
            _unreachable(f"no window matches {q!r}") + "; pass an address from desktop()"
        )
    if c is ABSTAINED:
        raise ResolveError(
            f"no open window matches {q!r} ({who}: none of them, {p:.0%}). "
            "The app may not be open — check desktop() or launch it."
        )
    if p < KEV_GATE:
        raise ResolveError(
            f"no confident match for {q!r} ({who} best guess {p:.0%} < {KEV_GATE:.0%}: "
            f"{describe(c)[:50]}). The app may not be open — check desktop() or launch it."
        )
    return c, f" [{who}: {p:.0%} in {ms}ms]"


def _control_label(e: dict[str, Any], browser: bool) -> str:
    label = f'{e.get("role", "")} "{e.get("name", "")}"'
    if browser:  # lets the chooser tell the browser's Back from a page's "Back home"
        label += " (web page)" if e.get("in_page") else " (browser toolbar or tab strip)"
    for key in ("value", "checked", "percent"):
        if key in e:
            label += f" {key}={e[key]!r}"
    return label


def choose_control(query: str, elements: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Pick the control a description refers to ("submit the form") from a
    window's actionable elements (as returned by server._ui_read). Offers an
    explicit NONE; raises ResolveError when nothing fits, the chooser is
    unsure, or it is unreachable. Returns (element, note)."""
    usable = [e for e in elements if e.get("clickable", True)]
    if not usable:
        raise ResolveError(f"no clickable controls to match {query!r} against")
    browser = any(e.get("in_page") for e in usable)
    ans = choose(
        f'The user asked: "{query}"',
        "Which control should be activated to do what the user asked?",
        {f"c{i}": _control_label(e, browser) for i, e in enumerate(usable)},
        none_label="No control in this window does what the user asked",
    )
    who = chooser()
    if ans is None:
        raise ResolveError(
            _unreachable(f"no control is named {query!r}") + "; call ui() and click by exact name"
        )
    if ans["choice"] == NONE:
        raise ResolveError(
            f"no control does {query!r} ({who}: none of them, {ans['p']:.0%}); "
            "call ui() to see them"
        )
    if ans["p"] < KEV_GATE:
        raise ResolveError(
            f"not sure which control does {query!r} ({who} best guess {ans['p']:.0%}); "
            "call ui() and click by exact name"
        )
    e = usable[int(ans["choice"][1:])]
    return e, f" [{who}: {ans['p']:.0%} in {ans['ms']}ms]"
