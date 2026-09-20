"""pick.resolve: address → substring → kev, with kev stubbed."""
import pytest
from hypruse import pick

WS = {"name": "1"}
C = [
    {"address": "0xa1", "class": "io.github.lgse.Strata", "title": "Strata", "mapped": True, "workspace": WS},
    {"address": "0xb2", "class": "chromium", "title": "tictactoe - Google Search - Chromium", "mapped": True, "workspace": WS},
    {"address": "0xc3", "class": "chromium", "title": "YouTube - Chromium", "mapped": True, "workspace": WS},
    {"address": "0xd4", "class": "foot", "title": "agf@omarchy:~", "mapped": True, "workspace": WS},
]

def test_address_exact():
    c, note = pick.resolve("0xd4", C); assert c["address"] == "0xd4" and note == ""

def test_malformed_address_is_still_an_address():
    with pytest.raises(pick.ResolveError, match="not found"):
        pick.resolve("0xzz", C)

def test_unique_substring_no_kev(monkeypatch):
    monkeypatch.setattr(pick, "_kev", lambda q, cs: (_ for _ in ()).throw(AssertionError("kev must not be called")))
    c, note = pick.resolve("strata", C); assert c["address"] == "0xa1" and note == ""

def test_ambiguous_substring_kev_breaks_tie(monkeypatch):
    monkeypatch.setattr(pick, "_kev", lambda q, cs: (cs[1], 0.9, 100))
    c, note = pick.resolve("chromium", C)
    assert c["address"] == "0xc3" and "of 2 matches" in note

def test_natural_language_above_gate(monkeypatch):
    monkeypatch.setattr(pick, "_kev", lambda q, cs: (next(x for x in cs if x["address"]=="0xa1"), 0.97, 180))
    c, note = pick.resolve("the file browser", C)
    assert c["address"] == "0xa1" and "[kev: 97% in 180ms]" in note

def test_natural_language_below_gate_is_actionable(monkeypatch):
    monkeypatch.setattr(pick, "_kev", lambda q, cs: (cs[0], 0.31, 180))
    with pytest.raises(pick.ResolveError, match="31% < 50%.*not be open"):
        pick.resolve("slack", C)

def test_kev_unreachable_is_actionable(monkeypatch):
    monkeypatch.setattr(pick, "_kev", lambda q, cs: (None, 0.0, 0))
    with pytest.raises(pick.ResolveError, match="kev is unreachable"):
        pick.resolve("the file browser", C)
