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
