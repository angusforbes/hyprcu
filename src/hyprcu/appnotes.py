"""Per-app interaction notes, surfaced when a tool touches that app.

Agents relearn every app from scratch: which window needs fullscreen, which
command takes an argument, what to verify, what the owner has forbidden.
This keeps that knowledge in plain markdown files, one per app, and makes
hyprcu point at the right file the first time a session touches the app.

  HYPRCU_APP_NOTES   directory of notes (default ~/.pi/agent/notes/apps)
  HYPRCU_APP_NOTES=0 disable

A notes file starts with a small front-matter block; `class` and `title`
are Python regexes matched (case-insensitively, `search`) against the
Hyprland client:

    ---
    app: WhatsApp
    class: ^chrome-web\\.whatsapp\\.com
    title: whatsapp
    launch: omarchy-launch-webapp https://web.whatsapp.com/
    ---
    ## Owner rules
    - Ask before sending any message.
    ...

Files starting with `_` (e.g. `_general.md`) are general rules, not apps.
The `## Owner rules` section is inlined into the hint, so even an agent that
never opens the file sees the owner's rules.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_DIR = os.environ.get("HYPRCU_APP_NOTES", str(Path.home() / ".pi/agent/notes/apps"))
ENABLED = _DIR not in ("0", "", "off", "false")
_RULES_MAX = 700

_seen: set[str] = set()  # apps already hinted this server process (= agent session)


def notes_dir() -> Path:
    return Path(_DIR)


def _parse(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text()
    except OSError:
        return None
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return None
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            meta[k.strip()] = v.strip()
    meta["path"] = str(path)
    meta["body"] = m.group(2)
    meta.setdefault("app", path.stem)
    return meta


def all_notes() -> list[dict[str, Any]]:
    if not ENABLED or not notes_dir().is_dir():
        return []
    out = []
    for p in sorted(notes_dir().glob("*.md")):
        if p.name.startswith("_"):
            continue
        n = _parse(p)
        if n and (n.get("class") or n.get("title")):
            out.append(n)
    return out


def _search(pattern: str, value: str) -> bool:
    try:
        return bool(re.search(pattern, value or "", re.I))
    except re.error:
        return False


def match(client: dict[str, Any] | None) -> dict[str, Any] | None:
    """The notes for a Hyprland client: class match wins, then title."""
    if not client:
        return None
    notes = all_notes()
    cls, title = client.get("class", ""), client.get("title", "")
    for n in notes:
        if n.get("class") and _search(n["class"], cls):
            return n
    for n in notes:
        if n.get("title") and _search(n["title"], title) and not n.get("class"):
            return n
    return None


def rules(note: dict[str, Any]) -> str:
    m = re.search(r"^## Owner rules\s*\n(.*?)(?=^## |\Z)", note.get("body", ""), re.S | re.M)
    r = (m.group(1).strip() if m else "")
    return r if len(r) <= _RULES_MAX else r[:_RULES_MAX].rsplit("\n", 1)[0] + "\n…"


def hint(client: dict[str, Any] | None) -> str:
    """A one-time pointer to the app's notes (empty after the first time
    this session, or when no notes match)."""
    n = match(client)
    if not n or n["path"] in _seen:
        return ""
    _seen.add(n["path"])
    r = rules(n)
    out = f"[app notes: {n['app']}: read {n['path']} before acting further"
    general = notes_dir() / "_general.md"
    if general.exists():
        out += f"; general rules: {general}"
    out += "]"
    if r:
        out += f"\nOwner rules for {n['app']}:\n{r}"
    return out


def reset() -> None:
    _seen.clear()


def lookup(app: str) -> str:
    """Full notes for an app (name/file stem, case-insensitive), or an index."""
    notes = all_notes()
    if not app:
        if not notes:
            return f"no app notes in {notes_dir()}"
        lines = [f"App notes in {notes_dir()} (pass app=<name> for one):"]
        for n in notes:
            lines.append(f"- {n['app']}: class={n.get('class', '')!r} title={n.get('title', '')!r}")
        g = notes_dir() / "_general.md"
        if g.exists():
            lines.append(f"- general rules for every app: {g}")
        return "\n".join(lines)
    a = app.lower()
    for n in notes:
        if a in (n["app"].lower(), Path(n["path"]).stem.lower()):
            return Path(n["path"]).read_text()
    if a in ("general", "_general") and (notes_dir() / "_general.md").exists():
        return (notes_dir() / "_general.md").read_text()
    return f"no notes for {app!r}; call app_notes() for the index"
