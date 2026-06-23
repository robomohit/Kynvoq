"""First-run setup: key presence check + .env writing (the non-GUI logic). Importing
the module must NOT require Qt (the window is built lazily)."""
import app.widget.setup_window as sw


def test_import_does_not_require_qt():
    # The module imports cleanly without PySide6 present at import time.
    assert hasattr(sw, "ensure_keys_configured")
    assert hasattr(sw, "_write_env")


def test_gemini_key_present_env_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "_env_path", lambda: tmp_path / ".env")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert sw._gemini_key_present() is False
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    assert sw._gemini_key_present() is True


def test_write_env_preserves_updates_and_appends(tmp_path, monkeypatch):
    envf = tmp_path / ".env"
    envf.write_text("EXISTING=1\nGEMINI_API_KEY=old\n", encoding="utf-8")
    monkeypatch.setattr(sw, "_env_path", lambda: envf)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    sw._write_env({"GEMINI_API_KEY": "newkey", "OPENROUTER_API_KEY": "sk-or-x"})

    txt = envf.read_text(encoding="utf-8")
    assert "EXISTING=1" in txt                 # untouched line preserved
    assert "GEMINI_API_KEY=newkey" in txt      # existing key updated in place
    assert "=old" not in txt                   # old value gone
    assert "OPENROUTER_API_KEY=sk-or-x" in txt  # new key appended
    import os
    assert os.environ["GEMINI_API_KEY"] == "newkey"   # live process env updated too


def test_validate_gemini_rejects_empty():
    ok, msg = sw._validate_gemini("   ")
    assert ok is False and "paste" in msg.lower()


from unittest.mock import patch, MagicMock
import urllib.error

def test_validate_agent_key_empty():
    ok, msg = sw._validate_agent_key("")
    assert ok is True and msg == ""
    ok, msg = sw._validate_agent_key("  ")
    assert ok is True and msg == ""

def test_validate_agent_key_unrecognized():
    ok, msg = sw._validate_agent_key("some-weird-key-format")
    assert ok is True and msg == ""

@patch("urllib.request.urlopen")
def test_validate_agent_key_anthropic(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    
    ok, msg = sw._validate_agent_key("sk-ant-12345")
    assert ok is True
    
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
    ok, msg = sw._validate_agent_key("sk-ant-invalid")
    assert ok is False
    assert "Anthropic" in msg

@patch("urllib.request.urlopen")
def test_validate_agent_key_groq(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    mock_urlopen.side_effect = None
    
    ok, msg = sw._validate_agent_key("gsk_12345")
    assert ok is True
    
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
    ok, msg = sw._validate_agent_key("gsk_invalid")
    assert ok is False
    assert "Groq" in msg

@patch("urllib.request.urlopen")
def test_validate_agent_key_openrouter(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    mock_urlopen.side_effect = None
    
    ok, msg = sw._validate_agent_key("sk-or-12345")
    assert ok is True
    
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
    ok, msg = sw._validate_agent_key("sk-or-invalid")
    assert ok is False
    assert "OpenRouter" in msg

@patch("urllib.request.urlopen")
def test_validate_agent_key_openai(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    mock_urlopen.side_effect = None
    
    ok, msg = sw._validate_agent_key("sk-proj-12345")
    assert ok is True
    
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
    ok, msg = sw._validate_agent_key("sk-proj-invalid")
    assert ok is False
    assert "OpenAI" in msg

