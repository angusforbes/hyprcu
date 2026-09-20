"""cleanup.py: process-exit handlers — they run on SIGTERM/atexit, each
best-effort, and arm() installs the path exactly once."""

import signal

from hyprcu import cleanup


def test_run_invokes_and_drains_register():
    got = []

    cleanup.register(lambda: got.append(1))
    cleanup.register(lambda: got.append(2))

    cleanup.run()
    assert got == [2, 1]      # registered-last runs first (LIFO)
    cleanup.run()
    assert got == [2, 1]      # drained: running again does nothing


def test_run_is_best_effort_per_handler():
    def boom():
        raise RuntimeError("a cleanup must not stop the rest")

    got = []
    cleanup.register(lambda: got.append("first"))
    cleanup.register(boom)    # registered last, so it runs first
    cleanup.register(lambda: got.append("last"))

    cleanup.run()             # must not raise
    assert got == ["last", "first"]


def test_arm_is_idempotent_and_sigterm_reraises(monkeypatch):
    registered = []
    sig_handlers = {}
    killed = []
    ran = []

    class _Atexit:
        def register(self, fn):
            registered.append(fn)

    class _Signal:
        SIG_DFL = signal.SIG_DFL
        SIGTERM = signal.SIGTERM

        def signal(self, signum, handler_or_dfl):
            sig_handlers[signum] = handler_or_dfl

    class _Os:
        def kill(self, pid, sig):
            killed.append((pid, sig))

        def getpid(self):
            return 4242

    monkeypatch.setattr(cleanup, "_armed", False)
    monkeypatch.setattr(cleanup, "atexit", _Atexit())
    monkeypatch.setattr(cleanup, "signal", _Signal())
    monkeypatch.setattr(cleanup, "os", _Os())

    cleanup.arm()
    cleanup.arm()             # second call must be a no-op

    assert len(registered) == 1                     # atexit registered once
    handler = sig_handlers[signal.SIGTERM]
    assert callable(handler)

    # drive the captured handler: it runs the cleanups, then re-raises
    # SIGTERM under the default disposition so the process actually dies
    monkeypatch.setattr(cleanup, "run", lambda: ran.append(True))
    handler(signal.SIGTERM, None)

    assert ran == [True]
    assert killed == [(4242, signal.SIGTERM)]