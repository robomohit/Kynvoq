# 03 — Universal Windows App Launch Methods

**Date:** 2026-06-22  
**Scope:** How to open any installed Windows app at scale (hundreds of apps) without per-app playbooks — launch-layer research for Orynn's voice fast-path and back-office agent.  
**Codebase reviewed:** `app/tools.py` (`detect_app_launch_intent`, `_KNOWN_LAUNCH_APPS`, `open_known_app`, `_launch_gui_command`), `app/widget/textbox_overlay.py` (`DESKTOP_HARDENING`), `app/widget/desktop_features.py` (`resolve_app_exe`), `app/agent.py` (launch fast-path)

**Related:** [00-master-strategy.md](./00-master-strategy.md) · [../windows-automation-research.md §2](../windows-automation-research.md#2-special-windows-mechanisms) · [07-app-framework-taxonomy.md](./07-app-framework-taxonomy.md)

**Verified on:** Windows 11 (build 26200), Acer OEM machine — 121 `Get-StartApps` entries, 16 user Start Menu shortcuts, `winget` not present in PATH.

---

## Executive Summary

Scaling app launch to hundreds of apps does **not** mean hard-coding hundreds of exe paths. Windows already exposes a **tiered launch stack** — each tier trades determinism for coverage:

| Tier | Mechanism | Coverage | Determinism | Orynn today |
|------|-----------|----------|-------------|-------------|
| 0 | Voice fast-path (`_KNOWN_LAUNCH_APPS`) | 7 built-ins | Very high | ✅ `detect_app_launch_intent` → `open_known_app` |
| 1 | OS-routed shortcuts (`start`, Run aliases, `ms-settings:`) | Built-ins + registered protocols | High | ✅ `run_command` GUI detection |
| 2 | AUMID / `shell:AppsFolder` | All Start-pinned + UWP + indexed Win32 | High (if AUMID resolved) | ❌ not wired |
| 3 | Start Menu `.lnk` index | User-installed apps with shortcuts | High | ❌ not wired |
| 4 | `Get-StartApps` name → AppID lookup | ~100–200 per machine | Medium (duplicate names) | ❌ not wired |
| 5 | `where.exe` / PATH / common install roots | CLI tools, some Win32 | Low–medium | Partial (`resolve_app_exe` scans running windows only) |
| 6 | Win+Search UI automation | Anything indexed by Windows Search | Low (UI changes per build) | Prompt-only (`DESKTOP_HARDENING`) |
| 7 | `winget list` / registry inventory | Package metadata | Read-only discovery | ❌ not wired |

**Key architectural insight:** Orynn correctly splits launch into a **narrow voice registry** (tier 0) and a **planner path** (tiers 1–7). The gap is not philosophy — it is missing a **runtime app index** built once per session from `Get-StartApps` + Start Menu `.lnk` files, with tier 0 as a curated override table.

---

## 1. Launch Method Catalog

### 1.1 Method comparison (master table)

| Method | Command / API | Best for | Verify window by | Fragility |
|--------|---------------|----------|------------------|-----------|
| `start <alias>` | `start notepad` | Built-ins on PATH | Title substring | Low |
| `start "" "path"` | Quoted path with empty title | Arbitrary `.exe` / `.lnk` | Exe basename or title | Low |
| `cmd /c start` | Same as `start` via cmd | Agent emits cmd-style | Same | Low |
| `Start-Process` | `powershell -command Start-Process calc` | PS-native agents | Same | Low |
| `explorer <path>` | Opens folder or delegates file assoc | Folders, `.lnk`, URIs | Context-dependent | Low |
| `explorer shell:AppsFolder\<AUMID>` | UWP / Store / indexed apps | Calculator, Photos, Copilot | AUMID-mapped title | Low |
| `start <protocol>:` | `start ms-settings:`, `start spotify:` | Registered URI handlers | URI→title map | Medium (unregistered = error dialog) |
| `ShellExecute` / `os.startfile` | Python equivalent of `start` | Same as above | Same | Low |
| Win+Search typing | `key_combo win` → type → Enter | Unknown app by display name | Search result / title | **High** |
| `.lnk` direct | `start "" "C:\...\App.lnk"` | Start Menu installs | Shortcut target exe | Low |
| `where.exe` | `where notepad` | PATH-resolved tools | N/A (discovery only) | Medium |
| `Get-StartApps` | PowerShell built-in | Name → AppID index | N/A (discovery) | Low |
| `winget list` | CLI package inventory | Installed package names/IDs | N/A (discovery) | Medium (not always installed) |

---

## 2. Win+Search / Start Menu Programmatic Launch

### 2.1 What the user sees

`Win` opens Start / Search. Typing filters the app list; `Enter` launches the best match. This is what `DESKTOP_HARDENING` instructs the back-office agent to do for apps not in the curated registry:

```text
1. To OPEN or launch an app, press the Windows key, type the app name,
   then press Enter (Start-menu search) - this works for any installed app.
```

### 2.2 Automating it (possible but discouraged as primary)

```
key_combo("win")           # open search
keyboard_type("Discord")   # filter
key_combo("enter")         # launch best match
wait_for_window("Discord")
```

**Problems:**

| Issue | Impact |
|-------|--------|
| Search UI changes per Windows 11 build (taskbar search vs full Start) | Breaks selectors and timing |
| Web results mixed with apps ("Search the web for…") | Wrong `Enter` target |
| Partial matches / duplicate names | May open Edge "Calculator" PWA instead of `calc.exe` (observed on test machine: two `Calculator` entries in `Get-StartApps`) |
| Copilot / AI search integration | Extra UI layers |
| Focus / IME / non-English SKUs | Typing reliability varies |
| Slower than direct launch | 2–4 s vs <500 ms for `start` / AUMID |

**Verdict for Orynn:** Keep Win+Search as **tier-6 fallback** in agent prompts only. Never add it to `detect_app_launch_intent`. Prefer building a local index (tiers 2–4) so "open Discord" resolves to a `.lnk` or AUMID without UI simulation.

### 2.3 Start menu folder structure

Windows aggregates shortcuts from multiple locations:

| Location | Scope | Typical contents |
|----------|-------|------------------|
| `%AppData%\Microsoft\Windows\Start Menu\Programs` | Per-user | User-installed apps (Cursor, Ollama, Edge…) |
| `%AppData%\Microsoft\Windows\Start Menu\Programs\Startup` | Per-user autostart | User startup items |
| `%ProgramData%\Microsoft\Windows\Start Menu\Programs` | All users | Vendor shortcuts (Office, Adobe, tools) |
| `%ProgramData%\Microsoft\Windows\Start Menu\Programs\Startup` | All users autostart | Machine startup |
| `shell:Programs` | Virtual | Opens user Programs folder |
| `shell:Common Programs` | Virtual | Opens common Programs folder |

**Test machine (2026-06-22):** 16 `.lnk` files under user Programs; common Programs folder returned empty in quick scan (vendor shortcuts may live under subfolders or only in `Get-StartApps`).

**Indexing strategy:**

```powershell
$roots = @(
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
  "$env:ProgramData\Microsoft\Windows\Start Menu\Programs"
)
$roots | ForEach-Object {
  Get-ChildItem $_ -Recurse -Filter *.lnk -ErrorAction SilentlyContinue
}
```

Build a map: `normalized_display_name → full_lnk_path`. Display name = `.lnk` basename without extension.

---

## 3. `run_command` / `cmd start` Patterns

Orynn's `ToolExecutor.run_command` and `bash` detect GUI launches via `_looks_like_gui_launch` and route them to `_launch_gui_command` (detached `subprocess.Popen`, auto `wait_for_window`).

### 3.1 Recognized GUI launch shapes (`_looks_like_gui_launch`)

```python
# tools.py — patterns that trigger detached GUI launch + optional wait
r'^(start\s+\S|explorer\s|cmd\s*/c\s+start|powershell(?:\.exe)?\s+-command\s+"?start(?:-process)?)'
r'^(notepad(?:\.exe)?|calc(?:\.exe)?|calculator:|mspaint(?:\.exe)?|paint(?:\.exe)?)(?:\s|$)'
```

### 3.2 Canonical `start` syntax

| Pattern | Example | Notes |
|---------|---------|-------|
| Bare alias | `start notepad` | Uses `PATHEXT` + App Paths registry |
| Quoted path | `start "" "C:\Program Files\App\app.exe"` | **First quoted arg is window title** (often empty `""`) |
| With args | `start "" "app.exe" --flag` | Args after path |
| URI | `start ms-settings:bluetooth` | ShellExecute via protocol handler |
| Via cmd | `cmd /c start notepad` | Equivalent; model often emits this |
| PowerShell | `powershell -command Start-Process calc` | Normalized for Calculator aliases |

### 3.3 Orynn launch pipeline

```
run_command("start notepad")
  → _looks_like_gui_launch? yes
  → _reuse_existing_window? (single-instance: Notepad, Calculator, Paint)
  → _normalize_gui_launch_command (calculator → calc)
  → subprocess.Popen(shell=True, DETACHED_PROCESS)
  → _auto_wait_after_launch
      → _guess_launch_target_title → "Notepad"
      → wait_for_window("Notepad", 10s)
      → set_isolated_hwnd + _remember_started_pid
```

`open_known_app` (voice fast-path) follows the same launch path but is invoked directly from `agent.py` when `detect_app_launch_intent(goal)` returns a match — **no LLM step**.

### 3.4 Title guessing (`_guess_launch_target_title`)

Maps launch target → window title for `wait_for_window`:

| Target | Wait title |
|--------|------------|
| `ms-settings:` | Settings |
| `ms-photos:` | Photos |
| `ms-clock:` | Clock |
| `calc` / `calculator:` | Calculator |
| `notepad` | Notepad |
| `mspaint` / `paint` | Paint |
| `https://...` | *(empty — no wait)* |
| Unknown scheme | *(empty — no wait)* |

Extend this map when adding URI launches to `_KNOWN_LAUNCH_APPS`.

---

## 4. Known Exe Paths & Install Roots

### 4.1 Windows built-ins (reliable)

| App | Run alias | `where.exe` (test machine) | Notes |
|-----|-----------|----------------------------|-------|
| Notepad | `notepad` | `C:\Windows\System32\notepad.exe`, `C:\Windows\notepad.exe` | Win32 |
| Calculator | `calc` | `C:\Windows\System32\calc.exe` | Win11 may also have UWP `Microsoft.WindowsCalculator_8wekyb3d8bbwe!App` |
| File Explorer | `explorer` | `C:\Windows\explorer.exe` | Also `explorer <path>` for folders |
| Task Manager | `taskmgr` | `C:\Windows\System32\Taskmgr.exe` | |
| Paint | `mspaint` | **Not on PATH** (test machine) | Win11: UWP `Microsoft.Paint_8wekyb3d8bbwe!App`; `start mspaint` still works via App Paths / redirect |
| CMD | `cmd` | `C:\Windows\System32\cmd.exe` | |
| PowerShell | `powershell` | `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` | |
| Windows Terminal | `wt` | **Not found** on test machine | Optional install from Store |
| Control Panel | `control` | Via `control.exe` in System32 | Opens CP home |
| WordPad | `wordpad` | Legacy; deprecated Win11 24H2+ | Orynn still lists it |

**Lesson:** `where.exe` is necessary but **not sufficient** — UWP apps and Store installs often have no PATH entry. `start <alias>` still works when App Paths registry or hash redirect exists.

### 4.2 Third-party install roots (discovery, not hard-code)

| Root | Exe count (test machine) | Typical apps |
|------|--------------------------|--------------|
| `C:\Program Files` | 1,453 | Native installers, Electron (Discord, Cursor…) |
| `C:\Program Files (x86)` | 1,726 | 32-bit, legacy |
| `%LocalAppData%\Programs` | 37 | Per-user installs (VS Code user setup, Rust…) |
| `%LocalAppData%\<vendor>\` | varies | `Discord\app-*\Discord.exe`, `Programs\cursor\Cursor.exe` |
| `%AppData%\..\Local\` | varies | Electron auto-update layouts |

**Anti-pattern:** Scanning all 3,000+ exes at launch time. **Pattern:** Index Start Menu `.lnk` + `Get-StartApps` once; use `resolve_app_exe` only for **running** process resolution (Electron unlock).

### 4.3 `resolve_app_exe` today

```python
# desktop_features.py — resolves name → full path of RUNNING app's exe
# 1. exact exe basename match in visible windows
# 2. app name substring in window title → that window's exe
# Returns input unchanged if no match
```

This is for **control/unlock**, not cold launch. Do not conflate with launch resolution.

---

## 5. Shortcut `.lnk` Resolution

### 5.1 WScript.Shell COM (recommended)

```powershell
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut("C:\Users\...\Cursor.lnk")
$s.TargetPath    # C:\Users\ACER\AppData\Local\Programs\cursor\Cursor.exe
$s.Arguments     # e.g. --force-renderer-accessibility
$s.WorkingDirectory
```

**Test machine example:**

| `.lnk` | Target |
|--------|--------|
| `4K Video Downloader+.lnk` | `C:\Program Files\4KDownload\4kvideodownloaderplus\4kvideodownloaderplus.exe` |

### 5.2 Launching `.lnk` files

```
start "" "C:\Users\ACER\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Cursor.lnk"
```

Prefer launching the `.lnk` (not only `TargetPath`) to preserve working directory and arguments.

### 5.3 Python equivalent

```python
import win32com.client
shell = win32com.client.Dispatch("WScript.Shell")
shortcut = shell.CreateShortcut(lnk_path)
target, args, cwd = shortcut.TargetPath, shortcut.Arguments, shortcut.WorkingDirectory
```

Or parse via `shell32` / `msilib` — COM is simplest on Windows.

---

## 6. Discovery APIs: `where.exe`, `Get-StartApps`, `winget list`

### 6.1 `where.exe`

```cmd
where notepad calc explorer taskmgr
```

| Pros | Cons |
|------|------|
| Fast, no elevation | Only PATH + App Paths registry |
| Good for CLI tools | Misses UWP, most Store apps |
| Scriptable | Multiple results possible (System32 + SysWOW64) |

Use for **validation** after picking an exe, not primary discovery.

### 6.2 `Get-StartApps` (PowerShell)

```powershell
Get-StartApps | Format-Table Name, AppID -AutoSize
```

**Test machine:** 121 entries — **71** with `!` (packaged AUMID), **28** with `\` (Win32 path-style AppID).

**Sample output:**

| Name | AppID |
|------|-------|
| Notepad | `Microsoft.WindowsNotepad_8wekyb3d8bbwe!App` |
| Calculator | `Microsoft.WindowsCalculator_8wekyb3d8bbwe!App` |
| Calculator | `Chrome._crx_joodakpmhfnpleo.UserData.Profile3` *(PWA duplicate)* |
| Paint | `Microsoft.Paint_8wekyb3d8bbwe!App` |
| Clock | `Microsoft.WindowsAlarms_8wekyb3d8bbwe!App` |
| Copilot | `Microsoft.Copilot_8wekyb3d8bbwe!App` |
| Character Map | `{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\charmap.exe` |

**Duplicate names:** `Calculator` (2), `4K Video Downloader+` (2). Resolver must rank: prefer `Microsoft.*!App` over PWA/Chrome CRX IDs; prefer `.lnk` user pin over ambiguous AUMID.

**Recommended index build (session start):**

```python
def build_launch_index() -> dict[str, LaunchEntry]:
    # 1. Get-StartApps → name.lower() → [{app_id, kind}]
    # 2. Start Menu .lnk → name.lower() → {lnk_path, target, args}
    # 3. Merge with precedence: curated _KNOWN_LAUNCH_APPS > .lnk > AUMID
    ...
```

### 6.3 `winget list`

```cmd
winget list --accept-source-agreements
```

| Pros | Cons |
|------|------|
| Package IDs (`Publisher.Package`) | **Not installed** on all machines (missing on test OEM image) |
| Version / source metadata | Slow; network for index update |
| Good for "is X installed?" | Does not give launch command directly |

Use as **supplementary inventory** for agent reasoning ("Spotify not in index — check winget"). Not a launch primitive.

### 6.4 Other discovery sources

| Source | Use |
|--------|-----|
| `Get-AppxPackage` | Installed UWP packages + `PackageFamilyName` |
| Registry `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths` | Exe aliases (`chrome.exe` → path) |
| Registry `HKCR\<protocol>\shell\open\command` | URI handler exe |
| `Get-ItemProperty HKLM:\...\Uninstall\*` | Add/Remove Programs inventory |

---

## 7. UWP / AppUserModelID (AUMID) Launching

### 7.1 What is an AUMID?

**Application User Model ID** — stable string identifying a Start-visible app. Format:

```
PackageFamilyName!ApplicationId
# e.g. Microsoft.WindowsCalculator_8wekyb3d8bbwe!App
```

Win32 apps may also appear with path-style IDs: `{GUID}\path\to\app.exe`.

### 7.2 Launch commands

```cmd
explorer shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App
```

```powershell
Start-Process "shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"
```

```python
import subprocess
aumid = r"Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
subprocess.Popen(f'explorer shell:AppsFolder\\{aumid}', shell=True)
```

**Browse all:** `explorer shell:AppsFolder` → Details view → group by AppUserModelID.

### 7.3 Packaged vs Win32 decision tree

```
App request "open X"
├─ In _KNOWN_LAUNCH_APPS? → start command (voice fast-path)
├─ Start Menu X.lnk exists? → start "" "path\X.lnk"
├─ Get-StartApps exact name match (single)? → explorer shell:AppsFolder\<AppID>
├─ Get-StartApps multiple matches? → rank (Microsoft.*!App > .exe path > PWA)
├─ Protocol registered? → start protocol: (spotify:, discord:)
├─ where.exe / App Paths? → start "" "full\path.exe"
└─ else → planner + Win+Search fallback OR tell user not installed
```

### 7.4 UWP launch + Orynn window verify

UWP apps run under `ApplicationFrameHost.exe` — window title is usually the **display name** ("Calculator", "Paint"), not the AUMID. Orynn's `wait_for_window("Calculator")` works after AUMID launch. Extend `_guess_launch_target_title` with an AUMID→title map when adding `launch_aumid`.

---

## 8. Common Built-ins & Control Panel Applets

### 8.1 Safe for `_KNOWN_LAUNCH_APPS` expansion

| Spoken name | Launch command | Window title | Single-instance? |
|-------------|----------------|--------------|------------------|
| notepad | `start notepad` | Notepad | Yes |
| calculator / calc | `start calc` | Calculator | Yes |
| paint / mspaint | `start mspaint` | Paint | Yes |
| settings | `start ms-settings:` | Settings | No |
| task manager | `start taskmgr` | Task Manager | No |
| wordpad | `start wordpad` | WordPad | Yes |
| file explorer | `start explorer` | File Explorer | No |
| command prompt | `start cmd` | *(cmd window)* | No |
| powershell | `start powershell` | Windows PowerShell | No |
| terminal | `start wt` | Windows Terminal | No |
| control panel | `start control` | Control Panel | No |
| snipping tool | `start ms-screenclip:` | Snipping Tool | No |
| photos | `start ms-photos:` | Photos | No |
| clock / alarms | `start ms-clock:` | Clock | No |
| bluetooth settings | `start ms-settings:bluetooth` | Settings | No |
| display settings | `start ms-settings:display` | Settings | No |
| sound settings | `start ms-settings:sound` | Settings | No |

### 8.2 Run dialog / MMC snap-ins (agent `run_command`, not voice fast-path)

| Command | Opens |
|---------|-------|
| `devmgmt.msc` | Device Manager |
| `compmgmt.msc` | Computer Management |
| `services.msc` | Services |
| `eventvwr` | Event Viewer |
| `diskmgmt.msc` | Disk Management |
| `ncpa.cpl` | Network Connections |
| `appwiz.cpl` | Programs and Features |
| `sysdm.cpl` | System Properties |
| `timedate.cpl` | Date and Time |
| `main.cpl` | Mouse Properties |
| `desk.cpl` | Display (legacy CP) |
| `firewall.cpl` | Windows Defender Firewall |
| `regedit` | Registry Editor |
| `msinfo32` | System Information |
| `winver` | About Windows |
| `optionalfeatures` | Windows Features |
| `cleanmgr` | Disk Cleanup |

### 8.3 Control Panel vs Settings

Win11 steers users to **Settings** (`ms-settings:`). Classic CPL applets still work and open separate windows — useful when UIA inside Settings is slow. Prefer `ms-settings:` for voice ("open Bluetooth settings") and `.cpl` when the agent needs a specific legacy dialog.

---

## 9. Orynn Implementation — Current State

### 9.1 `_KNOWN_LAUNCH_APPS` (curated registry)

```python
# app/tools.py — deliberately NARROW (7 apps, 9 aliases)
_KNOWN_LAUNCH_APPS: Dict[str, tuple] = {
    "notepad": ("start notepad", "Notepad"),
    "calculator": ("start calc", "Calculator"),
    "calc": ("start calc", "Calculator"),
    "paint": ("start mspaint", "Paint"),
    "ms paint": ("start mspaint", "Paint"),
    "mspaint": ("start mspaint", "Paint"),
    "wordpad": ("start wordpad", "WordPad"),
    "settings": ("start ms-settings:", "Settings"),
    "task manager": ("start taskmgr", "Task Manager"),
}
```

**Design intent (from code comments):** Only Windows built-ins with stable `start` commands **and** matchable window titles. Browsers and third-party apps **intentionally excluded** — "open chrome" returns `None` and falls to the planner.

### 9.2 `detect_app_launch_intent(goal)`

```python
# Returns (launch_command, window_title) or None
# 1. Normalize whitespace / lowercase / strip punctuation
# 2. Match _LAUNCH_VERB_RE: open|launch|start|run|bring up|switch to|show me...
# 3. Reject if _LAUNCH_EXTRA_RE: and|then|after|also|to|with|... (multi-step)
# 4. Strip filler: the|my|app|application|please|...
# 5. Exact lookup in _KNOWN_LAUNCH_APPS
```

**Tests** (`tests/test_voice_and_env.py`):

| Utterance | Result |
|-----------|--------|
| `open notepad` | `("start notepad", "Notepad")` |
| `launch the calculator` | `("start calc", "Calculator")` |
| `hey orynn, open notepad` | fast-path match |
| `open notepad and type hello` | `None` (planner) |
| `open chrome` | `None` |
| `open notepad to write a note` | `None` (`to` triggers extra-step regex) |

### 9.3 Agent integration

```python
# agent.py — before LLM loop
_launch = detect_app_launch_intent(goal)
if _launch:
    _cmd, _title = _launch
    # → open_known_app(_cmd, _title)
```

Voice overlay (`textbox_overlay.py`) uses the same detector to skip `start_desktop_task` for pure launches.

### 9.4 Single-instance reuse

```python
_SINGLE_INSTANCE_APPS = {"Notepad", "Calculator", "Paint"}
# _reuse_existing_window → focus instead of duplicate launch
```

---

## 10. Recommendations — Extending Launch at Scale

### 10.1 Keep two lanes

| Lane | Mechanism | Apps |
|------|-----------|------|
| **Voice fast-path** | `detect_app_launch_intent` + `open_known_app` | ~20–30 OS built-ins with proven titles |
| **Universal resolver** | New `resolve_launch_target(name)` tool | Hundreds via index |

Do **not** bloat `_KNOWN_LAUNCH_APPS` with Discord, Chrome, or Cursor — titles and paths vary. **Do** add safe OS entries: `explorer`, `cmd`, `powershell`, `wt`, `control`, and top `ms-settings:` deep links.

### 10.2 Proposed `_KNOWN_LAUNCH_APPS` additions (immediate)

```python
# Add to _KNOWN_LAUNCH_APPS — all verified via start + wait_for_window
"file explorer": ("start explorer", "File Explorer"),
"explorer": ("start explorer", "File Explorer"),
"command prompt": ("start cmd", "Command Prompt"),
"cmd": ("start cmd", "Command Prompt"),
"powershell": ("start powershell", "Windows PowerShell"),
"terminal": ("start wt", "Windows Terminal"),
"windows terminal": ("start wt", "Windows Terminal"),
"control panel": ("start control", "Control Panel"),
"snipping tool": ("start ms-screenclip:", "Snipping Tool"),
"snip": ("start ms-screenclip:", "Snipping Tool"),
"photos": ("start ms-photos:", "Photos"),
"clock": ("start ms-clock:", "Clock"),
"alarms": ("start ms-clock:", "Clock"),
"bluetooth": ("start ms-settings:bluetooth", "Settings"),
"bluetooth settings": ("start ms-settings:bluetooth", "Settings"),
"display": ("start ms-settings:display", "Settings"),
"display settings": ("start ms-settings:display", "Settings"),
"sound": ("start ms-settings:sound", "Settings"),
"sound settings": ("start ms-settings:sound", "Settings"),
"wifi": ("start ms-settings:network-wifi", "Settings"),
"wi-fi": ("start ms-settings:network-wifi", "Settings"),
"network settings": ("start ms-settings:network", "Settings"),
```

Also extend `_SINGLE_INSTANCE_APPS` only for true single-instance apps — **not** Settings (multiple pages can coexist).

### 10.3 New tool: `launch_app(name)` (medium term)

```python
def launch_app(self, name: str) -> ToolResult:
  # 1. detect_app_launch_intent fallback
  # 2. self._launch_index[name_lower] from session cache
  # 3. launch via start / explorer shell:AppsFolder / .lnk
  # 4. wait_for_window(expected_title)
```

Build `_launch_index` at session start:

```python
def _refresh_launch_index(self):
    # Get-StartApps (subprocess powershell -NoProfile -Command ...)
    # + enumerate Start Menu .lnk + WScript.Shell resolve
    # + load curated overrides
```

### 10.4 New tool: `launch_aumid(aumid)` (medium term)

```python
subprocess.Popen(f'explorer shell:AppsFolder\\{aumid}', shell=True, ...)
```

Expose `list_start_apps` read-only for agent debugging.

### 10.5 `detect_app_launch_intent` extensions

| Change | Rationale |
|--------|-----------|
| Add optional fuzzy match against `_launch_index` keys | "open disord" → Discord.lnk |
| Keep **reject** on `_LAUNCH_EXTRA_RE` | Preserve multi-step handoff |
| Add `open settings bluetooth` as compound? | **No** — use planner or dedicated ms-settings aliases |
| Strip trailing "app" / "for me" (already partial) | Continue |

### 10.6 Verification contract (unchanged — enforce everywhere)

Never report success without `wait_for_window` or `open_known_app` verification. `DESKTOP_HARDENING` already requires this; AUMID and `.lnk` launches must use the same contract.

### 10.7 Anti-patterns

| Anti-pattern | Why |
|--------------|-----|
| Guessing `start spotify:` without registry check | "No app to open this link" dialog |
| Hard-coding `C:\Program Files\...` for Electron apps | Auto-update changes folder |
| Win+Search as tier-1 | Fragile, slow, ambiguous |
| Adding Chrome/Firefox to voice registry | Default browser + path varies |
| `where.exe` as sole resolver | Misses UWP and per-user installs |

---

## 11. Scalable Architecture Diagram

```
                    USER: "open <app>"
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
   detect_app_launch_intent          start_desktop_task
   (pure + known registry)           (planner / multi-step)
            │                               │
            ▼                               ▼
     open_known_app                   resolve_launch_target
            │                         (Get-StartApps + .lnk index)
            │                               │
            └───────────────┬───────────────┘
                            ▼
              ┌─────────────────────────────┐
              │  Launch primitive           │
              │  start / explorer / AUMID   │
              └─────────────┬───────────────┘
                            ▼
              ┌─────────────────────────────┐
              │  wait_for_window(title)     │
              │  focus / set_isolated_hwnd  │
              └─────────────┬───────────────┘
                            ▼
                     UIA control plane
```

---

## 12. Sources

| Topic | URL |
|-------|-----|
| Find AUMID (`Get-StartApps`) | https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid |
| Launch default app for URI | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-default-app |
| Launch Windows Settings (`ms-settings`) | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings |
| KNOWNFOLDERID / shell folders | https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid |
| `start` command | https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/start |
| Shortcut object (WScript.Shell) | https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/windows-scripting/fdfdimyh(v=vs.84) |

---

*Verified behaviors vary by Windows 11 build, SKU, and installed software. Re-run `Get-StartApps` and Start Menu enumeration on target hardware before shipping a launch index.*
