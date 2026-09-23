"""Accessibility tree via AT-SPI, over an in-process D-Bus connection.

AT-SPI publishes every accessible app's widget tree on a private D-Bus (the
"a11y bus"), independent of the display server, so it works on Wayland.
hyprcu reads it and pairs it with hyprctl window geometry to turn
window-relative element positions into global click points.

Transport: one in-process connection (jeepney, pure Python) per Bus. A tree
walk makes ~5 calls per node and hundreds of calls per window; the original
busctl-subprocess transport paid a process spawn for each (~10 ms) and took
3-5 s to list a Chromium window. busctl remains as the fallback when the
native connection cannot be opened, with identical results.

Why window-relative, not screen: on Wayland an app does not know its own
global position, so AT-SPI SCREEN coordinates come back unreliable
(window-relative, zero-origin). WINDOW coordinates are reliable, and the
caller adds the window's global origin (hyprctl `at`) to get a real click
point. This module stays hyprctl-free and returns window-relative extents;
the server does the correlation and mapping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import Any

try:  # optional at import time so a missing wheel degrades to busctl
    from jeepney import DBusAddress, new_method_call
    from jeepney.io.blocking import open_dbus_connection
    from jeepney.low_level import HeaderFields
    from jeepney.wrappers import DBusErrorResponse, unwrap_msg
except ImportError:  # pragma: no cover - exercised only without jeepney
    open_dbus_connection = None  # type: ignore[assignment]

_NATIVE_TIMEOUT = 10.0  # seconds; same budget as the busctl subprocess
_PIPELINE_CHUNK = 128  # requests in flight at once; keeps socket buffers small


class A11yError(RuntimeError):
    """The accessibility bus is unreachable or a busctl call failed."""


_ACCESSIBLE = "org.a11y.atspi.Accessible"
_COMPONENT = "org.a11y.atspi.Component"
_ACTION = "org.a11y.atspi.Action"
_COLLECTION = "org.a11y.atspi.Collection"
_TEXT = "org.a11y.atspi.Text"
_VALUE = "org.a11y.atspi.Value"
_REGISTRY_SVC = "org.a11y.atspi.Registry"
_ROOT = "/org/a11y/atspi/accessible/root"
_DBUS = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")

COORD_WINDOW = 1  # ATSPI_COORD_TYPE_WINDOW: extents relative to the toplevel

# AtspiStateType bit positions (GetState returns a 2-word uint32 bitfield)
_STATE_ENABLED, _STATE_SENSITIVE, _STATE_SHOWING, _STATE_VISIBLE = 8, 24, 25, 30
_STATE_FOCUSED = 12

PASSWORD_ROLE = 40  # AtspiRole PASSWORD_TEXT: never read, never type without consent

# Window-relative coordinates beyond this are toolkit noise, not geometry
_EXTENT_SANITY = 20000

# Roles whose CURRENT VALUE is worth reading, and how to read it. Reading is
# gated on role so the common case (find a button) costs no extra busctl
# calls. PASSWORD_TEXT (40) is deliberately absent: never read its contents.
_STATE_CHECKED, _STATE_PRESSED = 4, 20
_CHECKABLE_ROLES = frozenset({7, 8, 44, 45, 62})  # check box/menu item, radio, toggle
_TEXT_ROLES = frozenset({61, 79})  # text, entry
_VALUE_ROLES = frozenset({51, 52})  # slider, spin button
_MAX_TEXT = 200  # a text area can hold a whole document; report a readable head
_VALUE_BEARING_ROLES = _CHECKABLE_ROLES | _TEXT_ROLES | _VALUE_ROLES

# Roles worth clicking or typing into, as AtspiRole ENUM NUMBERS (from
# GetRole). Numbers are matched, not GetRoleName strings, because the role
# name varies by toolkit (GTK reports a push button (enum 43) as "button",
# Qt as "push button") while the number is standardized.
ACTIONABLE_ROLE_NUMS = frozenset(
    {
        7,  # check box
        8,  # check menu item
        11,  # combo box
        33,  # menu
        35,  # menu item
        37,  # page tab
        40,  # password text
        43,  # push button
        44,  # radio button
        45,  # radio menu item
        51,  # slider
        52,  # spin button
        62,  # toggle button
        79,  # entry
        88,  # link
    }
)


def _busctl(address: str, verb: str, *args: str) -> Any:
    if shutil.which("busctl") is None:
        raise A11yError("busctl not found, install systemd for accessibility support")
    # the GetAddress broker lives on the session bus (--user); the a11y tree
    # itself lives on the private bus reached with --address
    where = ["--address", address] if address else ["--user"]
    argv = ["busctl", "--json=short", *where, verb, *args]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise A11yError(f"busctl {verb} timed out (unresponsive app?)") from exc
    if proc.returncode != 0:
        raise A11yError(f"busctl {verb} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise A11yError(f"unparseable busctl output: {proc.stdout[:200]!r}") from exc


def bus_address() -> str:
    """Ask the session-bus broker for the private accessibility bus address.
    Raises A11yError if no a11y bus is running (no accessible apps)."""
    out = _busctl("", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress")
    data = out.get("data") or []
    if not data or not data[0]:
        raise A11yError("accessibility bus reported no address (no accessible apps?)")
    return str(data[0])


def _typed_args(sig_args: tuple[str, ...]) -> tuple[str, tuple[Any, ...]]:
    """busctl-style (signature, *string values) -> (signature, typed values).
    Only the basic types AT-SPI calls here use: i/u/n/q/x/t ints, b, d, s/o."""
    if not sig_args:
        return "", ()
    sig, values = sig_args[0], sig_args[1:]
    if len(sig) != len(values):
        raise A11yError(f"signature {sig!r} does not match {len(values)} argument(s)")
    out: list[Any] = []
    for code, raw in zip(sig, values, strict=True):
        if code in "iunqxty":
            out.append(int(raw))
        elif code == "b":
            out.append(raw.lower() in ("1", "true", "yes"))
        elif code == "d":
            out.append(float(raw))
        elif code in "so":
            out.append(raw)
        else:
            raise A11yError(f"unsupported D-Bus argument type {code!r}")
    return sig, tuple(out)


def _plain(value: Any) -> Any:
    """jeepney returns tuples for structs and (signature, value) for variants;
    normalize to the lists busctl's JSON gave, so callers see one shape."""
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


class Bus:
    """A connection to the a11y bus: every AT-SPI object is a (service,
    object-path) pair reached with these two calls.

    Opens one native D-Bus connection lazily and reuses it for every call;
    if it cannot be opened, the Bus falls back to busctl for its lifetime.
    Not thread-safe: make one Bus per tool call (connect() does)."""

    def __init__(self, address: str):
        self.address = address
        self._conn: Any = None
        self._native = open_dbus_connection is not None

    def _connection(self) -> Any:
        if self._conn is None:
            try:
                self._conn = open_dbus_connection(bus=self.address)
            except Exception:  # unreachable/odd address: keep working via busctl
                self._native = False
                return None
        return self._conn

    def _native_call(
        self, svc: str, path: str, iface: str, method: str, sig_args: tuple[str, ...]
    ) -> list[Any] | None:
        conn = self._connection() if self._native else None
        if conn is None:
            return None
        sig, args = _typed_args(sig_args)
        msg = new_method_call(DBusAddress(path, bus_name=svc, interface=iface), method, sig, args)
        try:
            reply = conn.send_and_get_reply(msg, timeout=_NATIVE_TIMEOUT)
        except TimeoutError as exc:
            raise A11yError(f"{method} timed out (unresponsive app?)") from exc
        except (OSError, ConnectionError) as exc:
            raise A11yError(f"a11y bus connection failed: {exc}") from exc
        try:
            body = unwrap_msg(reply)
        except DBusErrorResponse as exc:
            raise A11yError(f"{method} failed: {exc.name}: {exc.data}") from exc
        return _plain(tuple(body))

    def call(self, svc: str, path: str, iface: str, method: str, *sig_args: str) -> list[Any]:
        """Return the method's out-args as a list (data[0] is the first)."""
        out = self._native_call(svc, path, iface, method, sig_args)
        if out is not None:
            return out
        return _busctl(self.address, "call", svc, path, iface, method, *sig_args)["data"]

    def prop(self, svc: str, path: str, iface: str, name: str) -> Any:
        """A property value (unwrapped from its variant, not list-wrapped)."""
        out = self._native_call(
            svc, path, "org.freedesktop.DBus.Properties", "Get", ("ss", iface, name)
        )
        if out is not None:
            _sig, value = out[0]  # variant -> [signature, value]
            return value
        return _busctl(self.address, "get-property", svc, path, iface, name)["data"]

    def _message(self, req: tuple[Any, ...]) -> Any:
        kind, svc, path, iface, member, *rest = req
        if kind == "prop":
            addr = DBusAddress(path, bus_name=svc, interface="org.freedesktop.DBus.Properties")
            return new_method_call(addr, "Get", "ss", (iface, member))
        sig, args = _typed_args(tuple(rest))
        return new_method_call(DBusAddress(path, bus_name=svc, interface=iface), member, sig, args)

    @staticmethod
    def _decode(reply: Any, req: tuple[Any, ...]) -> Any:
        try:
            body = _plain(tuple(unwrap_msg(reply)))
        except DBusErrorResponse as exc:
            return A11yError(f"{req[4]} failed: {exc.name}: {exc.data}")
        return body[0][1] if req[0] == "prop" else body

    def many(self, reqs: list[tuple[Any, ...]]) -> list[Any]:
        """Run many independent requests, pipelined: send them all, then read
        the replies, so N calls cost about one round trip instead of N.

        Each request is ("call", svc, path, iface, method, *busctl_sig_args)
        or ("prop", svc, path, iface, name). Returns one entry per request,
        in order: the same value call()/prop() would return, or the
        A11yError it would have raised (returned, not raised, so one dead
        element does not sink the batch)."""
        conn = self._connection() if self._native else None
        if conn is None:
            out: list[Any] = []
            for req in reqs:
                try:
                    if req[0] == "prop":
                        out.append(self.prop(*req[1:5]))
                    else:
                        out.append(self.call(*req[1:]))
                except A11yError as exc:
                    out.append(exc)
            return out
        results: list[Any] = [None] * len(reqs)
        for start in range(0, len(reqs), _PIPELINE_CHUNK):
            pending: dict[int, int] = {}
            try:
                for i in range(start, min(start + _PIPELINE_CHUNK, len(reqs))):
                    serial = next(conn.outgoing_serial)
                    conn.send(self._message(reqs[i]), serial=serial)
                    pending[serial] = i
                deadline = time.monotonic() + _NATIVE_TIMEOUT
                while pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    msg = conn.receive(timeout=remaining)
                    i = pending.pop(msg.header.fields.get(HeaderFields.reply_serial, -1), -1)
                    if i >= 0:
                        results[i] = self._decode(msg, reqs[i])
            except TimeoutError as exc:
                raise A11yError("a11y batch timed out (unresponsive app?)") from exc
            except (OSError, ConnectionError) as exc:
                raise A11yError(f"a11y bus connection failed: {exc}") from exc
        return results

    def get_matches(
        self, svc: str, path: str, rule: tuple[Any, ...]
    ) -> list[tuple[str, str]] | None:
        """AT-SPI Collection.GetMatches: every descendant matching `rule`, in
        document order, in ONE call. None when unavailable (no native
        connection, or the app does not implement Collection), so the
        caller walks the tree instead."""
        conn = self._connection() if self._native else None
        if conn is None:
            return None
        addr = DBusAddress(path, bus_name=svc, interface=_COLLECTION)
        msg = new_method_call(addr, "GetMatches", "(aiia{ss}iaiiasib)uib", (rule, 1, 0, True))
        try:
            body = unwrap_msg(conn.send_and_get_reply(msg, timeout=_NATIVE_TIMEOUT))
        except (DBusErrorResponse, TimeoutError, OSError, ConnectionError):
            return None
        return [(str(s), str(p)) for s, p in body[0]]

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def conn_pid(self, svc: str) -> int | None:
        try:
            return int(self.call(*_DBUS, "GetConnectionUnixProcessID", "s", svc)[0])
        except (A11yError, ValueError, IndexError):
            return None


def connect() -> Bus:
    return Bus(bus_address())


def apps(bus: Bus) -> list[tuple[str, str]]:
    """Every registered application's root accessible, as (service, path)."""
    children = bus.call(_REGISTRY_SVC, _ROOT, _ACCESSIBLE, "GetChildren")[0]
    return [(svc, path) for svc, path in children]


def app_for_pid(bus: Bus, pid: int, title: str = "") -> tuple[str, str] | None:
    """The application accessible whose connection PID matches the window
    (exact for single-process apps). Falls back to matching a frame's name
    to the window title, which covers multi-process apps (e.g. Electron/Qt
    whose a11y connection PID differs from the window PID)."""
    registered = apps(bus)
    for svc, path in registered:
        if bus.conn_pid(svc) == pid:
            return (svc, path)
    if title:
        for svc, path in registered:
            if _has_frame_named(bus, svc, path, title):
                return (svc, path)
    return None


def _has_frame_named(bus: Bus, svc: str, path: str, title: str) -> bool:
    return any(_name(bus, cs, cp) == title for cs, cp in _children(bus, svc, path))


def window_frame(
    bus: Bus,
    app_svc: str,
    app_path: str,
    title: str = "",
    size: tuple[int, int] | None = None,
) -> tuple[str, str]:
    """The app's toplevel matching a SPECIFIC window (by accessible name ==
    title, then by extent size), so a multi-window app's OTHER windows are
    not walked and mapped with the wrong origin. Returns the app root when
    there is a single toplevel or no confident match (walking from the root
    is then correct or the best available)."""
    frames = _children(bus, app_svc, app_path)
    if len(frames) <= 1:
        return (app_svc, app_path)
    if title:
        for fs, fp in frames:
            if _name(bus, fs, fp) == title:
                return (fs, fp)
    if size:
        for fs, fp in frames:
            ext = _window_extents(bus, fs, fp)
            if ext and (ext[2], ext[3]) == tuple(size):
                return (fs, fp)
    return (app_svc, app_path)


def _name(bus: Bus, svc: str, path: str) -> str:
    try:
        return str(bus.prop(svc, path, _ACCESSIBLE, "Name") or "")
    except A11yError:
        return ""


def _role_num(bus: Bus, svc: str, path: str) -> int:
    try:
        return int(bus.call(svc, path, _ACCESSIBLE, "GetRole")[0])
    except (A11yError, IndexError, ValueError):
        return -1


def _role_name(bus: Bus, svc: str, path: str) -> str:
    try:
        return str(bus.call(svc, path, _ACCESSIBLE, "GetRoleName")[0])
    except (A11yError, IndexError):
        return ""


def _children(bus: Bus, svc: str, path: str) -> list[tuple[str, str]]:
    try:
        return [(cs, cp) for cs, cp in bus.call(svc, path, _ACCESSIBLE, "GetChildren")[0]]
    except (A11yError, IndexError, ValueError):
        return []


def _window_extents(bus: Bus, svc: str, path: str) -> tuple[int, int, int, int] | None:
    """Window-relative extents, or None when the widget has no usable
    geometry. Toolkits report degenerate or wild extents for things that are
    not rendered (GTK notebook scroll arrows come back 8x0; widgets on an
    unrendered tab page report absurd origins), and those must not be
    offered as click targets."""
    try:
        return _parse_extents(bus.call(svc, path, _COMPONENT, "GetExtents", "u", str(COORD_WINDOW)))
    except A11yError:
        return None


def _parse_extents(data: Any) -> tuple[int, int, int, int] | None:
    """GetExtents out-args -> sane (x, y, w, h), or None (see _window_extents)."""
    try:
        x, y, w, h = data[0]
        x, y, w, h = int(x), int(y), int(w), int(h)
    except (IndexError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    if not (-_EXTENT_SANITY <= x <= _EXTENT_SANITY and -_EXTENT_SANITY <= y <= _EXTENT_SANITY):
        return None
    return x, y, w, h


def _states(bus: Bus, svc: str, path: str) -> set[int]:
    try:
        return _parse_states(bus.call(svc, path, _ACCESSIBLE, "GetState"))
    except A11yError:
        return set()


def _parse_states(data: Any) -> set[int]:
    """GetState out-args (a 2-word uint32 bitfield) -> set of state numbers."""
    try:
        words = [int(w) for w in data[0]]
    except (IndexError, TypeError, ValueError):
        return set()
    out: set[int] = set()
    for wi, word in enumerate(words):
        for bit in range(32):
            if word >> bit & 1:
                out.add(wi * 32 + bit)
    return out


def _interfaces(bus: Bus, svc: str, path: str) -> set[str]:
    """Short interface names the object supports, so Text/Value are only
    called where they exist (calling them blind raises UnknownMethod)."""
    try:
        return {i.rsplit(".", 1)[-1] for i in bus.call(svc, path, _ACCESSIBLE, "GetInterfaces")[0]}
    except (A11yError, IndexError, TypeError):
        return set()


def element_value(bus: Bus, svc: str, path: str, role: int, states: set[int]) -> dict[str, Any]:
    """The element's CURRENT VALUE, as opposed to its label: what is typed
    into it, where a slider sits, whether a box is ticked. Returns the keys
    that apply ({} for a plain button), because the accessible name alone
    says a control called "Volume" exists without saying it is at 66%.

    Gated on role: checkable state is free (already in `states`), Text and
    Value cost one call each and only for roles that can carry them. A
    password field's contents are never read."""
    if role in _CHECKABLE_ROLES:
        return {"checked": _STATE_CHECKED in states or _STATE_PRESSED in states}
    if role in _TEXT_ROLES:
        if "Text" not in _interfaces(bus, svc, path):
            return {}
        try:
            count = int(bus.prop(svc, path, _TEXT, "CharacterCount"))
            if count <= 0:
                return {"value": ""}
            end = min(count, _MAX_TEXT)
            text = str(bus.call(svc, path, _TEXT, "GetText", "ii", "0", str(end))[0])
            return {"value": text + ("..." if count > end else "")}
        except (A11yError, IndexError, ValueError, TypeError):
            return {}
    if role in _VALUE_ROLES:
        if "Value" not in _interfaces(bus, svc, path):
            return {}
        try:
            current = float(bus.prop(svc, path, _VALUE, "CurrentValue"))
            low = float(bus.prop(svc, path, _VALUE, "MinimumValue"))
            high = float(bus.prop(svc, path, _VALUE, "MaximumValue"))
        except (A11yError, ValueError, TypeError):
            return {}
        out: dict[str, Any] = {"value": current}
        if high > low:  # raw units are toolkit-specific; a percent is readable
            out["percent"] = round((current - low) / (high - low) * 100)
        return out
    return {}


def _clickable_now(states: set[int]) -> bool:
    """Showing, visible, and responsive to input. SENSITIVE and ENABLED
    overlap but toolkits do not set them together (GTK notebook tabs report
    SENSITIVE without ENABLED yet click fine), so either satisfies the
    responsive half rather than requiring both."""
    if not {_STATE_SHOWING, _STATE_VISIBLE} <= states:
        return False
    return _STATE_SENSITIVE in states or _STATE_ENABLED in states


_MATCH_ALL, _MATCH_ANY = 1, 2  # AtspiCollectionMatchType
DOCUMENT_WEB_ROLE = 95  # AtspiRole DOCUMENT_WEB (Chromium/Firefox/WebKit pages)


def _bitset(bits: Any, words: int) -> list[int]:
    """Pack bit numbers into D-Bus int32 words (signed, as 'ai' requires)."""
    out = [0] * words
    for b in bits:
        out[b // 32] |= 1 << (b % 32)
    return [w - (1 << 32) if w >= 1 << 31 else w for w in out]


def match_rule(roles: Any = None, states: Any = None) -> tuple[Any, ...]:
    """An AT-SPI Collection MatchRule: descendants having ANY of `roles` and
    ALL of `states`. Omitted criteria match everything (empty set + ALL)."""
    return (
        _bitset(states or (), 2),
        _MATCH_ALL,
        {},
        _MATCH_ALL,
        _bitset(roles, 4) if roles else [],
        _MATCH_ANY if roles else _MATCH_ALL,
        [],
        _MATCH_ALL,
        False,
    )


def _find_elements_collection(
    bus: Any, app_svc: str, app_path: str, needle: str, actionable: bool, max_results: int
) -> list[dict[str, Any]] | None:
    """find_elements via Collection.GetMatches + pipelined reads: the same
    filters and result shape as the walk, in ~4 round trips instead of ~5
    per node. None when the bus or app cannot do it (caller walks)."""
    get_matches = getattr(bus, "get_matches", None)
    many = getattr(bus, "many", None)
    if get_matches is None or many is None:
        return None
    cands = get_matches(
        app_svc, app_path, match_rule(roles=ACTIONABLE_ROLE_NUMS if actionable else None)
    )
    if cands is None:
        return None
    cands = list(cands)
    rule = match_rule(roles=ACTIONABLE_ROLE_NUMS if actionable else None)
    # Which candidates live inside a web document: Chromium reports those in
    # physical pixels but its own UI in a scaled unit, so the caller must scale
    # the two differently (see server._ui_read).
    in_doc: dict[tuple[str, str], tuple[str, str]] = {}
    for doc in get_matches(app_svc, app_path, match_rule(roles=[DOCUMENT_WEB_ROLE])) or []:
        in_doc[doc] = doc
        for sub in get_matches(doc[0], doc[1], rule) or []:
            in_doc.setdefault(sub, doc)
    if not actionable:  # the walk includes its start node; GetMatches returns descendants
        cands = [(app_svc, app_path), *cands]

    names = [
        "" if isinstance(n, A11yError) or n is None else str(n)
        for n in many([("prop", s, p, _ACCESSIBLE, "Name") for s, p in cands])
    ]
    named = [(c, n) for c, n in zip(cands, names, strict=True) if not needle or needle in n.lower()]
    roles = many([("call", s, p, _ACCESSIBLE, "GetRole") for (s, p), _ in named])

    staged: list[tuple[str, str, str, int]] = []
    for ((svc, path), nm), raw in zip(named, roles, strict=True):
        try:
            role_num = -1 if isinstance(raw, A11yError) else int(raw[0])
        except (IndexError, TypeError, ValueError):
            role_num = -1
        if actionable and role_num not in ACTIONABLE_ROLE_NUMS:
            continue
        if not nm and not needle and role_num not in _VALUE_BEARING_ROLES:
            continue
        staged.append((svc, path, nm, role_num))

    reqs: list[tuple[Any, ...]] = []
    for svc, path, _nm, _r in staged:
        reqs.append(("call", svc, path, _COMPONENT, "GetExtents", "u", str(COORD_WINDOW)))
        reqs.append(("call", svc, path, _ACCESSIBLE, "GetState"))
        reqs.append(("call", svc, path, _ACCESSIBLE, "GetRoleName"))
    details = many(reqs)

    results: list[dict[str, Any]] = []
    for k, (svc, path, nm, role_num) in enumerate(staged):
        ext_raw, st_raw, rn_raw = details[3 * k : 3 * k + 3]
        ext = None if isinstance(ext_raw, A11yError) else _parse_extents(ext_raw)
        if ext is None:
            continue
        states = set() if isinstance(st_raw, A11yError) else _parse_states(st_raw)
        try:
            role_name = "" if isinstance(rn_raw, A11yError) else str(rn_raw[0])
        except (IndexError, TypeError):
            role_name = ""
        item = {
            "role": role_name,
            "name": nm,
            "extent": ext,
            "clickable": _clickable_now(states),
            **element_value(bus, svc, path, role_num, states),
            "svc": svc,
            "path": path,
        }
        if (svc, path) in in_doc:
            item["document"] = in_doc[(svc, path)]
        results.append(item)
        if len(results) >= max_results:
            break
    return results


def frame_size(bus: Any, svc: str, path: str) -> tuple[int, int] | None:
    """The toplevel's own reported (w, h), in the toolkit's UI unit. When
    `path` is an application root (single-window apps), its one frame child."""
    ext = _window_extents(bus, svc, path)
    if ext is None:
        kids = _children(bus, svc, path)
        if len(kids) != 1:
            return None
        ext = _window_extents(bus, *kids[0])
    return (ext[2], ext[3]) if ext else None


def document_extents(bus: Any, doc: tuple[str, str]) -> tuple[int, int, int, int] | None:
    return _window_extents(bus, doc[0], doc[1])


def find_elements(
    bus: Bus,
    app_svc: str,
    app_path: str,
    name: str = "",
    actionable: bool = True,
    max_nodes: int = 400,
    max_results: int = 60,
) -> tuple[list[dict[str, Any]], bool]:
    """Depth-first over a window's subtree, returning (matching elements,
    truncated). Elements carry WINDOW-relative extents (the caller adds the
    window origin). Filters by `name` substring (case-insensitive) and, when
    `actionable`, to interactive roles. `truncated` is True when the walk hit
    the max_nodes budget before exhausting the tree, so the caller can tell
    'nothing there' from 'stopped early' instead of reporting a false
    absence."""
    needle = name.lower()
    fast = _find_elements_collection(bus, app_svc, app_path, needle, actionable, max_results)
    if fast is not None:
        return fast, False
    results: list[dict[str, Any]] = []
    stack: list[tuple[str, str]] = [(app_svc, app_path)]
    visited = 0
    while stack and visited < max_nodes and len(results) < max_results:
        svc, path = stack.pop()
        visited += 1
        nm = _name(bus, svc, path)
        kids = _children(bus, svc, path)
        stack.extend(reversed(kids))  # keep document order under a LIFO stack
        if needle and needle not in nm.lower():
            continue
        role_num = _role_num(bus, svc, path)  # also gates the value read below
        if actionable and role_num not in ACTIONABLE_ROLE_NUMS:
            continue
        if not nm and not needle and role_num not in _VALUE_BEARING_ROLES:
            # unnamed and valueless: nothing to target or report. An unnamed
            # slider or checkbox still carries a reading worth returning.
            continue
        ext = _window_extents(bus, svc, path)
        if ext is None:
            continue
        states = _states(bus, svc, path)
        results.append(
            {
                "role": _role_name(bus, svc, path),
                "name": nm,
                "extent": ext,
                "clickable": _clickable_now(states),
                **element_value(bus, svc, path, role_num, states),
                "svc": svc,
                "path": path,
            }
        )
    truncated = visited >= max_nodes and bool(stack) and len(results) < max_results
    return results, truncated


def focused_role(bus: Bus, app_svc: str, app_path: str, max_nodes: int = 200) -> int | None:
    """The AtspiRole number of the element that currently holds keyboard
    focus in this window, or None if none is found within the node budget.
    Bounded because it runs before typing: a fast, best-effort check for the
    auth guard, not an exhaustive walk. Prunes into non-showing subtrees so
    it does not spend the budget on hidden pages."""
    get_matches = getattr(bus, "get_matches", None)
    if get_matches is not None:
        # One call for every focused descendant, instead of a state read per node.
        focused = get_matches(app_svc, app_path, match_rule(states=[_STATE_FOCUSED]))
        if focused is not None:
            return _role_num(bus, *focused[0]) if focused else None
    stack: list[tuple[str, str]] = [(app_svc, app_path)]
    visited = 0
    while stack and visited < max_nodes:
        svc, path = stack.pop()
        visited += 1
        states = _states(bus, svc, path)
        if _STATE_FOCUSED in states:
            return _role_num(bus, svc, path)
        if _STATE_SHOWING in states or (svc, path) == (app_svc, app_path):
            stack.extend(reversed(_children(bus, svc, path)))
    return None


def do_action(bus: Bus, svc: str, path: str, index: int = 0) -> bool:
    """Invoke an accessible's action (default index 0, usually the click),
    with no pointer, so it works even when the window is not visible."""
    try:
        return bool(bus.call(svc, path, _ACTION, "DoAction", "i", str(index))[0])
    except (A11yError, IndexError):
        return False
