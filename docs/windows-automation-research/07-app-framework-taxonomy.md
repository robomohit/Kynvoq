# 07 — Windows App Framework Taxonomy & Automation Playbooks

**Date:** 2026-06-22  
**Scope:** Per-framework automation strategy for Orynn’s UIA-first desktop agent.  
**Codebase anchors:** `app/agent.py` (`_desktop_control_profile`), `app/adaptive_windows.py` (`classify_surface_runtime`), `app/widget/desktop_features.py` (`survey_app_controls`, `electron_hint_for_app`), `app/tools.py` (resolver ladder).

---

## 1. Why framework class matters

Windows apps expose very different **accessibility surfaces** even when they look similar on screen. The same agent action — “click Save” — may succeed via `uia_click` in Notepad, fail until `electron_unlock` in VS Code, require COM in Excel bulk edits, or be impossible via UIA in a DirectX game.

Orynn’s design separates **cheap pre-flight routing** (`control_profile` before the first model turn) from **post-failure recovery** (`analyze_windows_failure` + `adaptive_windows_profiles.json`). Framework taxonomy tells the agent *which ladder to climb first* and *what to never attempt*.

---

## 2. Taxonomy overview

| Class | Representative apps | UIA tree quality | Orynn `SurfaceRuntime` (typical) | `primary_route` (typical) |
|-------|---------------------|------------------|----------------------------------|---------------------------|
| **Win32 native** | Notepad, classic dialogs, mmc, Device Manager | Rich (standard controls) | `uia_rich` | UIA exact |
| **WPF** | Visual Studio (parts), modern enterprise tools | Excellent (server providers) | `uia_rich` | UIA exact |
| **WinForms** | Legacy LOB apps, old utilities | Good–excellent | `uia_rich` / `uia_sparse` | UIA exact |
| **WinUI 3 / UWP** | Settings, Calculator, Photos, Store apps | Good–excellent | `uia_rich` | UIA exact |
| **Microsoft Office** | Word, Excel, PowerPoint, Outlook desktop | Excellent (UIA); COM better for bulk | `uia_rich` | UIA exact (+ COM when bulk) |
| **Electron / Chromium shell** | VS Code, Discord, Slack, Spotify | Poor until unlocked | `electron_locked` | Electron unlock |
| **Java Swing / AWT** | IntelliJ (partial), legacy Java LOB | Variable (Java Access Bridge) | `uia_sparse` → `visual_text` | UIA degraded / OCR |
| **Qt (Qt Widgets / QML)** | Telegram desktop (Qt), some CAD tools | Variable (Qt accessibility) | `uia_sparse` / `visual_text` | UIA degraded |
| **Games / GPU canvas** | Steam titles, Unity/Unreal, Paint 3D canvas | Empty or chrome-only | `custom_rendered` | Screenshot fallback |
| **Custom Skia/DirectX UI** | Figma canvas, Blender viewport | Sparse pane + canvas | `custom_rendered` | Keyboard + vision |

**Detection priority in Orynn today:** UIA control count → Electron hint → meaningful named controls → OCR probe → vision flag. Framework-specific exe/class heuristics are *not yet* wired into `classify_surface_runtime` — this document is the routing table to add.

---

## 3. Orynn `control_profile` & runtime detection

### 3.1 When it runs

On every desktop task (`mode in ("computer", "computer_isolated")`), **before the first model turn**, `Agent.run` calls `_desktop_control_profile` in a thread and injects the result into the system prompt via `_desktop_control_profile_text`. It also emits a `control_profile` event to the UI.

```573:715:app/agent.py
def _desktop_control_profile(
    app_hint: str = "",
    *,
    isolated: bool = False,
    model_sees: bool = False,
) -> Dict[str, Any]:
    """Cheap local routing profile for desktop tasks before the first model turn."""
    # ... surveys UIA, electron hint, OCR availability ...
    runtime_plan = classify_surface_runtime(...)
    profile["runtime"] = runtime_plan.to_dict()
    profile["primary_route"] = route  # UIA exact | Electron unlock | OCR fallback | ...
```

### 3.2 What it collects (cheap, local)

| Field | Source | Purpose |
|-------|--------|---------|
| `target_app` / `foreground_window` | `app_hint` or `foreground_window_info()` | Window disambiguation |
| `window_found`, `app_rect` | `app_window_rect` | Bounds for OCR/isolation overlay |
| `uia_control_count`, `controls[]` | `survey_app_controls(cap=90)` | Control menu for exact-name actions |
| `electron_hint` | `electron_hint_for_app` → `is_electron_app` | Chromium/Electron relaunch path |
| `ocr_available` | `ocr_available()` | Whether Windows Media OCR is installed |
| `runtime` | `classify_surface_runtime` | Structured runtime plan |
| `primary_route` | Derived from `SurfaceRuntime` | Human-readable route label for prompt |

### 3.3 `classify_surface_runtime` decision tree

Implemented in `app/adaptive_windows.py`. Uses **meaningful** control count (strips title-bar chrome: Minimize, Maximize, Close, System).

```
named_control_count >= 12        → uia_rich        → primary_layer: uia
electron_hint present            → electron_locked → electron_accessibility
meaningful_named > 0 (but < 12)  → uia_sparse      → uia_then_ocr
window missing (with app hint)   → window_missing  → window_resolution
UIA empty + OCR sees text        → visual_text     → ocr
UIA empty + OCR probe = 0 words → custom_rendered → keyboard_visual
UIA empty + OCR available        → visual_text     → ocr (probe not run)
else                             → unknown         → observe
```

`primary_route` mapping in `agent.py`:

| `SurfaceRuntime` | `primary_route` |
|----------------|-----------------|
| `uia_rich`, `uia_sparse` | UIA exact |
| `electron_locked` | Electron unlock |
| `visual_text` | OCR fallback |
| `window_missing` | Window resolution |
| `custom_rendered` (+ vision model) | Screenshot fallback |
| else | UIA degraded |

### 3.4 Prompt injection (what the model sees)

`_desktop_control_profile_text` adds:

- Target app, primary route, UIA count, OCR/vision availability
- Surface runtime + primary layer
- **Exact clickable control names** (up to 24) — “use these EXACT names, don’t invent”
- Electron unlock note when `electron_hint` is set
- `uia_wait` reminder when target window not attached

### 3.5 Lazy playbooks (`adaptive_windows_profiles.json`)

Per-app resolver memory (`remember_resolver_outcome` / `learned_resolvers`). Example: Notepad Find dialog → learned `ocr_text_target`. Consulted on failure via `analyze_windows_failure`, not at profile time.

**Gap:** Framework class (Win32 vs Qt vs Office) is not yet a profile field — only failure_class + resolver_id.

---

## 4. Universal open layer (all classes)

Before any navigate/act playbook, prefer **OS-routed opens** over UI clicking:

| Mechanism | Example | Best for |
|-----------|---------|----------|
| `run_command` / `start` | `notepad`, `calc`, `wt` | Win32 exes |
| `ms-settings:` URI | `ms-settings:bluetooth` | WinUI Settings pages |
| AUMID launch | `explorer shell:AppsFolder\Microsoft.WindowsCalculator_...!App` | UWP/Store apps |
| Protocol URI | `ms-calculator:`, `ms-photos:` | Packaged apps |
| `shell:` folder | `shell:Downloads` | Explorer locations |
| COM `Dispatch` | `Excel.Application` | Office automation entry |
| Shortcut `.lnk` | `start "" "C:\...\App.lnk"` | Apps with custom args |

Orynn voice fast-path: `open_known_app` (`_KNOWN_LAUNCH_APPS` — Notepad, Calculator, Paint, Settings, etc.).

---

## 5. Per-class playbooks

Each playbook: **Open** → **Navigate** → **Act** → **Avoid**.

---

### 5.1 Win32 native (Notepad, Calculator classic, mmc, common dialogs)

**Signals:** `notepad.exe`, `mmc.exe`, `ApplicationFrameHost` absent; HWND class `Notepad`, `#32770` (dialog); UIA `EditControl`, `ButtonControl` with human names; `uia_control_count` often ≥ 12.

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | `start <exe>` or `open_known_app` | `run_command`, `open_known_app` |
| **Navigate** | UIA control names from survey; `Alt` menu accelerators; `Tab` focus chain | `uia_click`, `uia_wait`, `key_combo` |
| **Act** | `uia_click` / `uia_type` on named controls; `Ctrl+S`, `Ctrl+F`, `Enter` | `uia_click`, `uia_type`, `keyboard_type` |
| **Avoid** | Pixel/screenshot clicks; `uia_find` before acting when names already in profile; PostMessage to child HWNDs | — |

**Classic dialog pattern (`#32770`):** OK/Cancel/Yes/No are `ButtonControl` with exact names. Use `uia_click "OK"` not coordinates.

**Notepad nuance:** Find/Replace dialog controls may be misnamed in UIA; learned playbook uses `ocr_text_target` for “Find” label (see `adaptive_windows_profiles.json`).

**Runtime:** `uia_rich` → `primary_route: UIA exact`.

---

### 5.2 WPF & WinForms

**Signals:** Deep UIA trees; `AutomationId` often stable; `Pane`/`Custom` with rich children; exe not Electron; frameworks like `PresentationFramework` in stack (hard to detect from Orynn today — infer from rich tree + non-packaged exe).

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | Shortcut path, `start`, or installer-known exe | `run_command`, `focus_window` |
| **Navigate** | `AutomationId` + Name; ribbon tabs as `TabItemControl`; expanders via `uia_click` | `uia_find`, `uia_click`, `uia_wait` |
| **Act** | `uia_type` into `EditControl`/`Document`; `InvokePattern` on buttons; ribbon shortcuts | `uia_type`, `uia_click`, `key_combo` |
| **Avoid** | Assuming Win32 dialog class names; full-tree walks (use survey cap); `SetValue` on password fields | — |

**WPF virtualized lists:** Only visible rows exist in UIA. Scroll (`scroll` tool / `ScrollPattern`) then re-survey.

**WinForms quirks:** Some controls expose type names instead of labels (`Button1`). Prefer `AutomationId` or OCR on visible text.

**Runtime:** Usually `uia_rich`; degraded WinForms → `uia_sparse`.

---

### 5.3 WinUI 3 / UWP / modern Settings

**Signals:** `ApplicationFrameHost.exe` or packaged process; AUMID in `Get-StartApps`; Settings nav items (“System”, “Bluetooth”, “Display”) in UIA survey; `ms-settings:` handler.

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | **`start ms-settings:<page>`** — never click through home | `run_command`, future `open_settings` |
| **Navigate** | Left-nav `ListItem` names from control menu; search box in Settings | `uia_click`, `uia_type` |
| **Act** | Toggle switches (`TogglePattern`); combo boxes; `uia_click` on named settings | `uia_click`, `uia_type` |
| **Avoid** | Opening Settings via Start menu search; inventing nav names not in survey; pixel clicks on toggles | — |

**Calculator (UWP):** AUMID `Microsoft.WindowsCalculator_8wekyb3d8bbwe!App` or `start calc`; buttons have names like “Plus”, “Equals” — UIA exact (validated in tests).

**Photos / Clock / Store:** AUMID or protocol (`ms-photos:`, `ms-clock:`).

**Zombie UWP frames:** `survey_app_controls` tries up to 3 HWND candidates when top match is cloaked/chrome-only.

**Runtime:** `uia_rich` when nav items visible (≥12 nodes).

---

### 5.4 Microsoft Office (Word, Excel, PowerPoint, Outlook desktop)

**Signals:** `WINWORD.EXE`, `EXCEL.EXE`, `POWERPNT.EXE`, `OUTLOOK.EXE`; enormous UIA trees; ribbon `TabItem` names; document area as `Document` / spreadsheet grid.

#### Strategy matrix: COM vs UIA vs keyboard

| Task shape | Best method | Why |
|------------|-------------|-----|
| Open file, single UI action | UIA + keyboard | Visible, verifiable |
| Read/write cell range, formulas, export | **COM** (`win32com.client`) | O(n) UIA cell access is unusable |
| Draft/edit document text | UIA `uia_type` on Document | Connectors already document this |
| Build slides, ribbon navigation | UIA clicks on ribbon names | Reliable for one-off |
| Outlook mail triage (desktop) | UIA list items + keyboard | COM (`Outlook.Application`) for bulk |
| Macro/automation repeat | COM or VBA | Outside Orynn today |

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | `start winword` / `start excel`; COM `Workbooks.Open` for scripted open | `run_command`; future `office_com` |
| **Navigate** | Ribbon tab names (`Home`, `Insert`); `Ctrl+G` go-to in Excel; Outlook folder list | `uia_click`, `key_combo` |
| **Act (UI)** | `uia_type` into Document/grid; `uia_click` ribbon buttons | `uia_click`, `uia_type` |
| **Act (bulk)** | COM: `Range.Value`, `SaveAs`, charts | Not implemented — recommended gap |
| **Avoid** | UIA per-cell loops in Excel; grid-locate on ribbon; `electron_unlock` (Office is not Electron) | — |

**Connector skills** (`connectors.py`): Excel/Word/PPT default to UIA-first instructions — correct for interactive tasks, insufficient for “fill 500 cells”.

**Runtime:** `uia_rich`. Route stays UIA exact unless task is bulk → hand off to COM layer.

---

### 5.5 Java Swing / AWT on Windows

**Signals:** `java.exe` / `javaw.exe`; requires **Java Access Bridge** (JAB) enabled; UIA may show `Pane` with sparse or rich children depending on JAB; IntelliJ/Eclipse mix Swing + custom.

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | Shortcut to IDE/app; ensure JAB: `%JAVA_HOME%\bin\jabswitch.exe -enable` | `run_command` |
| **Navigate** | UIA names when JAB active; `F10`/`Alt` menu; `Ctrl+Tab` IDE shortcuts | `uia_find`, `key_combo` |
| **Act** | `uia_click`/`uia_type` when tree rich; else OCR on visible labels + `keyboard_type` | `uia_*`, `screen_context`, OCR path |
| **Avoid** | Assuming Electron unlock; UIA tree walk without JAB (empty tree); per-pixel without vision | — |

**Detection heuristic (proposed):** `javaw.exe` in foreground + `meaningful_named_control_count < 3` → suggest JAB check in profile text.

**Runtime:** Often `uia_sparse` or `visual_text` if JAB off.

---

### 5.6 Qt applications on Windows (Widgets & Qt Quick)

**Signals:** `Qt5QWindowIcon` / `Qt6QWindowIcon` window class; `Qt accessibility` plugin shipped with app; Telegram, qBittorrent, some media tools; may expose `Button` with text or only `Custom` nodes.

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | Exe path / Start Menu shortcut | `run_command`, `focus_window` |
| **Navigate** | UIA when accessible; `Alt` menu bar; `Tab` focus | `uia_click`, `uia_wait` |
| **Act** | `uia_type` into `Edit`; `Invoke` buttons; clipboard paste for complex fields | `uia_type`, `keyboard_type` |
| **Avoid** | Treating as Electron; relying on AutomationId (often empty in Qt); grid-locate before keyboard | — |

**Qt Quick / QML:** Often sparser than Widgets — expect `uia_sparse` → OCR for visible button text.

**Runtime:** `uia_sparse` or `visual_text`.

---

### 5.7 Games & canvas / custom-rendered apps

**Signals:** `uia_control_count` ≈ 0; only chrome names (Minimize/Close/System); `visual_word_count == 0` on OCR probe; fullscreen exclusive; DirectX/Vulkan swap chain.

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | Launcher (`steam://`, platform exe) — often **out of scope** for agent | `run_command` (launch only) |
| **Navigate** | Keyboard/gamepad semantics; OCR on HUD text if any | `key_combo`, `screen_context` |
| **Act** | `SendInput` key holds/clicks; vision grid-locate **back-office only** | `keyboard_type`, `computer` (vision), `grid_locate` |
| **Avoid** | **UIA entirely**; Live path grid-locate; assuming clickable named controls; long automation sessions | — |

**Orynn classification:** `custom_rendered` → `primary_route: Screenshot fallback` (when `model_vision`); else `keyboard_visual`.

**Figma / CAD / Blender:** Hybrid — chrome is UIA; canvas is custom. Navigate panels via UIA; draw/select on canvas via vision or keyboard shortcuts only.

**When automation should fail honestly:** competitive multiplayer, anti-cheat titles, DRM overlays, full-screen games without readable HUD text.

---

### 5.8 Electron / Chromium desktop (cross-reference)

Not in the user’s numbered list but central to Orynn routing. Included because `electron_locked` is the second-most-common runtime.

| Phase | Best method | Orynn tools |
|-------|-------------|-------------|
| **Open** | Exe or protocol (`spotify:`, `discord:`) | `run_command` |
| **Navigate** | **`electron_unlock` first** if tree sparse; then UIA names | `electron_check`, `electron_unlock`, `uia_wait` |
| **Act** | `uia_click`/`uia_type` post-unlock; `keyboard_type` for contenteditable | `uia_*`, `keyboard_type` |
| **Avoid** | UIA before unlock; PostMessage; `SetValue` on React controlled inputs without input events | — |

`count_app_controls >= 40` → skip relaunch (already unlocked).

---

## 6. Framework → Orynn runtime mapping (recommended)

Proposed extensions to `classify_surface_runtime` / `_desktop_control_profile` (not yet coded):

| Detected class | Condition | Override / hint |
|----------------|-----------|-----------------|
| Win32 / WPF / WinForms / WinUI | `meaningful_named >= 12`, no electron | Confirm `uia_rich` |
| Office | exe in Office set | Add `framework: office`; suggest COM for bulk goals |
| Electron | `is_electron_app` | `electron_locked` (existing) |
| Java | `javaw.exe` + sparse tree | Prompt: enable Java Access Bridge |
| Qt | class name `Qt*QWindowIcon` | `uia_sparse`; prefer keyboard |
| Game / canvas | sparse + `visual_word_count==0` | `custom_rendered` (existing) |
| Settings intent | goal mentions setting | Inject `ms-settings:` URI before UIA |

---

## 7. Resolver ladder by class (back-office agent)

```
ALL CLASSES:
  1. Universal open (URI / AUMID / start)
  2. focus_window / wait_for_window
  3. control_profile / adaptive_observe

UIA-RICH (Win32, WPF, WinForms, WinUI, Office UI):
  4. uia_click / uia_type / uia_click_sequence (exact names from profile)
  5. key_combo shortcuts
  6. OCR (labels UIA misses)
  7. grid_locate (last resort)

ELECTRON:
  4. electron_unlock → uia_wait → uia_*
  5. keyboard_type / SendInput
  6. OCR → grid_locate

JAVA / QT (sparse):
  4. key_combo / Tab navigation
  5. OCR visible text
  6. screen_context → vision

OFFICE BULK:
  4. COM automation (recommended addition)
  5. UIA only for verification

GAMES / CANVAS:
  4. key_combo
  5. screen_context / grid_locate (agent only, not Live)
  6. Stop — do not claim UIA success
```

---

## 8. Live vs back-office policy

| Class | Gemini Live (front desk) | Back-office agent |
|-------|--------------------------|-------------------|
| Win32 / WinUI / Office UI | `open_known_app`, `uia_click`, `uia_type` | Full ladder + learned playbooks |
| Electron | UIA only if already rich; else **hand off** | `electron_unlock` with consent |
| Java / Qt | Simple UIA if names in profile; else hand off | OCR + keyboard |
| Games / canvas | **Do not automate** — defer or refuse | Vision with `allow_pixel_fallback` |
| Settings | `start ms-settings:*` | In-app UIA navigation |

---

## 9. Quick reference — avoid lists consolidated

| Class | Never do first |
|-------|----------------|
| Win32 | Screenshot coordinates for standard buttons |
| WPF/WinForms | Full desktop-root UIA walk |
| WinUI/Settings | Start menu search to open Settings pages |
| Office | Per-cell UIA in large ranges; treat as Electron |
| Java | UIA without JAB enabled |
| Qt | Assume rich AutomationId |
| Games/canvas | `uia_find` / `uia_click` by invented names |
| Electron | UIA before unlock or consent |
| All | Invent control names not in `control_profile.controls` |

---

## 10. Detection cheat sheet (exe / HWND / UIA)

| Class | Process / class hints | UIA expectations |
|-------|----------------------|------------------|
| Win32 | `notepad.exe`, `#32770` dialogs | Named Edit, Button, MenuBar |
| WPF | Unpackaged exe, deep tree | `Pane`, `Tab`, rich `AutomationId` |
| WinForms | `MyApp.exe`, mixed labels | `Button1` risk — check survey |
| UWP/WinUI | `ApplicationFrameHost`, AUMID | Nav `ListItem`, `ToggleSwitch` |
| Office | `EXCEL.EXE`, etc. | Ribbon tabs, `Document`, grid |
| Electron | `app.asar`, `chrome_100_percent.pak` | ≤9 nodes until unlock |
| Java | `javaw.exe` | Empty without JAB |
| Qt | `Qt5QWindowIcon` HWND class | Variable text on controls |
| Game | Fullscreen, GPU exe | 0 meaningful nodes, OCR empty |

---

## 11. Related Orynn artifacts

| Artifact | Path |
|----------|------|
| Parent research | `docs/windows-automation-research.md` |
| Runtime classifier | `app/adaptive_windows.py` |
| Control survey | `app/widget/desktop_features.py` |
| Profile injection | `app/agent.py` |
| Learned resolvers | `adaptive_windows_profiles.json` |
| Connector Office skills | `app/connectors.py` |
| Tests | `tests/test_adaptive_windows.py`, `tests/test_computer_control_regressions.py` |

---

## 12. Sources

- [UI Automation overview](https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32)
- [Launch Windows Settings (ms-settings)](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings)
- [Find AUMID](https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid)
- [Java Access Bridge](https://www.oracle.com/java/technologies/javase/javase-client-tech-accessibility.html)
- [Qt Accessibility](https://doc.qt.io/qt-6/accessible.html)
- [Chromium accessibility / force renderer a11y](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md)
- [Office automation via COM](https://learn.microsoft.com/en-us/office/vba/api/overview/)

---

*This document defines per-class playbooks for Orynn engineering and agent prompting. Framework detection heuristics in §6 are recommendations; runtime behavior today is driven by UIA richness and Electron/OCR probes as implemented in `classify_surface_runtime`.*
