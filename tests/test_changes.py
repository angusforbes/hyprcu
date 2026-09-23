"""then='changes': raw-frame diff, pointer masking, settling, and the result."""

import pytest

from hyprcu import screenshot as shot
from hyprcu import server as srv


def _frame(w, h, paint=()):
    """A black w x h RGB frame with white (x, y, w, h) rects painted in."""
    buf = bytearray(w * h * 3)
    for x, y, rw, rh in paint:
        for yy in range(y, y + rh):
            buf[(yy * w + x) * 3 : (yy * w + x + rw) * 3] = b"\xff" * (rw * 3)
    return bytes(buf)


def test_identical_frames_have_no_changes():
    f = _frame(200, 100)
    assert shot.diff_boxes(200, 100, f, f) == []


def test_one_change_is_one_box_covering_it():
    before, after = _frame(200, 100), _frame(200, 100, [(50, 20, 10, 5)])
    [(x, y, w, h)] = shot.diff_boxes(200, 100, before, after)
    # rows exact; columns to the 16-px probe grid, always covering the change
    assert (y, h) == (20, 5)
    assert x <= 50 and x + w >= 60 and w <= 32


def test_distant_changes_stay_separate_boxes():
    before = _frame(200, 300)
    after = _frame(200, 300, [(10, 10, 5, 5), (150, 250, 5, 5)])
    boxes = shot.diff_boxes(200, 300, before, after)
    assert len(boxes) == 2 and boxes[0][1] == 10 and boxes[1][1] == 250


def test_many_bands_collapse_to_their_union():
    before = _frame(100, 400)
    after = _frame(100, 400, [(0, y, 4, 2) for y in range(0, 400, 60)])  # 7 bands
    [(x, y, w, h)] = shot.diff_boxes(100, 400, before, after, max_boxes=4)
    assert y == 0 and y + h >= 362


def test_size_change_is_everything():
    assert shot.diff_boxes(10, 10, _frame(10, 10), _frame(10, 5)) == [(0, 0, 10, 10)]


def test_mask_rects_hides_only_the_masked_area():
    before = _frame(100, 100)
    after = _frame(100, 100, [(10, 10, 8, 8), (70, 70, 8, 8)])
    masked_before = shot.mask_rects(100, 100, before, after, [(5, 5, 20, 20)])
    [(x, y, _w, _h)] = shot.diff_boxes(100, 100, masked_before, after)
    assert y == 70  # the change at (10,10) was under the pointer box


def test_settle_waits_for_a_quiet_period(monkeypatch):
    frames = iter([b"a", b"b", b"b", b"b", b"b", b"b"])
    monkeypatch.setattr(shot, "raw_frame", lambda out: (1, 1, next(frames)))
    monkeypatch.setattr(shot.time, "sleep", lambda s: None)
    clock = iter(x * 0.1 for x in range(100))
    monkeypatch.setattr(shot.time, "monotonic", lambda: next(clock))
    w, h, data, settled = shot.settle("OUT", interval=0.1, quiet=0.3)
    assert settled and data == b"b"


def test_settle_gives_up_on_endless_change(monkeypatch):
    n = iter(range(1000))
    monkeypatch.setattr(shot, "raw_frame", lambda out: (1, 1, bytes([next(n) % 256])))
    monkeypatch.setattr(shot.time, "sleep", lambda s: None)
    clock = iter(x * 0.1 for x in range(1000))
    monkeypatch.setattr(shot.time, "monotonic", lambda: next(clock))
    *_rest, settled = shot.settle("OUT", timeout=1.0)
    assert settled is False


MON = {"name": "OUT", "focused": True, "x": 0, "y": 0, "width": 200, "height": 100, "scale": 1.0}


@pytest.fixture
def desk(monkeypatch):
    """A 200x100 monitor whose 'after' frame the test sets; captures recorded."""
    state = {"after": _frame(200, 100), "crops": [], "cursor": (190, 90)}
    monkeypatch.setattr(srv.hyprctl, "query", lambda what: [MON])
    monkeypatch.setattr(srv.hyprctl, "cursor_pos", lambda: state["cursor"])
    monkeypatch.setattr(srv.hyprctl, "logical_rect", lambda m: (0, 0, 200, 100))
    monkeypatch.setattr(srv.shot, "raw_frame", lambda out: (200, 100, _frame(200, 100)))
    monkeypatch.setattr(srv.shot, "settle", lambda out: (200, 100, state["after"], True))

    def deliver(window="", region="", **kw):
        state["crops"].append(region or "whole")
        return [srv._text(f"image {region or 'whole'}")]

    monkeypatch.setattr(srv, "_deliver_capture", deliver)
    return state


def test_changes_nothing_changed_sends_no_image(desk):
    srv._prime("changes")
    out = srv._acted("clicked", "changes")
    assert "nothing changed" in out[1].text and desk["crops"] == []


def test_changes_sends_one_crop_per_area(desk):
    desk["after"] = _frame(200, 100, [(20, 10, 10, 10), (150, 70, 10, 10)])
    srv._prime("changes")
    out = srv._acted("clicked", "changes")
    assert "2 area(s) changed" in out[1].text
    assert len(desk["crops"]) == 2 and all(c != "whole" for c in desk["crops"])


def test_changes_ignores_the_pointer(desk):
    # a pointer-sized change right at the pointer position is the pointer
    desk["cursor"] = (100, 50)
    desk["after"] = _frame(200, 100, [(100, 50, 12, 18)])
    srv._prime("changes")
    out = srv._acted("moved", "changes")
    assert "nothing changed" in out[1].text and desk["crops"] == []


def test_changes_mostly_changed_sends_the_whole_screen(desk):
    desk["after"] = _frame(200, 100, [(0, 0, 200, 80)])
    srv._prime("changes")
    out = srv._acted("switched", "changes")
    assert "whole screen follows" in out[1].text and desk["crops"] == ["whole"]


def test_changes_without_a_baseline_falls_back(desk):
    srv._baseline.frame = None
    out = srv._acted("clicked", "changes")
    assert "no before-frame" in out[1].text and desk["crops"] == ["whole"]


def test_other_modes_leave_a_pending_baseline_alone(desk):
    # a sequence primes once; its steps run with then='none' and must not
    # wipe the baseline the sequence's own 'changes' will compare against
    srv._prime("changes")
    srv._prime("none")
    assert srv._baseline.frame is not None
    srv._baseline.frame = None
