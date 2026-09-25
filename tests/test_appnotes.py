"""Per-app notes: matching, the one-time hint, owner-rules inlining, lookup,
and the registration wrapper that appends the hint to tool results."""

from hyprcu import appnotes, server

WA = """---
app: WhatsApp
class: ^chrome-web\\.whatsapp\\.com
launch: omarchy-launch-webapp https://web.whatsapp.com/
---
## Owner rules
- Ask Angus before sending any message.

## Recipes
- fullscreen first
"""


def _write(tmp_path, monkeypatch, name="whatsapp.md", text=WA):
    d = tmp_path / "notes"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text)
    monkeypatch.setattr(appnotes, "_DIR", str(d))
    appnotes.reset()
    return d


def test_match_by_class_and_hint_once(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    wa = {"class": "chrome-web.whatsapp.com__-Default", "title": "WhatsApp"}
    h = appnotes.hint(wa)
    assert "whatsapp.md" in h and "Ask Angus before sending" in h
    assert appnotes.hint(wa) == ""  # once per session
    assert appnotes.hint({"class": "foot", "title": "x"}) == ""


def test_title_only_notes_and_general_pointer(tmp_path, monkeypatch):
    d = _write(tmp_path, monkeypatch, "matlab.md", "---\napp: MATLAB\ntitle: MATLAB Online\n---\nbody\n")
    (d / "_general.md").write_text("general")
    h = appnotes.hint({"class": "chromium", "title": "MATLAB Online R2026a - Chromium"})
    assert "MATLAB" in h and "_general.md" in h


def test_lookup_index_and_app(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    assert "WhatsApp" in appnotes.lookup("")
    assert "fullscreen first" in appnotes.lookup("whatsapp")
    assert "no notes" in appnotes.lookup("slack")


def test_bad_regex_and_missing_dir_are_harmless(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "bad.md", "---\napp: Bad\nclass: ([\n---\n")
    assert appnotes.hint({"class": "([", "title": ""}) == ""
    monkeypatch.setattr(appnotes, "_DIR", str(tmp_path / "nope"))
    assert appnotes.lookup("") .startswith("no app notes")


def test_wrapper_appends_hint_to_each_result_type(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    client = {"address": "0xwa", "class": "chrome-web.whatsapp.com__-Default", "title": "WhatsApp"}
    monkeypatch.setattr(server.hyprctl, "query", lambda what: [client] if what == "clients" else {"address": "0xwa"})

    def keyboard(action="", window=""):
        return "typed"
    out = server._with_app_notes(keyboard)(action="type", window="0xwa")
    assert out.startswith("typed\n[app notes: WhatsApp")
    assert server._with_app_notes(keyboard)(action="type", window="0xwa") == "typed"  # once

    appnotes.reset()

    def launch(command=""):
        return {"address": "0xwa"}
    assert "app_notes" in server._with_app_notes(launch)(command="x")


def test_wrapper_never_breaks_the_tool(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    def boom(what):
        raise RuntimeError("hyprctl down")
    monkeypatch.setattr(server.hyprctl, "query", boom)

    def keyboard(action="", window=""):
        return "typed"
    assert server._with_app_notes(keyboard)(action="type", window="0xwa") == "typed"
