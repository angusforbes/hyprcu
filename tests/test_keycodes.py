"""Keycode allocation for the virtual keyboard.

Regression: wtype-style numbering (1, 2, 3... by first appearance) put
punctuation on evdev Escape/Backspace/Tab, and Chromium derives punctuation's
key identity from the evdev code, so '/abc' typed 'abc' and 'abcdefghijklm-z'
typed 'abcdefghijklz' (the '-' arrived as Backspace and deleted the 'm').
"""

import pytest

from hyprcu import wire

# evdev codes whose US meaning is a non-character key
NON_CHARACTER = {1, 14, 15, 28, 29, 42, 54, 56, 58, 97, 100, 125, 126}


def codes_for(text: str) -> dict[str, int]:
    return wire._keymap_for(list(dict.fromkeys(text)))[1]


@pytest.mark.parametrize(
    "text", ["/abc", ".abc", "abcdefghijklm-z", "abcdefghijklmn-z", "file:///tmp/a-b/c.html"]
)
def test_printable_characters_never_land_on_non_character_keys(text):
    codes = codes_for(text)
    assert not set(codes.values()) & NON_CHARACTER


def test_characters_use_their_real_us_key():
    codes = codes_for("/-.a1")
    assert codes == {"/": 53, "-": 12, ".": 52, "a": 30, "1": 2}


def test_shared_key_goes_to_a_spare_character_key():
    codes = codes_for("aA1!")
    assert codes["a"] == 30 and codes["1"] == 2
    assert codes["A"] in wire._PRINTABLE_CODES and codes["A"] not in (30, 2)
    assert len(set(codes.values())) == 4


def test_newline_and_tab_are_their_named_keys():
    codes = codes_for("a\nb\tc")
    assert codes["\n"] == 28 and codes["\t"] == 15
    km = wire._keymap_for(["\n", "x"])[0].decode()
    assert "Return" in km


def test_unicode_goes_on_character_keys():
    codes = codes_for("héllo→")
    assert not set(codes.values()) & NON_CHARACTER
    assert len(set(codes.values())) == len(codes)


def test_long_unicode_text_is_split_into_segments():
    text = "".join(chr(0x4E00 + i) for i in range(120))  # 120 distinct CJK chars
    segs = wire.text_segments(text)
    assert "".join(segs) == text
    assert len(segs) >= 3
    for seg in segs:
        wire._keymap_for(list(dict.fromkeys(seg)))  # each fits: does not raise


def test_short_text_is_one_segment():
    assert wire.text_segments("hello-world/") == ["hello-world/"]


def test_combo_keys_on_real_codes():
    _km, codes = wire._keymap_for_combo("minus", ["ctrl"])
    assert codes == {"M_ctrl": 29, "KEY": 12}
    _km, codes = wire._keymap_for_combo("Return", [])
    assert codes == {"KEY": 28}
    _km, codes = wire._keymap_for_combo("l", ["ctrl", "shift"])
    assert codes == {"M_ctrl": 29, "M_shift": 42, "KEY": 38}


def test_combo_unknown_keysym_goes_on_character_key():
    _km, codes = wire._keymap_for_combo("XF86Launch5", [])
    assert codes["KEY"] in wire._PRINTABLE_CODES
    _km, codes = wire._keymap_for_combo("XF86AudioPlay", [])
    assert codes == {"KEY": 164}


def test_allocator_raises_when_pool_exhausted():
    items = [(str(i), None) for i in range(len(wire._PRINTABLE_CODES) + 1)]
    with pytest.raises(wire.KeycodesExhausted):
        wire.allocate_codes(items)
