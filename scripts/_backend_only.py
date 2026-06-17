"""Start ONLY the Orynn FastAPI backend on PORT (no pywebview/overlay).

Used to get a clean, freshly-loaded backend for testing the desktop executor
without the full GUI stack. Loads .env first so all API keys are present.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

import uvicorn
from app.main import app

PORT = int(os.getenv("ORYNN_PORT") or "8000")
if __name__ == "__main__":
    print(f"[backend-only] starting on 127.0.0.1:{PORT}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
