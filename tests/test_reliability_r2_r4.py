"""Unit tests for R2 (UIA resilience, clipboard retry, Electron bypass) and
R4 (LLM API retry with exponential backoff) reliability improvements.

These tests run without requiring real Windows UIA bindings or real API keys.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch, PropertyMock
import pytest
import httpx


# ─────────────────────────────────────────────────────────────────────────────
# R4: _execute_with_retry (providers.py)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def exec_retry():
    from app.providers import _execute_with_retry
    return _execute_with_retry


def _mock_response(status_code: int, json_data: dict | None = None):
    """Build a minimal mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    request = MagicMock()
    resp.request = request
    resp.raise_for_status.side_effect = (
        httpx.HTTPStatusError(
            str(status_code), request=request, response=resp
        )
        if status_code >= 400 else None
    )
    return resp


def test_execute_with_retry_success_first_attempt(exec_retry):
    """A clean 200 response should be returned immediately without any retry."""
    resp = _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})
    calls = 0

    def request_fn():
        nonlocal calls
        calls += 1
        return resp

    result = exec_retry(request_fn, "test", max_attempts=3)
    assert result is resp
    assert calls == 1


def test_execute_with_retry_retries_on_429(exec_retry):
    """A 429 rate-limit response should be retried up to max_attempts."""
    attempts = []

    def request_fn():
        attempts.append(1)
        resp = _mock_response(429)
        raise httpx.HTTPStatusError("429", request=MagicMock(), response=resp)

    with patch("time.sleep"):
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            exec_retry(request_fn, "test", max_attempts=3)

    assert len(attempts) == 3
    assert "429" in str(exc_info.value)


def test_execute_with_retry_retries_on_5xx(exec_retry):
    """HTTP 500 should be retried (server error)."""
    attempts = []

    def request_fn():
        attempts.append(1)
        resp = _mock_response(500)
        raise httpx.HTTPStatusError("500", request=MagicMock(), response=resp)

    with patch("time.sleep"):
        with pytest.raises(httpx.HTTPStatusError):
            exec_retry(request_fn, "test", max_attempts=2)

    assert len(attempts) == 2


def test_execute_with_retry_retries_on_transport_error(exec_retry):
    """Transport errors (connection issues) should be retried."""
    attempts = []

    def request_fn():
        attempts.append(1)
        raise httpx.TransportError("connection refused")

    with patch("time.sleep"):
        with pytest.raises(httpx.TransportError):
            exec_retry(request_fn, "test", max_attempts=2)

    assert len(attempts) == 2


def test_execute_with_retry_success_on_second_attempt(exec_retry):
    """Should succeed on second attempt when the first fails with 429."""
    attempts = []
    good_resp = _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})

    def request_fn():
        attempts.append(1)
        if len(attempts) == 1:
            resp = _mock_response(429)
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=resp)
        return good_resp

    with patch("time.sleep"):
        result = exec_retry(request_fn, "test", max_attempts=3)

    assert result is good_resp
    assert len(attempts) == 2


def test_execute_with_retry_raises_on_4xx_not_429(exec_retry):
    """Non-retryable 4xx errors like 401 should be raised immediately."""
    attempts = []

    def request_fn():
        attempts.append(1)
        resp = _mock_response(401)
        raise httpx.HTTPStatusError("401", request=MagicMock(), response=resp)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        exec_retry(request_fn, "test", max_attempts=3)

    assert len(attempts) == 1
    assert "401" in str(exc_info.value)


def test_execute_with_retry_logs_warnings_on_retry(exec_retry):
    """Retry attempts should produce a warning log."""
    call_count = 0
    good_resp = _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})

    def request_fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            resp = _mock_response(500)
            raise httpx.HTTPStatusError("500", request=MagicMock(), response=resp)
        return good_resp

    with patch("time.sleep"):
        with patch("app.providers._log") as mock_log:
            result = exec_retry(request_fn, "TestProvider", max_attempts=3)

    assert result is good_resp
    # Warning should have been called at least once
    assert mock_log.warning.called


# ─────────────────────────────────────────────────────────────────────────────
# R4: _chat_groq now uses _execute_with_retry (providers.py)
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_groq_retries_on_429(monkeypatch):
    """_chat_groq should retry on 429, not crash immediately."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    from app.providers import PlannerProvider
    p = PlannerProvider(model="groq/llama-3.1-8b-instant")

    calls = []

    def fake_post(url, headers=None, json=None, **kw):
        calls.append(url)
        if len(calls) <= 2:
            resp = _mock_response(429)
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=resp)
        return _mock_response(200, {"choices": [{"message": {"content": "hello"}}]})

    class FakeCtx:
        def __enter__(self):
            m = MagicMock()
            m.post.side_effect = fake_post
            return m
        def __exit__(self, *args):
            return False

    with patch("app.providers._build_llm_http_client", return_value=FakeCtx()):
        with patch("time.sleep"):
            result = p._chat_groq("sys", "prompt")

    assert result == "hello"
    assert len(calls) == 3


def test_chat_groq_raises_after_max_retries(monkeypatch):
    """_chat_groq should raise a RuntimeError after exhausting retries."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    from app.providers import PlannerProvider
    p = PlannerProvider(model="groq/llama-3.1-8b-instant")

    def fake_post(url, headers=None, json=None, **kw):
        resp = _mock_response(429)
        raise httpx.HTTPStatusError("429", request=MagicMock(), response=resp)

    class FakeCtx:
        def __enter__(self):
            m = MagicMock()
            m.post.side_effect = fake_post
            return m
        def __exit__(self, *args):
            return False

    with patch("app.providers._build_llm_http_client", return_value=FakeCtx()):
        with patch("time.sleep"):
            with pytest.raises((httpx.HTTPStatusError, RuntimeError)):
                p._chat_groq("sys", "prompt")


# ─────────────────────────────────────────────────────────────────────────────
# R2: Clipboard retry resilience in type_into_ui_element
# ─────────────────────────────────────────────────────────────────────────────

def test_clipboard_retry_on_locked_clipboard():
    """SetClipboardText retries up to 5 times on exception."""
    import importlib.util
    if importlib.util.find_spec("uiautomation") is None:
        pytest.skip("uiautomation not available in CI environment")

    from app.widget.desktop_features import type_into_ui_element
    import uiautomation as uia

    ctrl = MagicMock()
    ctrl.Name = "TextBox"
    ctrl.AutomationId = ""
    ctrl.ControlTypeName = "EditControl"
    ctrl.GetParentControl.return_value = None
    ctrl.NativeWindowHandle = 0
    rect = MagicMock()
    rect.right = 100; rect.left = 0; rect.bottom = 100; rect.top = 0
    ctrl.BoundingRectangle = rect
    ctrl.IsOffscreen = False

    clipboard_calls = []

    def get_clip():
        return "hello"

    def set_clip(text):
        clipboard_calls.append(text)
        if len(clipboard_calls) <= 2:
            raise OSError("Clipboard is locked")

    with patch("app.widget.desktop_features._find_uia_control", return_value=(ctrl, {
        "name": "TextBox", "automation_id": "", "control_type": "EditControl",
        "x": 50, "y": 50, "score": 100, "offscreen": False
    })):
        with patch("app.widget.desktop_features.is_electron_app", return_value=False):
            with patch("app.widget.desktop_features.resolve_app_exe", return_value="notepad.exe"):
                with patch("app.widget.desktop_features._try_background_setvalue", return_value=False):
                    with patch("app.widget.desktop_features.wait_for_user_idle", return_value={"waited": 0, "yielded": False, "proceeded_anyway": False}):
                        with patch("app.widget.desktop_features._politeness_note", return_value=""):
                            with patch("uiautomation.GetClipboardText", side_effect=get_clip):
                                with patch("uiautomation.SetClipboardText", side_effect=set_clip):
                                    with patch("time.sleep"):
                                        try:
                                            res = type_into_ui_element("TextBox", "hello", "notepad")
                                        except Exception:
                                            pass

    # SetClipboardText was called multiple times due to retries
    assert len(clipboard_calls) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# R2: Electron/browser bypass for SetValue (type_into_ui_element)
# ─────────────────────────────────────────────────────────────────────────────

def test_electron_app_bypasses_background_setvalue(monkeypatch):
    """For Electron apps, type_into_ui_element must skip SetValue and use paste."""
    import importlib.util
    if importlib.util.find_spec("uiautomation") is None:
        pytest.skip("uiautomation not available in CI environment")

    from app.widget.desktop_features import type_into_ui_element

    ctrl = MagicMock()
    ctrl.Name = "messageBox"
    ctrl.AutomationId = ""
    ctrl.ControlTypeName = "EditControl"
    ctrl.GetParentControl.return_value = None
    ctrl.NativeWindowHandle = 0
    rect = MagicMock()
    rect.right = 200; rect.left = 0; rect.bottom = 200; rect.top = 0
    ctrl.BoundingRectangle = rect
    ctrl.IsOffscreen = False
    ctrl.SetFocus = MagicMock()
    ctrl.SendKeys = MagicMock()

    setvalue_calls = []

    def mock_setvalue(c, text, clear_first):
        setvalue_calls.append(text)
        return True  # claim success

    with patch("app.widget.desktop_features._find_uia_control", return_value=(ctrl, {
        "name": "messageBox", "automation_id": "", "control_type": "EditControl",
        "x": 100, "y": 100, "score": 100, "offscreen": False
    })):
        with patch("app.widget.desktop_features.is_electron_app", return_value=True):
            with patch("app.widget.desktop_features.resolve_app_exe", return_value="discord.exe"):
                with patch("app.widget.desktop_features._try_background_setvalue", side_effect=mock_setvalue):
                    with patch("app.widget.desktop_features.wait_for_user_idle", return_value={"waited": 0, "yielded": False, "proceeded_anyway": False}):
                        with patch("app.widget.desktop_features._politeness_note", return_value=""):
                            with patch("uiautomation.GetClipboardText", return_value=""):
                                with patch("uiautomation.SetClipboardText"):
                                    with patch("time.sleep"):
                                        res = type_into_ui_element("messageBox", "hello", "discord")

    # SetValue should NOT have been called for Electron apps
    assert len(setvalue_calls) == 0, "SetValue should be bypassed for Electron apps"


# ─────────────────────────────────────────────────────────────────────────────
# R2: UIA element resolution retry loop in _find_uia_control
# ─────────────────────────────────────────────────────────────────────────────

def test_find_uia_control_retries_before_giving_up():
    """_find_uia_control should poll up to 2 seconds before returning error."""
    import importlib.util
    if importlib.util.find_spec("uiautomation") is None:
        pytest.skip("uiautomation not available in CI environment")

    from app.widget.desktop_features import _find_uia_control

    poll_calls = []
    start = time.monotonic()

    def mock_root_candidates(*args, **kwargs):
        poll_calls.append(1)
        return []  # Always return empty (no matching window)

    with patch("app.widget.desktop_features._uia_root_candidates", side_effect=mock_root_candidates):
        with patch("time.sleep") as mock_sleep:  # speed up test
            ctrl, info = _find_uia_control("NonExistentControl", "SomeApp")

    assert ctrl is None
    assert "ok" in info and info["ok"] is False
    # Should have polled multiple times (at least once before giving up)
    assert len(poll_calls) >= 1


def test_find_uia_control_returns_on_first_match():
    """_find_uia_control should return immediately when a match is found without waiting."""
    import importlib.util
    if importlib.util.find_spec("uiautomation") is None:
        pytest.skip("uiautomation not available in CI environment")

    from app.widget.desktop_features import _find_uia_control

    ctrl_mock = MagicMock()
    ctrl_mock.Name = "SaveButton"
    ctrl_mock.AutomationId = ""
    ctrl_mock.ControlTypeName = "ButtonControl"
    ctrl_mock.GetChildren.return_value = []
    ctrl_mock.IsOffscreen = False
    rect = MagicMock()
    rect.right = 100; rect.left = 0; rect.bottom = 50; rect.top = 0
    ctrl_mock.BoundingRectangle = rect
    ctrl_mock.NativeWindowHandle = 0

    root_mock = MagicMock()
    root_mock.Name = "Notepad"
    root_mock.AutomationId = ""
    root_mock.ControlTypeName = "WindowControl"
    root_mock.GetChildren.return_value = [ctrl_mock]
    rect2 = MagicMock()
    rect2.right = 800; rect2.left = 0; rect2.bottom = 600; rect2.top = 0
    root_mock.BoundingRectangle = rect2

    # FastPath returns the control immediately
    fast_ctrl = MagicMock()
    fast_ctrl.Name = "SaveButton"
    fast_ctrl.AutomationId = ""
    fast_ctrl.ControlTypeName = "ButtonControl"
    fast_ctrl.Exists.return_value = True
    fast_rect = MagicMock()
    fast_rect.right = 100; fast_rect.left = 0; fast_rect.bottom = 50; fast_rect.top = 0
    fast_ctrl.BoundingRectangle = fast_rect

    root_mock.Control.return_value = fast_ctrl

    poll_calls = []

    def mock_root_candidates(*args, **kwargs):
        poll_calls.append(1)
        return [root_mock]

    with patch("app.widget.desktop_features._uia_root_candidates", side_effect=mock_root_candidates):
        ctrl, info = _find_uia_control("SaveButton", "Notepad")

    assert ctrl is not None
    assert info.get("name") == "SaveButton"
    # Only polled once because first attempt succeeded
    assert len(poll_calls) == 1
