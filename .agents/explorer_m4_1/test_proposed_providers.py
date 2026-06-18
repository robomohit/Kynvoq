import sys
import os
import pytest
import logging
import importlib.util
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.insert(0, r"c:\Users\ACER\Desktop\Ai_computer\Orynn")

# Load proposed_providers.py as app.providers so relative imports work correctly
spec = importlib.util.spec_from_file_location(
    "app.providers",
    os.path.join(os.path.dirname(__file__), "proposed_providers.py")
)
providers = importlib.util.module_from_spec(spec)
sys.modules["app.providers"] = providers
spec.loader.exec_module(providers)

import httpx

class FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=MagicMock(),
                response=self
            )

    def json(self):
        return {"choices": [{"message": {"content": "mocked response"}}]}

class FlakyClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def post(self, *args, **kwargs):
        if self.calls >= len(self.responses):
            return FakeResp(200)
        resp = self.responses[self.calls]
        self.calls += 1
        if isinstance(resp, Exception):
            raise resp
        return resp

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

@pytest.fixture
def provider():
    p = providers.PlannerProvider(model="groq/llama3")
    p._groq_key = "test-key"
    p._openrouter_key = "test-key"
    p._google_key = "test-key"
    p._openai_key = "test-key"
    return p

def test_chat_groq_retries_408_and_logs_warning(provider, caplog):
    # Test that 408 is retried and a warning is logged
    client = FlakyClient([
        FakeResp(408),
        FakeResp(200)
    ])
    provider._http_client = client

    with patch("app.providers.time.sleep") as mock_sleep, \
         patch("app.providers._build_llm_http_client", return_value=client):
        with caplog.at_level(logging.WARNING):
            res = provider._chat_groq("sys", "prompt")
            assert res == "mocked response"
            assert client.calls == 2
            mock_sleep.assert_called_once_with(1) # 2 ** 0

            # Verify warning was logged
            warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
            assert len(warnings) == 1
            assert "Groq API HTTP error 408" in warnings[0]

def test_chat_groq_retries_503_and_logs_warning(provider, caplog):
    # Test that 5xx (e.g. 503) is retried and a warning is logged
    client = FlakyClient([
        FakeResp(503),
        FakeResp(200)
    ])
    provider._http_client = client

    with patch("app.providers.time.sleep") as mock_sleep, \
         patch("app.providers._build_llm_http_client", return_value=client):
        with caplog.at_level(logging.WARNING):
            res = provider._chat_groq("sys", "prompt")
            assert res == "mocked response"
            assert client.calls == 2
            mock_sleep.assert_called_once_with(1)

            # Verify warning was logged
            warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
            assert len(warnings) == 1
            assert "Groq API HTTP error 503" in warnings[0]

def test_chat_groq_retries_connection_error_and_logs_warning(provider, caplog):
    # Test that connection/transport error is retried and a warning is logged
    client = FlakyClient([
        httpx.ConnectError("Connection failed"),
        FakeResp(200)
    ])
    provider._http_client = client

    with patch("app.providers.time.sleep") as mock_sleep, \
         patch("app.providers._build_llm_http_client", return_value=client):
        with caplog.at_level(logging.WARNING):
            res = provider._chat_groq("sys", "prompt")
            assert res == "mocked response"
            assert client.calls == 2
            mock_sleep.assert_called_once_with(1)

            # Verify warning was logged
            warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
            assert len(warnings) == 1
            assert "Groq API connection/timeout error" in warnings[0]

def test_chat_groq_fails_on_400(provider, caplog):
    # Test that non-retryable error (e.g. 400) is NOT retried and raises immediately
    client = FlakyClient([
        FakeResp(400)
    ])
    provider._http_client = client

    with patch("app.providers.time.sleep") as mock_sleep, \
         patch("app.providers._build_llm_http_client", return_value=client):
        with pytest.raises(httpx.HTTPStatusError):
            provider._chat_groq("sys", "prompt")
        assert client.calls == 1
        assert not mock_sleep.called

        # Verify no warning was logged
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 0

def test_chat_ollama_retries_and_logs(provider, caplog):
    # Test that _chat_ollama (which didn't have retries previously) now retries on 429
    client = FlakyClient([
        FakeResp(429),
        FakeResp(200)
    ])
    # For Ollama, the mock response json is a bit different:
    client.responses[1] = FakeResp(200)
    client.responses[1].json = lambda: {"message": {"content": "ollama response"}}
    provider._http_client = client

    with patch("app.providers.time.sleep") as mock_sleep:
        with caplog.at_level(logging.WARNING):
            res = provider._chat_ollama("sys", "prompt")
            assert res == "ollama response"
            assert client.calls == 2
            mock_sleep.assert_called_once_with(1)

            warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
            assert len(warnings) == 1
            assert "Ollama API HTTP error 429" in warnings[0]
