# Orynn — online installer

A tiny **OrynnSetup.exe** that downloads the app on first run, installs it, and
makes shortcuts. The first launch of `Orynn.exe` shows the key window, so the
installer + app together onboard a brand-new user (no `.env` editing).

```
OrynnSetup.exe  ──downloads──▶  Orynn-win64.zip  ──extract──▶  %LOCALAPPDATA%\Programs\Orynn\Orynn.exe
   (tiny, Inno)                  (GitHub release)                first run → setup window (keys)
```

## One-time code change already in place
A frozen `.exe` has no `python -m`, so `run_desktop.py` now relaunches **itself**
as `Orynn.exe --overlay` for the companion overlay (handled at the top of
`__main__`; dev mode is unchanged). This was the real blocker — done.

## Build & release steps
1. **Build the payload** (in the project venv, from repo root):
   ```
   python packaging/build.py
   ```
   → `dist/Orynn/Orynn.exe` (one-folder app) and `dist/Orynn-win64.zip`.

   ⚠️ First build almost always hits `ModuleNotFoundError` at runtime for a few
   dynamically-imported packages — add each to `COLLECT`/`HIDDEN` in `build.py`
   and rebuild. Then **run `dist/Orynn/Orynn.exe` and confirm it actually launches**
   (Live toggles, the overlay appears) before shipping.

2. **Publish the payload**: upload `Orynn-win64.zip` to a GitHub Release
   (`robomohit/Orynn`). The installer's `PayloadUrl` points at
   `releases/latest/download/Orynn-win64.zip`.

3. **Build the installer**: install [Inno Setup](https://jrsoftware.org/isinfo.php)
   (6.1+), then:
   ```
   iscc packaging\orynn_online_setup.iss
   ```
   → `Output\OrynnSetup.exe` — the small thing you hand out.

## Honest status / what still needs a real pass
- ✅ Stage 1 (frozen entry point) — done & verified in dev.
- ✅ Build script, installer script, this runbook — written.
- ⏳ The PyInstaller build itself is **iterative** for an app this size (PySide6 +
  win32 + uiautomation + FastAPI + MCP). Expect 1–3 rounds of fixing hidden
  imports, then a launch test on this machine.
- ⏳ A **clean-machine test** (a PC without Python/keys) is the only true proof the
  installer works end-to-end.
- Note: PyInstaller exes sometimes trip Windows SmartScreen / antivirus until the
  binary builds reputation (or you code-sign it). Code signing is optional but nice
  for distribution.
