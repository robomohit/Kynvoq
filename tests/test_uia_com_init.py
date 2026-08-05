"""Regression tests for per-thread COM (STA) init on the UIA path.

The desktop agent runs every UIA call on asyncio `to_thread` pool workers. Those
threads never initialized COM, so comtypes lazily joined the MTA and a tree walk
racing the foreground window's input-sync handling crashed the whole process with
a *fatal* RPC_E_CANTCALLOUT_ININPUTSYNCCALL (0x8001010d). The fix inits COM as STA
once per thread in `_ensure_uia_config`; these tests pin that contract without a
real Windows desktop.
"""
from __future__ import annotations

import threading

import pytest

from app.widget import desktop_features as df


class _FakeUia:
    """Stand-in for the `uiautomation` module recording COM init calls."""

    def __init__(self) -> None:
        self.init_calls = 0
        self.timeout_set = None
        self.interval_set = None

    def InitializeUIAutomationInCurrentThread(self) -> None:
        self.init_calls += 1

    def SetGlobalSearchTimeout(self, val) -> None:
        self.timeout_set = val

    def SetGlobalSearchInterval(self, val) -> None:
        self.interval_set = val


@pytest.fixture(autouse=True)
def _reset_uia_state(monkeypatch):
    # Each test starts from a clean global + thread-local state so order doesn't
    # leak the "already configured / already inited" flags between cases.
    monkeypatch.setattr(df, "_uia_configured", False, raising=False)
    monkeypatch.setattr(df, "_uia_thread_com", threading.local(), raising=False)
    yield


def test_ensure_uia_config_inits_com_on_calling_thread():
    fake = _FakeUia()
    df._ensure_uia_config(fake)
    assert fake.init_calls == 1
    # Global fast-search tuning still applied.
    assert fake.timeout_set == 1.0
    assert fake.interval_set == 0.05


def test_com_init_is_idempotent_per_thread():
    fake = _FakeUia()
    for _ in range(5):
        df._ensure_uia_config(fake)
    # COM inited exactly once on this thread despite repeated entry-point calls.
    assert fake.init_calls == 1


def test_com_init_runs_again_on_a_different_thread():
    fake = _FakeUia()
    df._ensure_uia_config(fake)  # main/test thread -> 1

    def worker():
        # A pool worker (the real crash source) must get its own STA init.
        df._ensure_uia_thread_com(fake)

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert fake.init_calls == 2  # once per distinct thread


def test_com_init_swallows_changed_mode_error():
    # If the thread already joined a different apartment, CoInitializeEx raises
    # (RPC_E_CHANGED_MODE). We must not propagate it out of a UIA entry point.
    class _Raising(_FakeUia):
        def InitializeUIAutomationInCurrentThread(self) -> None:
            raise OSError("RPC_E_CHANGED_MODE")

    fake = _Raising()
    df._ensure_uia_config(fake)  # must not raise
    # Marked done so we don't thrash CoInitializeEx on every subsequent call.
    assert getattr(df._uia_thread_com, "inited", False) is True
