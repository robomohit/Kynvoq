# Windows Desktop Automation Research for Orynn

**Date:** 2026-06-22  
**Scope:** Practical automation methods for a voice-native Windows companion (Gemini Live front desk + UIA-first back-office agent).  
**Codebase reviewed:** `app/tools.py`, `app/widget/desktop_features.py`, `app/connectors.py`, `app/grid_locate.py`, `app/agent.py`, `app/adaptive_windows.py`

---

## Executive Summary

Orynn is already architected correctly for scalable Windows automation: **UIA by control name first**, **deterministic launch shortcuts second**, **local OCR third**, **vision grid-locate last**. The Live orchestrator should stay on the fast path (open app, focus window, UIA click/type); the back-office agent owns the full resolver ladder and lazy playbooks.

**UI Automation (UIA)** is the right default for hundreds of apps because it is semantic (names, roles, patterns), screenshot-free, and fast when used correctly. Its limits are well understood: Chromium/Electron apps hide their DOM until accessibility is activated; canvas/game/custom-rendered surfaces expose sparse trees; cross-process property reads are expensive without caching. Orynn mitigates Electron via `electron_unlock` (`--force-renderer-accessibility`) and mitigates misses via Windows Media OCR and two-stage grid-locate.

**Windows-native shortcuts** (`ms-settings:`, `shell:`, AUMID launches, protocol URIs, Run dialog) are the highest-ROI “universal open layer.” They bypass fragile UI navigation entirely. Orynn already uses `start ms-settings:` in its voice launch registry but has not yet generalized to AUMID/protocol/shell launches or a broader settings URI catalog.

**Alternative methods** each have a niche: SendInput/pyautogui for keystrokes into Chromium renderers; COM for Office deep automation; WMI/CIM/PowerShell for system state; browser automation (Playwright/CDP) for web surfaces; FlaUI/AutoHotkey when you need a dedicated Windows automation runtime. Vision/OCR should remain fallbacks, not the primary control plane.

**Scaling to hundreds of apps** does not mean writing hundreds of playbooks upfront. The winning pattern is:

1. **Universal open layer** — launch/focus by exe, AUMID, URI, or `start` command.
2. **Observe once** — `adaptive_observe` / control menu from UIA survey.
3. **Act by name** — `uia_find`, `uia_click`, `uia_type`, `uia_click_sequence`, keyboard shortcuts.
4. **Lazy playbooks** — `adaptive_windows_profiles.json` records which resolver worked per app (`ocr_text_target`, `vision_grid_locate`, etc.).
5. **Escalate only on classified failure** — Electron locked → unlock; sparse tree → OCR; custom surface → grid-locate.

**When NOT to use UIA:** games and GPU-rendered UIs, password fields in some browsers, apps with intentionally minimal a11y trees, system overlays (watermarks), and tasks better served by APIs (Settings URIs, WMI, COM, HTTP). Live should never block on grid-locate or multi-step vision recovery.

**Top gaps in Orynn today:** narrow voice launch registry (7 built-ins), no AUMID/protocol launcher tool, no UIA cache/batch layer in Python, Electron relaunch does not kill existing instance, no COM automation path for Office, browser connectors still default to slow `computer_use` instead of Playwright where possible, and no systematic app-class routing table exposed to the agent prompt.

---

## Method Comparison

| Method | Speed | Cost | Reliability | Best for |
|--------|-------|------|-------------|----------|
| **UIA (control name)** | Fast (ms–low s per action) | Free (local) | High on Win32, WinUI, Office, Settings | Buttons, fields, menus, dialogs |
| **Keyboard / SendInput** | Very fast | Free | High when shortcuts exist | Save, copy, tab-nav, Electron typing |
| **ms-settings / shell: / AUMID / URI launch** | Instant | Free | Very high (OS-routed) | Open Settings pages, apps, folders |
| **Windows Media OCR** | Medium (100–500 ms/region) | Free (local) | Medium (visible text only) | Labels UIA omits, File Explorer, legacy UI |
| **Vision grid-locate** | Slow (2+ model calls) | API $ | Medium (fails safe) | Canvas, games, icon-only toolbars |
| **Screenshot + coordinate click** | Medium | Free + vision if used | Low–medium | Last resort |
| **pyautogui / PostMessage** | Fast | Free | Low for Chromium content | Simple Win32; avoid for Electron content |
| **COM (Office)** | Fast | Free | Very high in Office | Spreadsheets, docs, slides programmatically |
| **WMI / CIM / PowerShell** | Medium | Free | High for system facts | Installed software, services, disks, NICs |
| **Browser automation (CDP/Playwright)** | Medium | Free–low | High for web apps | Gmail, GitHub, SaaS connectors |
| **FlaUI / pywinauto / AutoHotkey** | Fast | Free | Same as UIA (wrappers) | Alternative runtimes, hotkey macros |
| **Accessibility event “unlock”** | One-time delay | Free | High for Electron | Force Chromium tree without relaunch |

---

## 1. UI Automation (UIA)

### How it works

Microsoft UI Automation exposes every HWND’s control tree via COM (`IUIAutomation`). Each element has properties (Name, AutomationId, ControlType, BoundingRectangle) and patterns (Invoke, Value, Selection, Scroll). Clients walk the tree or use `FindFirst`/`FindAll` with conditions.

Orynn uses the **`uiautomation`** Python package (Yinkang Liu), which wraps the same COM API as FlaUI/pywinauto’s UIA backend.

**Official references:**
- [Windows Automation API: UI Automation](https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32)
- [Caching UI Automation properties](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients)
- [Use caching in UI Automation (.NET)](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/use-caching-in-ui-automation)

### Strengths

- Semantic targeting — click `"Save"` not `(412, 288)`.
- Works headlessly from the agent’s perspective (no screenshots).
- Excellent on **Win32 common controls**, **WinUI 3 / UWP** (when providers exist), **WPF**, **WinForms**, and **Microsoft Office**.
- Supports verification (`uia_find` read Value/Name after action).

### Limits

- **Cross-process calls are slow** if you read properties one-by-one; use cache requests / batch walks.
- **Electron/Chromium** exposes only title-bar controls until accessibility bridge activates (~3–9 elements vs thousands).
- **Custom-drawn** controls (Skia, DirectX, game engines) may expose a single `Pane` or nothing.
- **Virtualized lists** (RecyclerView-style) only materialize visible rows.
- **Security-sensitive fields** may be marked offscreen or password-protected.
- **Multiple windows** with similar titles require app-hint disambiguation (Orynn’s `_uia_root` + exe matching).

### Electron / WinUI / Office notes

| Stack | UIA quality | Notes |
|-------|-------------|-------|
| Win32 | Good | Default providers on standard controls |
| WPF / WinForms | Excellent | Server-side providers |
| WinUI 3 / UWP | Good–excellent | Native XAML a11y |
| Office desktop | Excellent | Deep tree; COM often better for bulk |
| Electron/Chromium | Poor until unlocked | Needs `--force-renderer-accessibility` or UIA event subscription |
| Settings (Win11) | Good | Orynn already surveys nav items |

### Speed best practices

1. **Search-first** — `FindFirst(BuildCache)` with Name/AutomationId condition; don’t walk entire tree.
2. **Batch properties** — configure `CacheRequest` with only needed properties/patterns; set `AutomationElementMode.None` when you don’t need live references ([MS docs](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationcacherequest)).
3. **Scope narrowly** — `TreeScope.Descendants` from app root, not desktop root.
4. **Prefer keyboard** — `Ctrl+S`, `Alt+F4`, `Tab` beats hunting OK buttons.
5. **Cap walks** — Orynn’s `cap=90` in `survey_app_controls` is correct; stop early.
6. **Cache observations** — Orynn caches `uia_find` (2s) and `adaptive_observe` (4s); extend with event-driven invalidation.
7. **Sequence clicks** — `uia_click_sequence` amortizes focus/find overhead.

### Python library patterns

| Library | Role |
|---------|------|
| **uiautomation** | Orynn’s choice; lightweight, good for find/click |
| **pywinauto** | Higher-level; `backend="uia"`; good for dialogs |
| **comtypes + UIAutomationClient** | Maximum control; verbose |
| **FlaUI** (.NET) | Best perf/features if you add a C# sidecar |
| **PowerShell UIAutomation** | Quick probes: `Get-UIAElement` community modules |

**pywinauto pattern:**
```python
from pywinauto import Application
app = Application(backend="uia").connect(title_re=".*Notepad.*")
dlg = app.window(title_re=".*Notepad.*")
dlg.child_window(title="Text editor", control_type="Edit").set_text("hello")
```

**comtypes pattern:** instantiate `IUIAutomation`, `CreateCacheRequest`, `AddProperty(UIA_NamePropertyId)`, `FindFirstBuildCache`.

---

## 2. Special Windows Mechanisms

These are the **universal open layer** — prefer them over clicking through Settings or Start.

### 2.1 ms-settings: URIs

Launch via: `start ms-settings:display` or `ShellExecute("open", "ms-settings:bluetooth", ...)`.

**Official full reference:** [Launch Windows Settings](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings)

#### Curated common URIs (30)

| Page | URI |
|------|-----|
| Settings home | `ms-settings:` |
| System | `ms-settings:system` |
| Display | `ms-settings:display` |
| Night light | `ms-settings:nightlight` |
| Sound | `ms-settings:sound` |
| Notifications | `ms-settings:notifications` |
| Focus assist | `ms-settings:quiethours` |
| Power & sleep | `ms-settings:powersleep` |
| Storage | `ms-settings:storagesense` |
| Clipboard | `ms-settings:clipboard` |
| Bluetooth | `ms-settings:bluetooth` |
| Printers | `ms-settings:printers` |
| Wi-Fi | `ms-settings:network-wifi` |
| Ethernet | `ms-settings:network-ethernet` |
| VPN | `ms-settings:network-vpn` |
| Mobile hotspot | `ms-settings:network-mobilehotspot` |
| Apps & features | `ms-settings:appsfeatures` |
| Default apps | `ms-settings:defaultapps` |
| Startup apps | `ms-settings:startupapps` |
| Optional features | `ms-settings:optionalfeatures` |
| Personalization | `ms-settings:personalization` |
| Taskbar | `ms-settings:taskbar` |
| Themes | `ms-settings:themes` |
| Fonts | `ms-settings:fonts` |
| Privacy | `ms-settings:privacy` |
| Location | `ms-settings:privacy-location` |
| Microphone | `ms-settings:privacy-microphone` |
| Camera | `ms-settings:privacy-webcam` |
| Windows Update | `ms-settings:windowsupdate` |
| Sign-in options | `ms-settings:signinoptions` |
| Date & time | `ms-settings:dateandtime` |
| Region & language | `ms-settings:regionlanguage` |

**Default app deep link (Win11 22H2+):**  
`ms-settings:defaultapps?registeredAUMID=<escaped-aumid>`

### 2.2 shell: folders

Type in Run (`Win+R`) or Explorer address bar: `shell:<name>`.

#### Curated shell paths

| Command | Opens |
|---------|-------|
| `shell:AppsFolder` | All installed apps (virtual) |
| `shell:Desktop` | User desktop folder |
| `shell:Downloads` | Downloads |
| `shell:Personal` | Documents |
| `shell:My Pictures` | Pictures |
| `shell:AppData` | `%AppData%` (Roaming) |
| `shell:Local AppData` | `%LocalAppData%` |
| `shell:ProgramFiles` | Program Files |
| `shell:ProgramFilesX86` | Program Files (x86) |
| `shell:Common AppData` | ProgramData |
| `shell:Startup` | User startup folder |
| `shell:Common Startup` | All-users startup |
| `shell:Programs` | Start Menu programs |
| `shell:Administrative Tools` | Windows Tools |
| `shell:ControlPanelFolder` | Control Panel |
| `shell:ConnectionsFolder` | Network Connections |
| `shell:PrintersFolder` | Printers |
| `shell:RecycleBinFolder` | Recycle Bin |
| `shell:Recent` | Recent files |
| `shell:SendTo` | Send To menu |
| `shell:Fonts` | Fonts |
| `shell:Profile` | User profile folder |
| `shell:::{4234d49b-0245-4df3-b780-3893943456e1}` | Applications (by GUID) |

**Discover more:**  
`Get-ChildItem HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderDescriptions | % { (Get-ItemProperty $_.PSPath).Name }`

**Reference:** [KNOWNFOLDERID](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)

### 2.3 Protocol handlers (URI schemes)

Registered under `HKEY_CLASSES_ROOT\<scheme>` with `URL Protocol` value.

| Scheme | Typical use |
|--------|-------------|
| `ms-settings:` | Windows Settings |
| `ms-windows-store:` | Microsoft Store (`ms-windows-store://home/`) |
| `microsoft-edge:` | Edge (`microsoft-edge:https://example.com/`) |
| `ms-calculator:` | Calculator |
| `ms-photos:` | Photos |
| `ms-screenclip:` | Snipping Tool |
| `ms-clock:` | Clock / alarms |
| `ms-teams:` | Microsoft Teams |
| `spotify:` | Spotify desktop |
| `steam:` / `steam://` | Steam |
| `slack:` | Slack |
| `discord:` | Discord |
| `zoommtg:` | Zoom |
| `mailto:` | Default mail client |
| `tel:` | Phone dialer |

Launch: `start spotify:` or `explorer shell:AppsFolder\<AUMID>`.

**Reference:** [Launch the default app for a URI](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-default-app)

### 2.4 Run dialog & Win+Search

| Command | Action |
|---------|--------|
| `notepad` | Notepad |
| `calc` | Calculator |
| `mspaint` | Paint |
| `taskmgr` | Task Manager |
| `control` | Control Panel |
| `devmgmt.msc` | Device Manager |
| `compmgmt.msc` | Computer Management |
| `services.msc` | Services |
| `eventvwr` | Event Viewer |
| `powershell` | PowerShell |
| `wt` | Windows Terminal |
| `cmd` | Command Prompt |
| `explorer` | File Explorer |
| `winver` | About Windows |
| `optionalfeatures` | Windows Features |
| `msinfo32` | System Information |
| `regedit` | Registry Editor |

**Win+Search:** types into Windows Search; automating it is fragile (UI changes per build). Prefer direct launch commands.

### 2.5 AppUserModelID (AUMID)

- **Find:** `Get-StartApps` in PowerShell ([MS docs](https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid))
- **Launch:** `explorer shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App`
- **Browse:** `shell:AppsFolder` → Details → group by AppUserModelId

**Packaged (UWP/Store) vs Win32:**

| Type | Launch | AUMID | UIA |
|------|--------|-------|-----|
| Win32 `.exe` | Path, `start`, shortcut | Optional (pinned) | Good |
| MSIX/UWP | AUMID, Store | Required | Good |
| Electron | `.exe` + flags | Sometimes | Poor until unlocked |
| Portable | Path only | None | Varies |

### 2.6 Shortcuts (.lnk)

- Resolve target: PowerShell `(New-Object -ComObject WScript.Shell).CreateShortcut('path.lnk').TargetPath`
- Launch: `start "" "path.lnk"` — inherits cwd, args, icon.
- Start Menu paths: `%AppData%\Microsoft\Windows\Start Menu\Programs`

---

## 3. Alternative Automation Methods

### 3.1 OCR — Windows Media OCR

Built into Windows 10+ (`Windows.Media.Ocr`). No Tesseract required.

**Orynn implementation:** `desktop_features.win_ocr_words` / `ocr_find_in_app` via `winsdk.windows.media.ocr`.

**Strengths:** Fast, local, good for visible labels.  
**Limits:** No semantic structure; fails on icons-only UI; needs language pack installed.

### 3.2 Vision / grid-locate

**Orynn:** `grid_locate.py` — 12×8 coarse grid → 6×6 fine zoom; Gemini vision picks cell; fails safe on cell 0.

Use only in back-office agent with `allow_pixel_fallback=True`. Live must not use this path.

### 3.3 pyautogui / SendInput

- **SendInput** (used by pyautogui) injects at the OS input queue — **works with Chromium** when focused.
- **PostMessage** to HWND does **not** reach Electron renderers reliably.
- Orynn uses pyautogui for OCR/grid click fallbacks and `keyboard_type`/`key_combo`.

### 3.4 Win32 API

Orynn already uses: `EnumWindows`, `GetWindowText`, `SetForegroundWindow`, `DwmGetWindowAttribute` (cloaked), `IsHungAppWindow`, `QueryFullProcessImageNameW`.

Useful additions: `SendInput` wrapper, `RegisterHotKey` for emergency stop, `UIAccess` only if absolutely needed.

### 3.5 Accessibility hooks / “clients listening”

Chromium checks `UiaClientsAreListening()` before building full tree. Subscribing to `FocusChanged` or launching with `--force-renderer-accessibility` forces tree materialization ([Chromium accessibility overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md)).

### 3.6 PowerShell UIAutomation

Quick inspection without Python deploy:
```powershell
# Requires UIA module / script — useful for debugging
Get-Process notepad | ForEach-Object { $_.MainWindowTitle }
```

For production, stay in Orynn’s Python stack.

### 3.7 FlaUI / AutoHotkey

- **FlaUI:** .NET UIA wrapper; faster cache story; consider if Python UIA becomes bottleneck.
- **AutoHotkey v2:** Excellent for user macros and hotkey chords; poor fit for LLM agent loop unless funneled through a single REST/stdio tool.

### 3.8 Browser automation

For connectors (Gmail, GitHub, Slack web): **Playwright/CDP** beats screenshot `computer_use` on cost, speed, and reliability. Orynn has `BackgroundBrowser` but connectors still declare `default_mode: computer_use`.

### 3.9 COM automation (Office)

```python
import win32com.client
excel = win32com.client.Dispatch("Excel.Application")
excel.Visible = True
wb = excel.Workbooks.Open(r"C:\path\book.xlsx")
```

Best for bulk cell writes, charts, exports — complement UIA for one-off UI tasks.

### 3.10 WMI / CIM

```powershell
Get-CimInstance Win32_OperatingSystem
Get-CimInstance Win32_LogicalDisk
Get-Package | Where-Object Name -like '*Python*'
```

Use for **read-only system state** — not for clicking UI.

---

## 4. App Classification — What Works Per Class

| Class | Examples | Primary | Secondary | Avoid |
|-------|----------|---------|-----------|-------|
| **Native Win32** | Notepad, calc, mmc | UIA + keyboard | OCR | Vision |
| **WPF / WinForms** | Visual Studio (WPF parts), legacy tools | UIA | COM | — |
| **WinUI 3 / UWP** | Settings, Calculator, Photos | UIA + AUMID launch | ms-settings URIs | Pixel |
| **Office** | Word, Excel, PPT | COM + UIA | keyboard | Grid-locate |
| **Electron** | VS Code, Discord, Slack, Spotify, Teams, Figma desktop | Unlock + UIA | SendInput keyboard | UIA before unlock |
| **Chromium browser** | Chrome, Edge | CDP/Playwright | SendInput | UIA (sparse) |
| **Games / GPU** | Steam games, Unity | Vision/input macros | OCR HUD text | UIA |
| **Custom canvas** | Figma canvas, CAD | Grid-locate / CDP | OCR | UIA |
| **Web SaaS** | Gmail, Notion | Browser automation | — | Desktop UIA |

---

## 5. What Orynn Already Has

### Implemented

| Area | Location | Notes |
|------|----------|-------|
| UIA find/click/type/wait/sequence | `tools.py` | Core control plane |
| Control survey / menu | `desktop_features.survey_app_controls` | Fed to agent after focus |
| Adaptive observe | `tools.adaptive_observe` | Runtime classification + recovery plan |
| Lazy playbooks | `adaptive_windows.py` + `adaptive_windows_profiles.json` | Per-app resolver memory |
| Electron detect/unlock | `electron_check`, `electron_unlock`, `relaunch_with_accessibility` | `--force-renderer-accessibility` |
| OCR fallback | `ocr_find_in_app`, `_ocr_click_fallback` | Windows Media OCR |
| Grid-locate fallback | `grid_locate.py`, `_grid_locate_click` | Vision SoM; agent-only |
| Voice launch fast-path | `_KNOWN_LAUNCH_APPS` (7 apps) | Notepad, calc, paint, settings… |
| Window focus/resolve | `desktop_features` | HWND, exe, title scoring |
| Connectors registry | `connectors.py` | Web + Office + VS Code templates |
| Agent prompts | `agent.py` | Strong UIA-first protocol, Electron guidance |
| Hybrid resolver ladder | `tools.py` | UIA → OCR → grid-locate |
| Caching | `_uia_find_cache`, `_adaptive_observe_cache` | Short TTL |

### Gaps

| Gap | Impact | Suggested fix |
|-----|--------|---------------|
| Narrow launch registry | Voice can’t open most apps deterministically | `open_uri`, `open_aumid`, expand registry |
| No ms-settings catalog in tools | Agent navigates Settings manually | `open_settings(page)` tool |
| Electron relaunch doesn’t close old instance | Unlock appears to fail | `taskkill` + relaunch with user approval |
| No UIA cache/batch in Python | Slow on large trees | CacheRequest wrapper |
| No COM Office path | Excel/Word tasks slower | `office_com` tool for connectors |
| Connectors use screenshot browser mode | Cost + fragility | Playwright for `auth_kind: browser` |
| No Chromium FocusChanged unlock | Relaunch disruption | Subscribe once at agent start |
| Win+Search not wrapped | Low priority | Skip — too fragile |
| FlaUI / pywinauto unused | — | Stay on uiautomation unless perf issues |
| Live vs agent fallback split | Documented in grid_locate | Enforce in Live tool policy |

---

## 6. Scalable Strategy

### Universal open layer (implement first)

```
Intent → classify
  ├─ settings page?     → start ms-settings:<uri>
  ├─ known protocol?    → start <protocol>:
  ├─ Store/UWP app?     → explorer shell:AppsFolder\<AUMID>
  ├─ known Win32?       → start <exe> / shortcut path
  ├─ file/document?     → start "" "path"
  └─ else               → Win+Search / planner (slow)
```

### Lazy playbooks (already started)

`adaptive_windows_profiles.json` stores winning `resolver_id` per app:

- `ocr_text_target` — Notepad Find, File Explorer address bar
- `vision_grid_locate` — custom surfaces

**Policy:** on `uia_no_match`, consult profile → try learned resolver before generic ladder.

### Resolver ladder (back-office agent)

```
1. focus_window(app)
2. adaptive_observe / control menu
3. uia_find → uia_click / uia_type
4. keyboard shortcut path
5. electron_unlock (if electron_locked)
6. OCR click (local)
7. grid_locate (vision, allow_pixel_fallback=True)
8. finish honestly with evidence
```

### When NOT to use UIA

- **Opening apps/settings** — use URI/AUMID/shell.
- **Reading system state** — WMI/CIM/PowerShell.
- **Bulk Office manipulation** — COM.
- **Web apps** — browser automation.
- **Electron before unlock** — keyboard or unlock first.
- **Games / GPU-only UI** — vision or don’t automate.
- **Live voice path** — never grid-locate; cap at UIA + OCR or defer to back-office.

### Live orchestrator vs UIA agent split

| Concern | Gemini Live (front desk) | Back-office agent |
|---------|---------------------------|-------------------|
| Open app | `open_known_app`, voice registry | `run_command start` |
| Simple click | `uia_click` UIA-only | Full ladder |
| Typing | `uia_type` / `keyboard_type` | Same + fallbacks |
| Failure | Hand off task JSON | `adaptive_observe`, unlock, OCR, grid |
| Settings | `start ms-settings:*` | Can navigate inside Settings via UIA |
| Evidence | Window title + control name | `uia_find` read_result verification |

---

## 7. Electron Apps — List & Unlock Strategies

### Common Electron apps

| App | Exe (typical) | Unlock |
|-----|---------------|--------|
| VS Code | `Code.exe` | `--force-renderer-accessibility` |
| Discord | `Discord.exe` | same |
| Slack | `slack.exe` | same |
| Spotify | `Spotify.exe` | same |
| Teams (new) | `ms-teams.exe` | same / `msteams:` URI |
| Figma desktop | `Figma.exe` | same; canvas may still need vision |
| Notion desktop | `Notion.exe` | same |
| Cursor | `Cursor.exe` | same (Orynn blocks agent from driving Cursor) |
| Obsidian | `Obsidian.exe` | same |
| Postman | `Postman.exe` | same |
| GitHub Desktop | `GitHubDesktop.exe` | same |
| WhatsApp desktop | `WhatsApp.exe` | same |
| 1Password | `1Password.exe` | same |
| Linear desktop | `Linear.exe` | same |

### Unlock strategies (ordered)

1. **Check tree richness** — Orynn `count_app_controls >= 40` → skip relaunch.
2. **Relaunch with flag** — `electron_unlock` adds `--force-renderer-accessibility`.
3. **Kill + relaunch** — needed when single-instance lock blocks new process (gap today).
4. **UIA event subscription** — subscribe `FocusChanged` at session start to wake Chromium bridge without relaunch ([Chromium inspect docs](https://chromium.googlesource.com/chromium/src/+/HEAD/tools/accessibility/inspect/README.md)).
5. **CDP** — `electron_unlock(..., also_remote_debug=True)` port 9222 for power users.
6. **Keyboard fallback** — `SendInput` typing when tree partially available.
7. **Web URI** — `spotify:`, `discord:` handlers open app to deep link without UI automation.

**Chromium flag reference:** `--force-renderer-accessibility`  
**Detect Electron:** Orynn `is_electron_app()` checks for `resources/electron.asar` or `electron.exe` adjacent.

---

## 8. Recommendations for Orynn Architecture

### Immediate (high ROI, small diff)

1. **Expand `_KNOWN_LAUNCH_APPS`** with ~20 safe entries: `wt`, `powershell`, `explorer`, `ms-settings:display`, `ms-settings:bluetooth`, `ms-settings:sound`, `ms-clock:`, `ms-photos:`, etc.
2. **Add `open_settings(uri_suffix)` tool** — wraps `start ms-settings:{suffix}`.
3. **Add `launch_aumid(aumid)` tool** — `explorer shell:AppsFolder\{aumid}` with `Get-StartApps` helper.
4. **Wire learned playbooks into resolver** — read `adaptive_windows_profiles.json` before OCR/grid.
5. **Electron kill-and-relaunch** — optional `force=true` on `electron_unlock` after user approval.

### Medium term

6. **UIA cache wrapper** — batch Name/ControlType/BoundingRectangle in one walk.
7. **Session-wide Chromium wake** — register minimal `FocusChanged` handler when desktop control enabled.
8. **Playwright connector driver** — replace `computer_use` for `auth_kind: browser` connectors.
9. **COM shim for Excel/Word/PPT** — cell range read/write behind connector templates.
10. **App-class routing table in agent prompt** — auto-inject Electron/Office/web hints from exe sniff.

### Live-specific

11. **Hard gate:** Live tools = `{open_known_app, focus_window, uia_click, uia_type, keyboard_type, run_command start}` — no `allow_pixel_fallback`.
12. **Handoff envelope** — when Live detects sparse tree or multi-step workflow, queue `tasks/*.json` for back-office agent with `target_app`, `electron_hint`, `failure_class`.
13. **Spoken settings** — map “turn on Bluetooth” → `start ms-settings:bluetooth` not UIA navigation.

### Observability

14. **Log resolver path** — `control_layer` already in overlay payloads; aggregate in `logs/run_desktop_live.log`.
15. **Benchmark table** — extend `docs/BENCHMARKS.md` with open/click/locate timings per app class.

---

## 9. Sources & Links

| Topic | URL |
|-------|-----|
| Launch Windows Settings (ms-settings) | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings |
| Default apps settings deep link | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-default-apps-settings |
| URI scheme handlers | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-default-app |
| Find AUMID | https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid |
| KNOWNFOLDERID / shell folders | https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid |
| UI Automation overview | https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32 |
| UIA caching (perf) | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients |
| Chromium accessibility | https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md |
| Chromium inspect / force a11y | https://chromium.googlesource.com/chromium/src/+/HEAD/tools/accessibility/inspect/README.md |
| URI handler registry survey | https://github.com/amartinsec/MS-URI-Handlers |
| Windows OCR (WinRT) | https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr |

---

## Appendix A — Orynn tool inventory (desktop)

| Tool | Purpose |
|------|---------|
| `adaptive_observe` | Classify surface + list controls |
| `uia_find` | Locate control by name |
| `uia_click` / `uia_click_sequence` | Invoke controls |
| `uia_type` | Type into fields |
| `uia_wait` | Wait for control |
| `electron_check` / `electron_unlock` | Electron detection + unlock |
| `focus_window` / `wait_for_window` | Window management |
| `run_command` | Shell launch (`start`) |
| `open_known_app` | Voice fast-path launch |
| `keyboard_type` / `key_combo` | SendInput path |
| `find_on_screen` / OCR tools | Text locate |
| `grid_locate` (internal) | Vision SoM fallback |

---

*This document is intended to guide Orynn engineering decisions. It is not a guarantee of behavior on every Windows 11 build/SKU — always verify URIs and shell paths on target hardware.*
