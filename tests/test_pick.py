"""pick.resolve: address → substring → kev, with kev stubbed."""
import json

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
    with pytest.raises(pick.ResolveError, match="kev chooser is unreachable"):
        pick.resolve("the file browser", C)


# --- chooser backends and control choice ------------------------------------


def _fake_urlopen(answer, seen):
    import io
    import json as _json

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        seen.append((req.full_url, dict(req.headers), _json.loads(req.data)))
        return R(_json.dumps({"answers": {"q": answer}}).encode())

    return urlopen


def test_jev_backend_sends_key_and_none_option(monkeypatch):
    seen = []
    monkeypatch.setenv("HYPRCU_CHOOSER", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k-test")
    ans = {"choice": "0xa1", "probabilities": {"0xa1": 0.9, "NONE": 0.1}}
    monkeypatch.setattr(pick.urllib.request, "urlopen", _fake_urlopen(ans, seen))
    c, note = pick.resolve("the file browser", C)
    assert c["address"] == "0xa1" and note.startswith(" [jev: 90%")
    url, headers, body = seen[0]
    assert url == pick.JEV_URL and headers["Authorization"] == "Bearer k-test"
    assert body["model"] == pick.JEV_MODEL
    assert "NONE" in body["questions"]["q"]["criteria"]


def test_jev_none_is_an_actionable_abstention(monkeypatch):
    monkeypatch.setenv("HYPRCU_CHOOSER", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k-test")
    ans = {"choice": "NONE", "probabilities": {"0xa1": 0.1, "NONE": 0.9}}
    monkeypatch.setattr(pick.urllib.request, "urlopen", _fake_urlopen(ans, []))
    with pytest.raises(pick.ResolveError, match="no open window matches"):
        pick.resolve("my email client", C)


def test_jev_without_key_is_unreachable_not_a_crash(monkeypatch):
    monkeypatch.setenv("HYPRCU_CHOOSER", "jev")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(pick.ResolveError, match="jev chooser is unreachable"):
        pick.resolve("the file browser", C)


def test_kev_backend_has_no_none_option(monkeypatch):
    seen = []
    monkeypatch.setenv("HYPRCU_CHOOSER", "kev")
    ans = {"choice": "0xa1", "probabilities": {"0xa1": 0.8}}
    monkeypatch.setattr(pick.urllib.request, "urlopen", _fake_urlopen(ans, seen))
    pick.resolve("the file browser", C)
    url, headers, body = seen[0]
    assert url == pick.KEV_URL and "Authorization" not in headers
    assert "NONE" not in body["questions"]["q"]["criteria"]


CONTROLS = [
    {"role": "button", "name": "Back", "x": 48, "y": 107, "clickable": True},
    {"role": "link", "name": "Back home", "x": 81, "y": 395, "clickable": True, "in_page": True},
    {
        "role": "button",
        "name": "Send message",
        "x": 102,
        "y": 369,
        "clickable": True,
        "in_page": True,
    },
    {"role": "button", "name": "Hidden", "x": 1, "y": 1, "clickable": False},
]


def test_choose_control_labels_page_vs_toolbar_and_skips_unclickable(monkeypatch):
    seen = []
    monkeypatch.setenv("HYPRCU_CHOOSER", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k-test")
    ans = {"choice": "c2", "probabilities": {"c2": 0.95}}
    monkeypatch.setattr(pick.urllib.request, "urlopen", _fake_urlopen(ans, seen))
    e, note = pick.choose_control("submit the form", CONTROLS)
    assert e["name"] == "Send message" and "jev: 95%" in note
    crit = seen[0][2]["questions"]["q"]["criteria"]
    assert crit["c0"] == 'button "Back" (browser toolbar or tab strip)'
    assert crit["c1"] == 'link "Back home" (web page)'
    assert "Hidden" not in json.dumps(crit)


def test_choose_control_none_and_low_confidence_refuse(monkeypatch):
    monkeypatch.setenv("HYPRCU_CHOOSER", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k-test")
    for ans, msg in (
        ({"choice": "NONE", "probabilities": {"NONE": 0.9}}, "no control does"),
        ({"choice": "c0", "probabilities": {"c0": 0.3}}, "not sure which control"),
    ):
        monkeypatch.setattr(pick.urllib.request, "urlopen", _fake_urlopen(ans, []))
        with pytest.raises(pick.ResolveError, match=msg):
            pick.choose_control("log out", CONTROLS)
