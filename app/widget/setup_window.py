"""First-run setup — a polished, breathing key-entry window, same visual tier as the
Gemini Live bubble: dark acrylic glass, one blue accent, generous space.

Shown by run_desktop.py BEFORE the backend starts, only when the Gemini key (Live's
lifeblood) is missing. Collects the Gemini key (required) + an optional agent key
(Groq or OpenRouter), validates the Gemini one against the API, and writes them to
.env. Returns True once a working key is saved (or one already existed)."""
from __future__ import annotations

import os
import threading
from pathlib import Path

GEMINI_LINK = "https://aistudio.google.com/apikey"
GROQ_LINK = "https://console.groq.com/keys"
OPENROUTER_LINK = "https://openrouter.ai/keys"

# One accent, Live-blue. Everything else is neutral glass.
ACCENT = "#4F8DFF"
ACCENT_DIM = "#3D6FCC"
TEXT = "#F1F2F6"
MUTED = "#8B8C99"
FIELD_BG = "rgba(255,255,255,0.045)"
FIELD_BORDER = "rgba(255,255,255,0.09)"


def _env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _gemini_key_present() -> bool:
    if (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip():
        return True
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(_env_path())
        return bool((vals.get("GEMINI_API_KEY") or vals.get("GOOGLE_API_KEY") or "").strip())
    except Exception:
        return False


def _validate_gemini(key: str) -> tuple[bool, str]:
    """Confirm the key actually authenticates (cheap models.list call)."""
    key = (key or "").strip()
    if not key:
        return False, "Paste your Gemini key to continue."
    try:
        from google import genai
        client = genai.Client(api_key=key)
        next(iter(client.models.list()), None)  # one auth'd request; raises on a bad key
        return True, ""
    except Exception as exc:
        msg = str(exc)
        if "API_KEY_INVALID" in msg or "401" in msg or "PERMISSION" in msg.upper():
            return False, "That key didn't work — double-check you copied all of it."
        return False, f"Couldn't reach Google to verify the key ({msg[:60]})."


def _write_env(updates: dict[str, str]) -> None:
    """Set/append KEY=value lines in .env, preserving everything else."""
    path = _env_path()
    lines: list[str] = []
    try:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line else ""
        if k in remaining:
            out.append(f"{k}={remaining.pop(k)}")
        else:
            out.append(line)
    for k, v in remaining.items():
        out.append(f"{k}={v}")
    try:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        pass
    for k, v in updates.items():
        os.environ[k] = v


def ensure_keys_configured() -> bool:
    """If the Gemini key is missing, show the setup window. True once a key exists."""
    if _gemini_key_present():
        return True
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        # No Qt available — can't show the window; let the launcher proceed and the
        # backend will report the missing key the old way.
        return True
    app = QApplication.instance() or QApplication([])
    win = SetupWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    app.exec()
    return _gemini_key_present()


def _build():  # imports deferred so importing this module never needs Qt
    from PySide6.QtCore import Qt, Signal, QPoint
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
        QGraphicsDropShadowEffect,
    )
    from PySide6.QtGui import QColor

    def _link(text: str, url: str) -> str:
        return f'<a href="{url}" style="color:{ACCENT};text-decoration:none;">{text}</a>'

    class _SetupWindow(QWidget):
        _validated = Signal(bool, str)

        def __init__(self):
            super().__init__()
            self.setWindowTitle("Welcome to Orynn")
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setFixedWidth(468)
            self._drag = None

            # Glass card (rounded surface; the window itself is transparent so corners
            # stay clean).
            card = QFrame(self)
            card.setObjectName("card")
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(48)
            shadow.setColor(QColor(0, 0, 0, 170))
            shadow.setOffset(0, 12)
            card.setGraphicsEffect(shadow)

            lay = QVBoxLayout(card)
            lay.setContentsMargins(40, 38, 40, 34)
            lay.setSpacing(8)

            # Header: blue orb + wordmark, then subtitle.
            head = QHBoxLayout()
            head.setSpacing(12)
            orb = QLabel("●")
            orb.setStyleSheet(f"color:{ACCENT};font-size:16px;")
            name = QLabel("Orynn")
            name.setStyleSheet(f"color:{TEXT};font-size:23px;font-weight:700;")
            head.addWidget(orb)
            head.addWidget(name)
            head.addStretch(1)
            lay.addLayout(head)
            sub = QLabel("Let's get you set up — this only takes a moment.")
            sub.setStyleSheet(f"color:{MUTED};font-size:13px;")
            lay.addWidget(sub)
            lay.addSpacing(22)

            # Gemini field (required)
            lay.addWidget(self._field_label("GEMINI API KEY", "required", ACCENT))
            self.gemini = self._input("Paste your key here")
            lay.addWidget(self.gemini)
            lay.addWidget(self._helper(
                "Powers Orynn's voice & vision. " + _link("Get one free →", GEMINI_LINK)))
            lay.addSpacing(18)

            # Agent field (optional)
            lay.addWidget(self._field_label("AGENT KEY", "optional", MUTED))
            self.agent = self._input("Groq or OpenRouter key — for multi-step tasks")
            lay.addWidget(self.agent)
            lay.addWidget(self._helper(
                "Lets Orynn do bigger jobs on your PC. "
                + _link("Groq →", GROQ_LINK) + "  ·  " + _link("OpenRouter →", OPENROUTER_LINK)))
            lay.addSpacing(20)

            # Status line (validation feedback)
            self.status = QLabel("")
            self.status.setStyleSheet(f"color:{MUTED};font-size:12.5px;")
            self.status.setWordWrap(True)
            lay.addWidget(self.status)

            # Continue button
            self.btn = QPushButton("Continue")
            self.btn.setObjectName("primary")
            self.btn.setCursor(Qt.PointingHandCursor)
            self.btn.setFixedHeight(46)
            self.btn.clicked.connect(self._on_continue)
            lay.addWidget(self.btn)

            outer = QVBoxLayout(self)
            outer.setContentsMargins(18, 18, 18, 18)  # room for the drop shadow
            outer.addWidget(card)
            self.setStyleSheet(self._qss())
            self._validated.connect(self._on_validated)
            self.gemini.returnPressed.connect(self._on_continue)
            self.gemini.setFocus()
            self._center()

        # ---- small builders -------------------------------------------------
        def _field_label(self, title: str, tag: str, tag_color: str):
            w = QLabel(f'<span style="letter-spacing:1px;">{title}</span>'
                       f'<span style="color:{tag_color};"> · {tag}</span>')
            w.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")
            return w

        def _input(self, placeholder: str):
            from PySide6.QtWidgets import QLineEdit
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            e.setMinimumHeight(44)
            e.setObjectName("field")
            return e

        def _helper(self, html: str):
            from PySide6.QtWidgets import QLabel
            l = QLabel(html)
            l.setOpenExternalLinks(True)
            l.setStyleSheet(f"color:{MUTED};font-size:12px;")
            l.setWordWrap(True)
            return l

        # ---- behavior -------------------------------------------------------
        def _on_continue(self):
            key = self.gemini.text().strip()
            if not key:
                self._set_status("Paste your Gemini key to continue.", error=True)
                return
            self.btn.setEnabled(False)
            self.btn.setText("Checking…")
            self._set_status("Verifying your key with Google…", error=False)
            threading.Thread(target=self._do_validate, args=(key,), daemon=True).start()

        def _do_validate(self, key: str):
            ok, msg = _validate_gemini(key)
            self._validated.emit(ok, msg)

        def _on_validated(self, ok: bool, msg: str):
            if not ok:
                self.btn.setEnabled(True)
                self.btn.setText("Continue")
                self._set_status(msg, error=True)
                return
            updates = {"GEMINI_API_KEY": self.gemini.text().strip()}
            agent = self.agent.text().strip()
            if agent:
                # gsk_ = Groq, sk-or = OpenRouter; default unknown to OpenRouter.
                key_name = "GROQ_API_KEY" if agent.lower().startswith("gsk_") else "OPENROUTER_API_KEY"
                updates[key_name] = agent
            _write_env(updates)
            self._set_status("All set — starting Orynn.", error=False)
            self.btn.setText("Done ✓")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(450, self.close)

        def _set_status(self, text: str, error: bool):
            self.status.setText(text)
            self.status.setStyleSheet(
                f"color:{'#FF6B6B' if error else ACCENT};font-size:12.5px;")

        # ---- chrome ---------------------------------------------------------
        def _center(self):
            from PySide6.QtGui import QGuiApplication
            scr = QGuiApplication.primaryScreen().availableGeometry()
            self.adjustSize()
            self.move(scr.center().x() - self.width() // 2,
                      scr.center().y() - self.height() // 2)

        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, e):
            if self._drag is not None and e.buttons() & Qt.LeftButton:
                self.move(e.globalPosition().toPoint() - self._drag)

        def mouseReleaseEvent(self, e):
            self._drag = None

        def showEvent(self, e):
            super().showEvent(e)
            try:
                from .qt_shell import _apply_acrylic
                _apply_acrylic(int(self.winId()), 0x1C1C24_00)
            except Exception:
                pass

        def _qss(self) -> str:
            return f"""
            #card {{
                background: rgba(22,22,28,0.96);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 22px;
            }}
            QLineEdit#field {{
                background: {FIELD_BG};
                border: 1px solid {FIELD_BORDER};
                border-radius: 12px;
                padding: 0 14px;
                color: {TEXT};
                font-size: 14px;
                selection-background-color: {ACCENT};
            }}
            QLineEdit#field:focus {{ border: 1px solid {ACCENT}; background: rgba(79,141,255,0.07); }}
            QPushButton#primary {{
                background: {ACCENT};
                border: none; border-radius: 12px;
                color: white; font-size: 15px; font-weight: 600;
            }}
            QPushButton#primary:hover {{ background: #5C97FF; }}
            QPushButton#primary:disabled {{ background: {ACCENT_DIM}; color: rgba(255,255,255,0.7); }}
            """

    return _SetupWindow


# Lazily resolve the Qt class so `import setup_window` never requires PySide6.
def __getattr__(name):
    if name == "SetupWindow":
        return _build()
    raise AttributeError(name)
