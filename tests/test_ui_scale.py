"""Accessibility extents -> logical pixels, per coordinate space.

Measured on Chromium: its UI frame reports 1147x705 for a 1558x958 window
(x1.358), and its web document reports physical pixels (1412 wide in an
881-wide window on a 1.6-scale monitor). GTK reports logical pixels.
"""

import pytest

from hyprcu import server as srv

DOC = ("app", "/doc")


@pytest.fixture
def geometry(monkeypatch):
    state = {"frame": None, "doc": None, "mscale": 1.0}
    monkeypatch.setattr(srv.a11y, "frame_size", lambda bus, s, p: state["frame"])
    monkeypatch.setattr(srv.a11y, "document_extents", lambda bus, d: state["doc"])
    monkeypatch.setattr(srv, "_monitor_scale", lambda c: state["mscale"])
    return state


def scales(state, size, docs=True):
    client = {"size": size, "monitor": 0}
    elements = [{"document": DOC}] if docs else [{}]
    return srv._a11y_scales(None, ("app", "/f"), client, elements)


def test_gtk_logical_pixels_are_unscaled(geometry):
    geometry["frame"] = (800, 600)
    assert scales(geometry, [800, 600], docs=False) == {None: 1.0}


def test_chromium_ui_scaled_web_unscaled_at_monitor_scale_1(geometry):
    geometry.update(frame=(1147, 705), doc=(0, 118, 1560, 841), mscale=1.0)
    s = scales(geometry, [1558, 958])
    assert s[None] == pytest.approx(1.358, abs=0.002)
    assert s[DOC] == 1.0


def test_chromium_web_physical_pixels_on_hidpi_monitor(geometry):
    geometry.update(frame=(649, 785), doc=(0, 263, 1412, 1445), mscale=1.6)
    s = scales(geometry, [881, 1066])
    assert s[None] == pytest.approx(1.357, abs=0.002)
    assert s[DOC] == pytest.approx(1 / 1.6)


def test_split_view_half_width_document_uses_height_to_decide(geometry):
    # a half-width document still fits horizontally at scale 1, but not vertically
    geometry.update(frame=(649, 785), doc=(706, 263, 706, 1445), mscale=1.6)
    assert scales(geometry, [881, 1066])[DOC] == pytest.approx(1 / 1.6)


def test_logical_web_view_is_left_alone(geometry):
    # a WebKitGTK-style document already in logical pixels
    geometry.update(frame=(900, 700), doc=(0, 50, 900, 650), mscale=1.6)
    assert scales(geometry, [900, 700])[DOC] == 1.0


def test_unknown_frame_size_means_no_ui_scaling(geometry):
    assert scales(geometry, [1000, 800], docs=False) == {None: 1.0}
