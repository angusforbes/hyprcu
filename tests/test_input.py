import pytest

from hyprcu import input as hinput


def test_parse_combo_mods_and_key():
    assert hinput.parse_combo("ctrl+shift+t") == (["ctrl", "shift"], "t")
    assert hinput.parse_combo("super+enter") == (["logo"], "Return")
    assert hinput.parse_combo("Alt+F4") == (["alt"], "F4")
    assert hinput.parse_combo("esc") == ([], "Escape")
    assert hinput.parse_combo("q") == ([], "q")


def test_parse_combo_bare_modifier_tap():
    assert hinput.parse_combo("super") == (["logo"], None)


def test_parse_combo_passes_unknown_keysyms_through():
    assert hinput.parse_combo("XF86AudioPlay") == ([], "XF86AudioPlay")


def test_parse_combo_rejects_garbage():
    with pytest.raises(hinput.InputError):
        hinput.parse_combo("")
    with pytest.raises(hinput.InputError, match="unknown modifier"):
        hinput.parse_combo("banana+t")


def test_combo_to_wtype_args_press_release_order():
    args = hinput.combo_to_wtype_args(["ctrl", "shift"], "t")
    assert args == ["-M", "ctrl", "-M", "shift", "-k", "t", "-m", "shift", "-m", "ctrl"]
    assert hinput.combo_to_wtype_args(["logo"], None) == ["-M", "logo", "-m", "logo"]


def test_click_validates_before_touching_compositor():
    with pytest.raises(hinput.InputError, match="both x and y"):
        hinput.click(x=100)  # y missing, must fail before any socket use
    with pytest.raises(hinput.InputError, match="unknown button"):
        hinput.click(button="laser")


def test_scroll_requires_a_direction():
    with pytest.raises(hinput.InputError, match="non-zero"):
        hinput.scroll()


class FakeVP:
    # not on a named seat, so positioning falls back to the compositor the
    # way it does in a default single-seat session (see input.move)
    on_named_seat = False

    def __init__(self):
        self.events = []

    def button(self, button, state):
        self.events.append((button, state))

    def move_to(self, x, y):  # drag sends real motion from its own pointer
        pass


def test_drag_tracks_and_clears_held_button(monkeypatch):
    vp = FakeVP()
    seen = []
    monkeypatch.setattr(hinput, "_vp", vp)
    # every motion observes the flag: this is what a SIGTERM landing mid-drag
    # would see, so it must read "left" for the entire hold
    vp.move_to = lambda x, y: seen.append(hinput._held_button)
    monkeypatch.setattr(hinput.time, "sleep", lambda s: None)
    hinput.drag(0, 0, 10, 10)
    from hyprcu.wire import PRESSED, RELEASED

    assert vp.events == [("left", PRESSED), ("left", RELEASED)]
    assert hinput._held_button is None
    # the placement motion, then 20 path motions and 3 hover motions, all held
    assert seen[0] is None and seen[1:] == ["left"] * 23


def test_concurrent_drags_never_interleave(monkeypatch):
    # MCP hosts can issue tool calls in parallel and sync tools run on
    # worker threads: the seat lock must keep each drag's press/move/release
    # atomic on the shared virtual pointer
    import threading

    from hyprcu.wire import PRESSED, RELEASED

    vp = FakeVP()
    monkeypatch.setattr(hinput, "_vp", vp)
    monkeypatch.setattr(hinput.hyprctl, "dispatch", lambda *a: None)
    monkeypatch.setattr(hinput.time, "sleep", lambda s: None)
    threads = [threading.Thread(target=lambda: hinput.drag(0, 0, 5, 5)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [s for _, s in vp.events] == [PRESSED, RELEASED] * 4


def test_release_held_releases_mid_drag_state(monkeypatch):
    # the state a SIGTERM would see if it lands between press and release
    from hyprcu.wire import RELEASED

    vp = FakeVP()
    monkeypatch.setattr(hinput, "_vp", vp)
    monkeypatch.setattr(hinput, "_held_button", "left")
    hinput.release_held()
    assert vp.events == [("left", RELEASED)]
    assert hinput._held_button is None
    hinput.release_held()  # idempotent: nothing held, nothing sent
    assert vp.events == [("left", RELEASED)]


# --- modifier + pointer --------------------------------------------------------


def test_parse_mods_forms():
    assert hinput.parse_mods("") == []
    assert hinput.parse_mods(None) == []
    assert hinput.parse_mods("ctrl") == ["ctrl"]
    assert hinput.parse_mods("Ctrl+Shift") == ["ctrl", "shift"]
    assert hinput.parse_mods(["control", "super"]) == ["ctrl", "logo"]
    assert hinput.parse_mods("ctrl+ctrl") == ["ctrl"]  # deduplicated


def test_parse_mods_rejects_unknown_and_non_modifiers():
    with pytest.raises(hinput.InputError, match="unknown modifier"):
        hinput.parse_mods("banana")
    with pytest.raises(hinput.InputError, match="unknown modifier"):
        hinput.parse_mods("ctrl+t")  # a key is not a modifier to hold


def test_click_bad_modifier_fails_before_touching_compositor():
    with pytest.raises(hinput.InputError, match="unknown modifier"):
        hinput.click(modifiers="hyper")


class FakeVK:
    def __init__(self, log):
        self.log = log

    def press_mods(self, mods):
        self.log.append(("press_mods", list(mods)))
        return ("handle", list(mods))

    def release_mods(self, handle):
        self.log.append(("release_mods", handle[1]))


class LoggingVP(FakeVP):
    def __init__(self, log):
        super().__init__()
        self.log = log

    def click(self, button, double=False):
        self.log.append(("click", button))


def _wire_fakes(monkeypatch):
    log = []
    monkeypatch.setattr(hinput, "_vp", LoggingVP(log))
    monkeypatch.setattr(hinput, "_vk", FakeVK(log))
    monkeypatch.setattr(hinput.time, "sleep", lambda s: None)
    monkeypatch.setattr(hinput.hyprctl, "dispatch", lambda *a: None)
    return log


def test_modifier_click_holds_mods_around_the_click(monkeypatch):
    log = _wire_fakes(monkeypatch)
    hinput.click(10, 20, modifiers="ctrl+shift")
    assert log == [
        ("press_mods", ["ctrl", "shift"]),
        ("click", "left"),
        ("release_mods", ["ctrl", "shift"]),
    ]
    assert hinput._held_mods is None


def test_plain_click_never_touches_the_keyboard(monkeypatch):
    log = _wire_fakes(monkeypatch)
    hinput.click(10, 20)
    assert log == [("click", "left")]


def test_mods_released_even_when_the_click_fails(monkeypatch):
    log = _wire_fakes(monkeypatch)

    def boom(button, double=False):
        raise RuntimeError("pointer died")

    hinput._vp.click = boom
    with pytest.raises(RuntimeError):
        hinput.click(modifiers="ctrl")
    assert log == [("press_mods", ["ctrl"]), ("release_mods", ["ctrl"])]
    assert hinput._held_mods is None


def test_release_held_releases_mid_click_modifiers(monkeypatch):
    # what a SIGTERM would see between press_mods and release_mods: a stuck ctrl
    # would turn every later keystroke of the human's into a shortcut
    log = _wire_fakes(monkeypatch)
    monkeypatch.setattr(hinput, "_held_mods", ("handle", ["ctrl"]))
    hinput.release_held()
    assert log == [("release_mods", ["ctrl"])]
    assert hinput._held_mods is None
