"""Unit tests for PlaywrightOps' current-tab bookkeeping (no browser needed)."""

from dbrowser import browser_ops
from dbrowser.browser_ops import PlaywrightOps, _pick_active


def test_remembered_tab_wins_over_devtools_order():
    # Regression: Chromium kept listing the newer tab first after selecting tab 0.
    assert _pick_active(["a", "b"], "a", ["b", "a"]) == 0


def test_falls_back_to_devtools_order_when_remembered_tab_is_gone():
    assert _pick_active(["a", "b"], "closed", ["b", "a"]) == 1
    assert _pick_active(["a", "b"], None, ["a", "b"]) == 0


def test_falls_back_to_last_tab_without_any_information():
    assert _pick_active(["a", "b", None], None, []) == 2


def test_remembered_sessions_are_bounded(monkeypatch):
    monkeypatch.setattr(browser_ops, "MAX_REMEMBERED_SESSIONS", 2)
    ops = PlaywrightOps()
    ops._remember("s1", "a")
    ops._remember("s2", "b")
    ops._remember("s1", "c")  # refresh s1, so s2 is the oldest
    ops._remember("s3", "d")
    assert dict(ops._selected) == {"s1": "c", "s3": "d"}
