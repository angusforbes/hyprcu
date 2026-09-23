"""Minimal Wayland client speaking zwlr_virtual_pointer_unstable_v1.

hyprcu injects pointer input by being a regular Wayland client of the
user's compositor, the same mechanism wlrctl uses, rather than a uinput
daemon (ydotool) or the RemoteDesktop portal (which
xdg-desktop-portal-hyprland does not implement). Nothing here needs root,
/dev/uinput access, or a background service.

Wire format, little-endian:
    message: u32 object-id, u32 (size << 16 | opcode), args
    string:  u32 length (incl. NUL), bytes, NUL, pad to 4
    fixed:   signed 24.8 fixed point

Opcodes match the protocol XML shipped in Hyprland's own tree
(protocols/wlr-virtual-pointer-unstable-v1.xml).
"""

from __future__ import annotations

import os
import socket
import struct
import tempfile
import time

DISPLAY_ID = 1
# wl_display requests
REQ_SYNC, REQ_GET_REGISTRY = 0, 1
# wl_display events
EV_ERROR, EV_DELETE_ID = 0, 1
# zwlr_virtual_pointer_manager_v1 requests
MGR_CREATE_POINTER, MGR_DESTROY = 0, 1
# zwlr_virtual_pointer_v1 requests
PTR_MOTION, PTR_MOTION_ABSOLUTE, PTR_BUTTON, PTR_AXIS, PTR_FRAME = 0, 1, 2, 3, 4
PTR_AXIS_SOURCE, PTR_AXIS_STOP, PTR_AXIS_DISCRETE, PTR_DESTROY = 5, 6, 7, 8

MANAGER_INTERFACE = "zwlr_virtual_pointer_manager_v1"
SEAT_INTERFACE = "wl_seat"
SEAT_EV_NAME = 1

# Multi-seat: when HYPRCU_SEAT names a seat, the virtual pointer is created ON
# that seat instead of the compositor default. Requires a compositor that
# advertises more than one wl_seat; on stock Hyprland this finds nothing and we
# fall back to the default seat, so the variable is safe to leave set.
SEAT_ENV = "HYPRCU_SEAT"

BUTTONS = {
    "left": 0x110,
    "right": 0x111,
    "middle": 0x112,
    "back": 0x113,
    "forward": 0x114,
}
PRESSED, RELEASED = 1, 0
AXIS_VERTICAL, AXIS_HORIZONTAL = 0, 1
AXIS_SOURCE_WHEEL = 0
SCROLL_UNITS_PER_NOTCH = 15.0  # touchpad-coordinate length of one wheel notch


class WireError(RuntimeError):
    """Protocol error or unusable compositor connection."""


# --- pure wire helpers -----------------------------------------------------


def wl_string(s: str) -> bytes:
    raw = s.encode() + b"\x00"
    pad = (4 - len(raw) % 4) % 4
    return struct.pack("<I", len(raw)) + raw + b"\x00" * pad


def to_fixed(value: float) -> int:
    """Wayland signed 24.8 fixed point."""
    return int(round(value * 256))


def encode_msg(obj: int, opcode: int, body: bytes = b"") -> bytes:
    size = 8 + len(body)
    return struct.pack("<II", obj, (size << 16) | opcode) + body


def parse_events(buf: bytes) -> tuple[list[tuple[int, int, bytes]], bytes]:
    """Split a byte stream into complete (object, opcode, body) events + remainder."""
    events = []
    while len(buf) >= 8:
        obj, sizeop = struct.unpack_from("<II", buf, 0)
        size, opcode = sizeop >> 16, sizeop & 0xFFFF
        if size < 8 or len(buf) < size:
            break
        events.append((obj, opcode, buf[8:size]))
        buf = buf[size:]
    return events, buf


def parse_global(body: bytes) -> tuple[int, str, int]:
    """wl_registry.global(name: uint, interface: string, version: uint)."""
    name = struct.unpack_from("<I", body, 0)[0]
    slen = struct.unpack_from("<I", body, 4)[0]
    interface = body[8 : 8 + slen - 1].decode()
    pad = (4 - slen % 4) % 4
    version = struct.unpack_from("<I", body, 8 + slen + pad)[0]
    return name, interface, version


def parse_error(body: bytes) -> tuple[int, int, str]:
    """wl_display.error(object_id: object, code: uint, message: string)."""
    obj, code = struct.unpack_from("<II", body, 0)
    slen = struct.unpack_from("<I", body, 8)[0]
    message = body[12 : 12 + slen - 1].decode(errors="replace")
    return obj, code, message


def _now_ms() -> int:
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


def scroll_messages(
    dy: float = 0.0, dx: float = 0.0, discrete_ok: bool = True
) -> list[tuple[int, bytes]]:
    """The (opcode, body) sequence for one wheel scroll. Whole-notch deltas
    go out as axis_discrete (carrying both the continuous value and the
    notch count) so applications that step per wheel click see real
    notches; fractional deltas keep the plain continuous axis event.
    axis_discrete exists only since protocol v2, so callers bound at v1
    pass discrete_ok=False to stay on the continuous path."""
    t = _now_ms()
    msgs = [(PTR_AXIS_SOURCE, struct.pack("<I", AXIS_SOURCE_WHEEL))]
    for axis, v in ((AXIS_VERTICAL, dy), (AXIS_HORIZONTAL, dx)):
        if not v:
            continue
        value = to_fixed(v * SCROLL_UNITS_PER_NOTCH)
        notches = int(round(v))
        if discrete_ok and notches and abs(v - notches) < 1e-6:
            msgs.append((PTR_AXIS_DISCRETE, struct.pack("<IIii", t, axis, value, notches)))
        else:
            msgs.append((PTR_AXIS, struct.pack("<IIi", t, axis, value)))
    msgs.append((PTR_FRAME, b""))
    return msgs


# --- live connection ---------------------------------------------------------


class VirtualPointer:
    """One compositor connection owning one virtual pointer device.

    Cheap to create (~1 ms); the server keeps one alive and recreates it if
    the connection drops. Use as a context manager to guarantee the device
    is destroyed, a leaked virtual pointer lingers in `hyprctl devices`.
    """

    def __init__(self, display: str | None = None):
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        display = display or os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        if not runtime and not display.startswith("/"):
            raise WireError("XDG_RUNTIME_DIR not set, not inside a Wayland session?")
        path = display if display.startswith("/") else os.path.join(runtime, display)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(3.0)
        try:
            self._sock.connect(path)
        except OSError as exc:
            raise WireError(f"cannot connect to Wayland display at {path}: {exc}") from exc
        self._buf = b""
        self._next_id = 2
        self._registry = self._new_id()
        self._send(DISPLAY_ID, REQ_GET_REGISTRY, struct.pack("<I", self._registry))
        globals_seen = self._roundtrip(collect_globals=True)
        match = [(n, v) for n, i, v in globals_seen if i == MANAGER_INTERFACE]
        if not match:
            raise WireError(f"compositor does not advertise {MANAGER_INTERFACE}")
        name, version = match[0]
        # The pointer inherits the manager's negotiated version; axis_discrete
        # only exists since v2, so remember what we actually bound.
        self._version = min(version, 2)
        self._manager = self._new_id()
        self._send(
            self._registry,
            0,  # wl_registry.bind
            struct.pack("<I", name)
            + wl_string(MANAGER_INTERFACE)
            + struct.pack("<II", self._version, self._manager),
        )
        self._globals_cache = globals_seen
        self._seat = self._resolve_seat(globals_seen)
        # tracked cursor position, established lazily by move_to()
        self._pos: tuple[float, float] | None = None

        self._pointer = self._new_id()
        self._send(self._manager, MGR_CREATE_POINTER, struct.pack("<II", self._seat, self._pointer))
        self._roundtrip()

    def _resolve_seat(self, globals_seen: list[tuple[int, str, int]]) -> int:
        """Object id of the requested wl_seat, or 0 for the compositor default.

        zwlr_virtual_pointer_manager_v1.create_virtual_pointer takes the seat the
        device belongs to. hyprcu has always passed 0 (null) because there was
        only ever one seat. Naming one routes this pointer to it, which is how an
        agent gets its own cursor instead of sharing the human's.
        """
        wanted = os.environ.get(SEAT_ENV, "").strip()
        if not wanted:
            return 0

        bound: dict[int, str] = {}
        for name, iface, version in globals_seen:
            if iface != SEAT_INTERFACE:
                continue
            oid = self._new_id()
            self._send(
                self._registry,
                0,
                struct.pack("<I", name)
                + wl_string(SEAT_INTERFACE)
                + struct.pack("<II", min(version, 9), oid),
            )
            bound[oid] = ""

        if not bound:
            return 0

        # names arrive as wl_seat.name events during the next roundtrip
        pending = dict(bound)
        self._seat_names = pending
        self._roundtrip()

        for oid, seat_name in pending.items():
            if seat_name == wanted:
                return oid

        # Fall back rather than fail. The variable is easy to leave set in a shell
        # profile and then use on a compositor with only one seat, where hard
        # failure makes every single call error out for no good reason. Seat 0 is
        # the compositor default, which is what hyprcu always used.
        import warnings

        warnings.warn(
            f"{SEAT_ENV}={wanted!r} but this compositor advertises no such seat "
            f"(saw: {sorted(n for n in pending.values() if n)}); "
            f"using the default seat",
            RuntimeWarning,
            stacklevel=2,
        )
        return 0

    # -- plumbing --

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    def _send(self, obj: int, opcode: int, body: bytes = b"") -> None:
        try:
            self._sock.sendall(encode_msg(obj, opcode, body))
        except OSError as exc:
            raise WireError(f"compositor connection lost: {exc}") from exc

    def _roundtrip(self, collect_globals: bool = False) -> list[tuple[int, str, int]]:
        """Sync barrier: returns once the compositor has processed everything sent."""
        done_cb = self._new_id()
        self._send(DISPLAY_ID, REQ_SYNC, struct.pack("<I", done_cb))
        globals_seen: list[tuple[int, str, int]] = []
        while True:
            try:
                chunk = self._sock.recv(65536)
            except TimeoutError as exc:
                raise WireError("compositor did not answer sync") from exc
            if not chunk:
                raise WireError("compositor closed the connection")
            self._buf += chunk
            events, self._buf = parse_events(self._buf)
            for obj, opcode, body in events:
                if obj == DISPLAY_ID and opcode == EV_ERROR:
                    err_obj, code, msg = parse_error(body)
                    raise WireError(f"wl_display.error object={err_obj} code={code}: {msg}")
                if obj == self._registry and opcode == 0 and collect_globals:
                    globals_seen.append(parse_global(body))
                names = getattr(self, "_seat_names", None)
                if names is not None and obj in names and opcode == SEAT_EV_NAME:
                    slen = struct.unpack_from("<I", body, 0)[0]
                    names[obj] = body[4 : 4 + slen - 1].decode(errors="replace")
                if obj == done_cb and opcode == 0:  # wl_callback.done
                    return globals_seen

    # -- pointer actions --

    @property
    def on_named_seat(self) -> bool:
        """True when this pointer was created on a seat other than the default."""
        return bool(self._seat)

    def move(self, dx: float, dy: float) -> None:
        """Relative motion, in logical pixels."""
        motion = struct.pack("<Iii", _now_ms(), int(dx * 256), int(dy * 256))
        self._send(self._pointer, PTR_MOTION, motion)
        self._send(self._pointer, PTR_FRAME)
        self._roundtrip()
        if self._pos is not None:
            self._pos = (self._pos[0] + dx, self._pos[1] + dy)

    def move_to(self, x: float, y: float) -> None:
        """Absolute positioning, built out of relative motion.

        The compositor's cursor dispatcher cannot be used on a second seat: it moves the
        one global cursor, which is the human's. Relative motion is per device and
        therefore per seat.

        Absolute needs a known origin. The compositor clamps to the output, so a
        large negative sweep parks the cursor at (0, 0) exactly once; after that the
        position is tracked, since nothing else moves this cursor.
        """
        if self._pos is None:
            for _ in range(10):
                self.move(-4000, -4000)
            self._pos = (0.0, 0.0)
        self.move(x - self._pos[0], y - self._pos[1])
        self._pos = (float(x), float(y))

    def button(self, name: str, state: int) -> None:
        code = BUTTONS[name]
        self._send(self._pointer, PTR_BUTTON, struct.pack("<III", _now_ms(), code, state))
        self._send(self._pointer, PTR_FRAME)
        self._roundtrip()

    def click(self, name: str = "left", *, double: bool = False) -> None:
        for i in range(2 if double else 1):
            if i:
                time.sleep(0.06)
            self.button(name, PRESSED)
            time.sleep(0.02)
            self.button(name, RELEASED)

    def scroll(self, dy: float = 0.0, dx: float = 0.0) -> None:
        """Scroll by wheel notches; positive dy scrolls content down."""
        for opcode, body in scroll_messages(dy, dx, discrete_ok=self._version >= 2):
            self._send(self._pointer, opcode, body)
        self._roundtrip()

    def close(self) -> None:
        try:
            self._send(self._pointer, PTR_DESTROY)
            self._send(self._manager, MGR_DESTROY)
            self._roundtrip()
        except WireError:
            pass
        finally:
            self._sock.close()

    def __enter__(self) -> VirtualPointer:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# --- virtual keyboard -------------------------------------------------------
# wtype cannot target a seat, so multi-seat text needs our own keyboard. The
# trick wtype uses, and we reuse: instead of mapping characters onto the user's
# layout, generate a keymap whose keys ARE the characters we want to type.
# Layout-independent and unicode-correct by construction.
#
# WHICH keycode carries a character matters, though. wtype numbers keys 1, 2, 3...
# in order of first appearance, and evdev 1/14/15 are Escape/Backspace/Tab.
# Chromium derives the key identity of punctuation from the evdev code (US
# layout), so a '/' on code 1 arrives as Escape and is dropped, and a '-' on
# code 14 arrives as Backspace and DELETES the previous character
# ("abcdefghijklm-z" typed as "abcdefghijklz"). Toolkits that read only the
# keysym (foot, GTK) never noticed. So every key goes on its REAL US code when it
# has one, and anything else only on codes that are ordinary character keys.

VK_INTERFACE = "zwp_virtual_keyboard_manager_v1"
VK_CREATE = 0
VK_KEYMAP, VK_KEY, VK_MODIFIERS = 0, 1, 2
XKB_KEYMAP_FORMAT_V1 = 1
KEYCODE_BASE = 8  # evdev offset: xkb keycode = evdev + 8
_KEYCODE_MAX = 255  # xkb keycodes are 8..255

# US layout: evdev code -> (unshifted, shifted) character.
_US_ROWS = [
    (2, "1234567890-=", "!@#$%^&*()_+"),
    (16, "qwertyuiop[]", "QWERTYUIOP{}"),
    (30, "asdfghjkl;'`", 'ASDFGHJKL:"~'),
    (43, "\\", "|"),
    (44, "zxcvbnm,./", "ZXCVBNM<>?"),
]
US_CODE: dict[str, int] = {" ": 57}
for _base, _lo, _hi in _US_ROWS:
    for _i, (_a, _b) in enumerate(zip(_lo, _hi, strict=True)):
        US_CODE.setdefault(_a, _base + _i)
        US_CODE.setdefault(_b, _base + _i)

# Codes whose US meaning is a printable character: the only safe homes for a
# character that has no code of its own (or lost it to another character).
_PRINTABLE_CODES = sorted({*US_CODE.values(), 86})  # 86: the ISO 102nd key

# Named keysyms -> their real evdev code, so Return/Tab/arrows/modifiers are
# identified correctly by apps that look at the code as well as the keysym.
NAMED_CODE: dict[str, int] = {
    "Escape": 1, "BackSpace": 14, "Tab": 15, "ISO_Left_Tab": 15, "Return": 28,
    "Control_L": 29, "Shift_L": 42, "Shift_R": 54, "KP_Multiply": 55, "Alt_L": 56,
    "space": 57, "Caps_Lock": 58, "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63,
    "F6": 64, "F7": 65, "F8": 66, "F9": 67, "F10": 68, "F11": 87, "F12": 88,
    "KP_Enter": 96, "Control_R": 97, "Print": 99, "Alt_R": 100,
    "ISO_Level3_Shift": 100, "Home": 102, "Up": 103, "Prior": 104, "Page_Up": 104,
    "Left": 105, "Right": 106, "End": 107, "Down": 108, "Next": 109,
    "Page_Down": 109, "Insert": 110, "Delete": 111, "Pause": 119, "Super_L": 125,
    "Super_R": 126, "Menu": 127, "XF86AudioMute": 113, "XF86AudioLowerVolume": 114,
    "XF86AudioRaiseVolume": 115, "XF86AudioNext": 163, "XF86AudioPlay": 164,
    "XF86AudioPrev": 165, "XF86AudioStop": 166,
}  # fmt: skip

# Keysym names for characters, so a combo like ctrl+minus finds the minus key.
_KEYSYM_CHAR = {
    "minus": "-", "equal": "=", "plus": "+", "underscore": "_", "slash": "/",
    "backslash": "\\", "period": ".", "comma": ",", "semicolon": ";", "colon": ":",
    "apostrophe": "'", "quotedbl": '"', "grave": "`", "asciitilde": "~",
    "bracketleft": "[", "bracketright": "]", "braceleft": "{", "braceright": "}",
    "less": "<", "greater": ">", "question": "?", "exclam": "!", "at": "@",
    "numbersign": "#", "dollar": "$", "percent": "%", "asciicircum": "^",
    "ampersand": "&", "asterisk": "*", "parenleft": "(", "parenright": ")", "bar": "|",
}  # fmt: skip

# Characters typed as their named key, as wtype does.
_TEXT_KEYSYM = {"\n": "Return", "\t": "Tab", "\x1b": "Escape"}


def _char_keysym(ch: str) -> str:
    return _TEXT_KEYSYM.get(ch) or f"U{ord(ch):04X}"


def preferred_code(keysym: str, ch: str | None = None) -> int | None:
    """The real US evdev code for a keysym/character, or None if it has none."""
    if ch is not None:
        if ch in _TEXT_KEYSYM:
            return NAMED_CODE[_TEXT_KEYSYM[ch]]
        return US_CODE.get(ch)
    if keysym in NAMED_CODE:
        return NAMED_CODE[keysym]
    if len(keysym) == 1:
        return US_CODE.get(keysym)
    return US_CODE.get(_KEYSYM_CHAR.get(keysym, ""))


class KeycodesExhausted(WireError):
    """More distinct keys than safe keycodes in one keymap (caller splits)."""


def allocate_codes(items: list[tuple[str, int | None]]) -> list[int]:
    """Assign an evdev code to each (label, preferred code): the preferred code
    when free, otherwise a free printable-character code. Never a code whose US
    meaning is Escape/Backspace/Tab/Enter/etc. unless that IS the key's own code.
    Raises KeycodesExhausted when the printable pool runs out."""
    taken: set[int] = set()
    out: list[int | None] = [None] * len(items)
    for i, (_label, pref) in enumerate(items):  # pass 1: real codes win
        if pref is not None and pref not in taken:
            out[i] = pref
            taken.add(pref)
    spare = (c for c in _PRINTABLE_CODES if c not in taken)
    for i in range(len(items)):  # pass 2: everyone else on a character key
        if out[i] is None:
            code = next(spare, None)
            while code is not None and code in taken:
                code = next(spare, None)
            if code is None:
                raise KeycodesExhausted(f"more than {len(_PRINTABLE_CODES)} distinct keys")
            out[i] = code
            taken.add(code)
    return [c for c in out if c is not None]


def _keymap(entries: list[tuple[str, str, int]], modmap: list[str] | None = None) -> bytes:
    """Build an XKB keymap from (label, keysym, evdev code) entries."""
    keycodes = [f"    <{lab}> = {code + KEYCODE_BASE};" for lab, _sym, code in entries]
    symbols = [f"    key <{lab}> {{ [ {sym} ] }};" for lab, sym, _code in entries]
    return (
        "xkb_keymap {\n"
        "  xkb_keycodes {\n"
        f"    minimum = {KEYCODE_BASE};\n"
        f"    maximum = {_KEYCODE_MAX};\n" + "\n".join(keycodes) + "\n  };\n"
        '  xkb_types { include "complete" };\n'
        '  xkb_compat { include "complete" };\n'
        '  xkb_symbols "(unnamed)" {\n' + "\n".join(symbols + (modmap or [])) + "\n  };\n"
        "};\n"
    ).encode()


def _keymap_for(chars: list[str]) -> tuple[bytes, dict[str, int]]:
    """An XKB keymap producing each character, and char -> evdev code."""
    codes = allocate_codes([(ch, preferred_code(_char_keysym(ch), ch)) for ch in chars])
    entries = [
        (f"K{i}", _char_keysym(ch), code)
        for i, (ch, code) in enumerate(zip(chars, codes, strict=True))
    ]
    return _keymap(entries), dict(zip(chars, codes, strict=True))


def text_segments(text: str) -> list[str]:
    """Split text into runs that each fit one keymap (<= the safe code pool)."""
    segs: list[str] = []
    cur: list[str] = []
    uniq: list[str] = []
    for ch in text:
        if ch not in uniq:
            try:
                allocate_codes([(c, preferred_code(_char_keysym(c), c)) for c in [*uniq, ch]])
            except KeycodesExhausted:
                segs.append("".join(cur))
                cur, uniq = [], []
            uniq.append(ch)
        cur.append(ch)
    if cur:
        segs.append("".join(cur))
    return segs


# wtype's modifier names -> the XKB keysym that produces them, and the XKB real
# modifier they map onto. A generated keymap has no modifiers at all, so a combo
# needs both spelled out.
COMBO_MOD_KEYSYM = {
    "shift": "Shift_L",
    "ctrl": "Control_L",
    "alt": "Alt_L",
    "logo": "Super_L",
    "altgr": "ISO_Level3_Shift",
}
# Real-modifier bits of the depressed mask (xkb core order: Shift, Lock,
# Control, Mod1..Mod5), matching COMBO_MOD_XKB below.
COMBO_MOD_MASK = {"shift": 1, "ctrl": 4, "alt": 8, "logo": 64, "altgr": 128}
COMBO_MOD_XKB = {
    "shift": "Shift",
    "ctrl": "Control",
    "alt": "Mod1",
    "logo": "Mod4",
    "altgr": "Mod5",
}


def _keymap_for_combo(key: str | None, mods: list[str]) -> tuple[bytes, dict[str, int]]:
    """A keymap holding one key plus the modifier keys a combo needs.

    Returns the keymap and a name -> evdev code map. Modifiers are pressed as real
    keys rather than announced through the modifiers event, because that is what a
    physical keyboard does and it needs no agreement about mask numbering. Every
    key sits on its real US code (see allocate_codes).
    """
    entries: list[tuple[str, str]] = []  # (label, keysym)
    prefs: list[int | None] = []
    for m in mods:
        sym = COMBO_MOD_KEYSYM.get(m)
        if sym is None:
            raise WireError(f"unknown modifier {m!r}")
        entries.append((f"M_{m}", sym))
        prefs.append(NAMED_CODE.get(sym))
    if key:
        if len(key) > 1:
            entries.append(("KEY", key))
            prefs.append(preferred_code(key))
        else:
            entries.append(("KEY", f"U{ord(key):04X}"))
            prefs.append(preferred_code(key, key))

    if not entries:
        raise WireError("combo resolved to nothing")

    codes_list = allocate_codes(
        [(lab, pref) for (lab, _s), pref in zip(entries, prefs, strict=True)]
    )
    modmap = [f"    modifier_map {COMBO_MOD_XKB[m]} {{ <M_{m}> }};" for m in mods]
    km = _keymap(
        [(lab, sym, code) for (lab, sym), code in zip(entries, codes_list, strict=True)], modmap
    )
    return km, {lab: code for (lab, _s), code in zip(entries, codes_list, strict=True)}


class VirtualKeyboard(VirtualPointer):
    """A virtual keyboard on a chosen seat. Reuses VirtualPointer's connection.

    Subclassing keeps the wire plumbing in one place; the inherited pointer is
    created and simply unused.
    """

    def type_text(self, text: str) -> None:
        if not text:
            return
        # A keymap holds a bounded set of safe keycodes; long unicode text is
        # typed in runs, each on a fresh keyboard with its own keymap.
        for segment in text_segments(text):
            chars = list(dict.fromkeys(segment))  # unique, order preserved
            keymap, codes = _keymap_for(chars)
            kb = self._new_keyboard()
            self._upload_keymap(kb, keymap)
            for ch in segment:
                code = codes[ch]  # evdev code; compositor adds the +8 offset
                for state in (PRESSED, RELEASED):
                    self._send(kb, VK_KEY, struct.pack("<III", _now_ms(), code, state))
                self._roundtrip()

    def _keyboard_seat(self) -> int:
        """A bound wl_seat object for create_virtual_keyboard. Unlike the pointer
        manager, the keyboard manager does not accept a null seat (0), so on the
        default seat we bind the compositor's first wl_seat once and reuse it."""
        if self._seat:
            return self._seat
        cached = getattr(self, "_default_seat", 0)
        if cached:
            return cached
        seats = [(n, v) for n, i, v in self._globals_cache if i == SEAT_INTERFACE]
        if not seats:
            raise WireError(f"compositor does not advertise {SEAT_INTERFACE}")
        name, version = seats[0]
        oid = self._new_id()
        self._send(
            self._registry,
            0,
            struct.pack("<I", name)
            + wl_string(SEAT_INTERFACE)
            + struct.pack("<II", min(version, 9), oid),
        )
        self._default_seat = oid
        return oid

    def _new_keyboard(self) -> int:
        """Bind the manager and create a virtual keyboard on our seat."""
        vk = [(n, v) for n, i, v in self._globals_cache if i == VK_INTERFACE]
        if not vk:
            raise WireError(f"compositor does not advertise {VK_INTERFACE}")
        name, version = vk[0]
        # Resolve the seat FIRST: binding it allocates a new object id, and Wayland
        # requires new ids to be used in the order they were allocated.
        seat = self._keyboard_seat()
        mgr = self._new_id()
        self._send(
            self._registry,
            0,
            struct.pack("<I", name)
            + wl_string(VK_INTERFACE)
            + struct.pack("<II", min(version, 1), mgr),
        )
        kb = self._new_id()
        self._send(mgr, VK_CREATE, struct.pack("<II", seat, kb))
        self._roundtrip()
        return kb

    def _upload_keymap(self, kb: int, keymap: bytes) -> None:
        """The protocol requires a keymap before any key event, passed as an fd."""
        with tempfile.TemporaryFile() as tf:
            tf.write(keymap)
            tf.flush()
            tf.seek(0)
            msg = encode_msg(kb, VK_KEYMAP, struct.pack("<II", XKB_KEYMAP_FORMAT_V1, len(keymap)))
            self._sock.sendmsg(
                [msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack("i", tf.fileno()))]
            )
            self._roundtrip()

    def key_combo(self, mods: list[str], key: str | None) -> None:
        """Press a combo on this seat.

        Modifiers are pressed as real keys, in order, then released in reverse,
        mirroring a physical keyboard. That alone is not enough: the compositor
        does not derive modifier state from a VIRTUAL keyboard's key events, so
        the depressed mask is also announced with the modifiers request (as
        wtype does), or ctrl+a arrives as a plain 'a'.
        """
        keymap, codes = _keymap_for_combo(key, mods)
        kb = self._new_keyboard()
        self._upload_keymap(kb, keymap)
        mask = 0
        for m in mods:
            mask |= COMBO_MOD_MASK[m]

        for m in mods:
            self._send(kb, VK_KEY, struct.pack("<III", _now_ms(), codes[f"M_{m}"], PRESSED))
        if mask:
            self._send(kb, VK_MODIFIERS, struct.pack("<IIII", mask, 0, 0, 0))
        if key:
            for state in (PRESSED, RELEASED):
                self._send(kb, VK_KEY, struct.pack("<III", _now_ms(), codes["KEY"], state))
        if mask:
            self._send(kb, VK_MODIFIERS, struct.pack("<IIII", 0, 0, 0, 0))
        for m in reversed(mods):
            self._send(kb, VK_KEY, struct.pack("<III", _now_ms(), codes[f"M_{m}"], RELEASED))
        self._roundtrip()
