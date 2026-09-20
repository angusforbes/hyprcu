"""hyprcu contract: acting tools do exactly what they're asked. No abort on
desktop change unless opted in, no step cap, no time budget, no clamped waits."""
import inspect
import hyprcu.server as srv


def test_sequence_default_does_not_stop_on_change():
    assert inspect.signature(srv.sequence).parameters["stop_on_change"].default is False


def test_sequence_has_no_practical_step_cap():
    assert srv._SEQ_MAX_STEPS >= 1000


def test_sequence_has_no_practical_time_budget():
    assert srv._SEQ_BUDGET >= 3600


def test_launch_wait_is_not_clamped(monkeypatch):
    seen = {}
    monkeypatch.setattr(srv, "_launch_and_wait", lambda cmd, ws, wait_s: seen.setdefault("w", wait_s) or {"address": "0x1", "class": "", "title": "", "workspace": 1}, raising=False)
    src = inspect.getsource(srv.launch)
    assert "min(max(wait_s" not in src and "uncapped" in src


def test_wait_for_timeout_is_not_clamped():
    src = inspect.getsource(srv.wait_for)
    assert "60.0" not in src and "uncapped" in src


def test_no_tool_docstring_promises_refusal():
    for name in ("pointer", "keyboard", "click_ui", "hypr", "launch", "use_bind", "sequence", "wait_for"):
        doc = (getattr(srv, name).__doc__ or "").lower()
        for word in ("refus", "confine", "allowlist", "guard", "bounded to"):
            assert word not in doc, f"{name} docstring still says {word!r}"
