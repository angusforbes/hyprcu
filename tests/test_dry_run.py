"""--dry-run / HYPRCU_DRYRUN must never act (it was a no-op stub from the fork)."""

import pytest

from hyprcu import journal
from hyprcu import server as srv


def test_dry_run_reads_the_environment(monkeypatch):
    monkeypatch.delenv("HYPRCU_DRYRUN", raising=False)
    assert journal.dry_run() is False
    monkeypatch.setenv("HYPRCU_DRYRUN", "1")
    assert journal.dry_run() is True


def test_input_barrier_refuses_when_dry(monkeypatch):
    monkeypatch.setenv("HYPRCU_DRYRUN", "1")
    with pytest.raises(RuntimeError, match="dry run"):
        journal.refuse_if_dry("type_text")


def test_dry_run_hypr_never_dispatches(monkeypatch):
    monkeypatch.setenv("HYPRCU_DRYRUN", "1")

    def boom(*a, **k):
        raise AssertionError("dispatched during a dry run")

    monkeypatch.setattr(srv.hyprctl, "dispatch", boom)
    out = srv.hypr("workspace", workspace="3")
    assert "DRY RUN" in str(out)
