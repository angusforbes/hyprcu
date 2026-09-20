"""Process-exit cleanup: run registered handlers on SIGTERM or normal exit.

hyprcu carries no activity beacon and makes no guarantees to a human; but
it *does* hold OS resources that must not be stranded if the process is
killed. The one today is a mouse button an in-flight drag is holding on
the virtual pointer (`input.release_held`). Upstream bundled this with
the safety beacon (`safety.on_shutdown`), which this fork keeps as a
no-op stub, so the cleanup is re-homed here under a name that says only
what it does.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import signal
from collections.abc import Callable

_cleanups: list[Callable[[], None]] = []
_armed = False


def register(fn: Callable[[], None]) -> None:
    """Run `fn` before the process dies, whether by SIGTERM or normal exit."""
    _cleanups.append(fn)


def run() -> None:
    """Run every registered cleanup, each best-effort, in reverse order."""
    while _cleanups:
        with contextlib.suppress(Exception):
            _cleanups.pop()()


def arm() -> None:
    """Install the SIGTERM + atexit shutdown path, once.

    Only SIGTERM: the MCP/anyio runtime handles SIGINT (Ctrl+C) itself,
    and overriding it can deadlock the interpreter against its own stdin
    reader. `signal.signal` only works on the main thread, so a call from
    a worker thread is suppressed and atexit alone covers that case. The
    cleanups run first; then the default SIGTERM disposition is restored
    and the signal re-raised so the process actually terminates.
    """
    global _armed
    if _armed:
        return
    _armed = True
    atexit.register(run)

    def _on_sigterm(signum: int, _frame: object) -> None:
        run()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGTERM, _on_sigterm)