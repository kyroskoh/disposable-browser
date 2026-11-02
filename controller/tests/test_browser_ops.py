"""Unit tests for PlaywrightOps' tab bookkeeping (no browser needed)."""

from dbrowser import browser_ops
from dbrowser.browser_ops import PlaywrightOps, _pick_active, _stable_order


def test_remembered_tab_wins_over_devtools_order():
    # Regression: Chromium kept listing the newer tab first after selecting tab 0.
    assert _pick_active(["a", "b"], "a", ["b", "a"]) == 0


def test_falls_back_to_devtools_order_when_remembered_tab_is_gone():
    assert _pick_active(["a", "b"], "closed", ["b", "a"]) == 1
    assert _pick_active(["a", "b"], None, ["a", "b"]) == 0


def test_falls_back_to_last_tab_without_any_information():
    assert _pick_active(["a", "b", None], None, []) == 2


def test_stable_order_ignores_attach_order_between_connections():
    # Regression: each call reconnects and Playwright may list pages in a different order.
    assert _stable_order(["a", "b"], ["b", "a"]) == [1, 0]


def test_stable_order_appends_new_tabs_and_drops_closed_ones():
    ids = ["c", None, "b", "a"]
    assert [ids[i] for i in _stable_order(["a", "gone", "b"], ids)] == ["a", "b", "c", None]


def test_remembered_sessions_are_bounded(monkeypatch):
    monkeypatch.setattr(browser_ops, "MAX_REMEMBERED_SESSIONS", 2)
    ops = PlaywrightOps()
    ops._session("s1").selected = "a"
    ops._session("s2").selected = "b"
    ops._session("s1")  # touch s1, so s2 is the oldest
    ops._session("s3").selected = "d"
    assert {k: v.selected for k, v in ops._sessions.items()} == {"s1": "a", "s3": "d"}
