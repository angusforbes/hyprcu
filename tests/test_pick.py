"""pick.resolve: address → substring → kev, with kev stubbed."""
import pytest

from hyprcu import pick

WS = {"name": "1"}


def _win(address, title, cls="chromium", workspace=WS):
    return {"address": address, "class": cls, "title": title,
            "mapped": True, "workspace": workspace}


C = [
    _win("0xa1", "Strata", cls="io.github.lgse.Strata"),
    _win("0xb2", "tictactoe - Google Search - Chromium"),
    _win("0xc3", "YouTube - Chromium"),
    _win("0xd4", "agf@omarchy:~", cls="foot"),
]


def test_address_exact():
    c, note = pick.resolve("0xd4", C)
    assert c["address"] == "0xd4" and note == ""


def test_malformed_address_is_still_an_address():
    with pytest.raises(pick.ResolveError, match="not found"):
        pick.resolve("0xzz", C)


def test_unique_substring_no_kev(monkeypatch):
    monkeypatch.setattr(
        pick, "_kev",
        lambda q, cs: (_ for _ in ()).throw(AssertionError("kev must not be called")),
    )
    c, note = pick.resolve("strata", C)
    assert c["address"] == "0xa1" and note == ""


def test_ambiguous_substring_kev_breaks_tie(monkeypatch):
    monkeypatch.setattr(
        pick, "_kev_full",
        lambda q, cs: (cs[1], 0.9, 100,
                       {cs[0]["address"]: 0.1, cs[1]["address"]: 0.9}),
    )
    c, note = pick.resolve("chromium", C)
    assert c["address"] == "0xc3" and "of 2 matches" in note


def test_ambiguous_substring_margin_beats_low_absolute(monkeypatch):
    # 8-way split: winner at 0.30, runner-up 0.12 → clear margin, accept despite < gate
    probs = {c["address"]: 0.12 for c in C}
    probs["0xd4"] = 0.30
    monkeypatch.setattr(
        pick, "_kev_full",
        lambda q, cs: (next(x for x in cs if x["address"] == "0xd4"), 0.30, 100, probs),
    )
    c, note = pick.resolve("a", C)   # 'a' is a substring of every title here
    assert c["address"] == "0xd4"


def test_ambiguous_substring_flat_split_is_actionable(monkeypatch):
    probs = {c["address"]: 0.25 for c in C}
    monkeypatch.setattr(pick, "_kev_full", lambda q, cs: (cs[0], 0.25, 100, probs))
    with pytest.raises(pick.ResolveError, match="matches 3 windows"):
        pick.resolve("a", C)


def test_natural_language_above_gate(monkeypatch):
    monkeypatch.setattr(
        pick, "_kev",
        lambda q, cs: (next(x for x in cs if x["address"] == "0xa1"), 0.97, 180),
    )
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