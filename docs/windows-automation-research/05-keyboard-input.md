# 05 — Keyboard-First & Input Automation on Windows

**Date:** 2026-06-22  
**Scope:** How Orynn should use keyboard injection, accessibility navigation, and command palettes as a complement (and sometimes replacement) for UIA on Windows.  
**Codebase reviewed:** `app/tools.py`, `app/widget/desktop_features.py`, `app/agent.py`, `app/safety.py`, `app/adaptive_windows.py`

**Related:** [windows-automation-research.md](../windows-automation-research.md) (parent overview)

---

## Executive Summary

Keyboard automation is Orynn's **fast path** when an app already speaks shortcuts: save, copy, tab-navigate, open Run, invoke command palettes, and type into focused Chromium renderers. It is implemented today via **pyautogui** (which calls Win32 **SendInput** under the hood) and, for targeted UIA typing, **control-scoped `SendKeys`** (also SendInput-based).

The winning pattern for Orynn is **keyboard-first when shortcuts exist, UIA-first when names are stable, clipboard-paste when React/Electron state matters**. Keyboard beats UIA on Electron before unlock, virtualized lists, canvas surfaces, and apps where tree walks are slow but muscle memory is universal.

---

## 1. SendInput vs keybd_event vs pyautogui

### 1.1 Win32 API stack

| API | Status | Injection model | Notes |
|-----|--------|-----------------|-------|
| **SendInput** | Current standard | Inserts `INPUT` structs into the system input stream as an atomic batch | Returns count of events inserted; subject to **UIPI** (cannot inject into higher-integrity processes) |
| **keybd_event** | Deprecated | Legacy per-key events | No reliable failure reporting; events can be **spliced** with real user input |
| **mouse_event** | Deprecated | Legacy mouse events | Same failure-reporting and splicing problems |
| **PostMessage / SendMessage** (WM_KEYDOWN…) | Active but different | Posts to a window message queue | Does **not** reach Chromium/Electron renderers reliably; bypasses global hotkey handling differently |

**Microsoft guidance:** Use [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput) instead of `keybd_event` / `mouse_event`. SendInput serializes its batch — user keystrokes are not interleaved mid-batch — whereas legacy APIs can splice with physical input.

**UIPI constraint:** All three injection paths are blocked when the target runs at a higher integrity level (e.g., elevated admin console from a normal agent). Neither zero return nor `GetLastError` reliably signals UIPI blocks. Orynn should assume keyboard injection only works into **equal-or-lower** integrity foreground windows.

**Accessibility exception:** Signed apps with `uiAccess="true"` in the manifest can inject shell shortcut keys in some cases; Orynn does not need this today.

### 1.2 pyautogui — what Orynn actually uses

Orynn depends on `pyautogui>=0.9.54` (`requirements.txt`). On Windows, pyautogui's `press`, `hotkey`, `write`, and `typewrite` ultimately call **SendInput** (via its `pyautogui._pyautogui_win` backend).

| Orynn tool | Implementation | Politeness gate |
|------------|----------------|-----------------|
| `key_combo` | `pyautogui.hotkey(*parts)` | `wait_for_user_idle` via `_input_politeness_gate()` |
| `keyboard_type` | `pyautogui.write` per char, 20–80 ms jitter | Same |
| `hold_key` | `keyDown` + sleep + `keyUp` | No gate (rare; short) |
| `uia_type` (tiers 2–3) | `ctrl.SendKeys(...)` or pyautogui fallback | `wait_for_user_idle` before focus-stealing tiers |
| OCR/grid pixel click | `pyautogui.click` | Same |

**Why pyautogui and not a raw ctypes SendInput wrapper?**

- Already integrated, cross-platform surface for the agent (`key_combo`, `keyboard_type`).
- Handles modifier chord ordering (`hotkey("ctrl", "shift", "p")`).
- Sufficient for Orynn's use case; a native wrapper would add maintenance for marginal gain.

**Known pyautogui weaknesses (documented in Orynn code):**

1. **Global injection** — keys go to whatever HWND has foreground focus; a mistimed focus change sends shortcuts to the wrong app.
2. **Rapid chord + typing** — global hotkeys can drop or reorder under fast automation; `uia_type` prefers **targeted `ctrl.SendKeys`** on the UIA control for clear/paste.
3. **Per-char `typewrite`** — fixed intervals drop characters on laggy RDP/WinUI; Orynn uses **clipboard paste** as tier 2 and `interval=0.04`+ as tier 3.
4. **No batch atomicity across sleeps** — `keyboard_type` sleeps between chars, so user input *can* interleave during long strings; paste path avoids this.

### 1.3 UIA SendKeys — targeted SendInput

The `uiautomation` library's `Control.SendKeys()` sends keystrokes to the **focused control's window thread**, not blindly to the desktop. Orynn uses this for `{Ctrl}v`, `{Ctrl}a{Delete}`, etc., inside `uia_type`:

```python
ctrl.SendKeys("{Ctrl}v", waitTime=0)   # targeted paste
ctrl.SendKeys("{Ctrl}a{Delete}", waitTime=0)  # clear field
```

**SendKeys special characters** must be escaped: `{`, `}`, `+`, `^`, `%`, `~`, `(`, `)` → wrap in braces (`{+}`, `{^}`, …).

**When to prefer UIA SendKeys over pyautogui:**

- Known target control already focused via `SetFocus()`.
- Chords immediately before paste (less stray-key risk).
- Background-safe reads already done; only the typing tier needs foreground.

**When to prefer pyautogui:**

- `DocumentControl` and rich editors where UIA `SetValue` doesn't update the document model.
- Global shortcuts (Ctrl+S, Alt+Tab) with no specific control target.
- Calculator keyboard fast path, command palette invocation.

### 1.4 Decision matrix

```
Need input?
├─ Background / no focus steal     → UIA InvokePattern, SetValue (background tier)
├─ Known control, text entry       → uia_type: SetValue → paste → SendKeys/typewrite
├─ Global shortcut                 → key_combo (pyautogui/SendInput)
├─ Electron/Chromium content       → focus + paste or keyboard_type (NOT PostMessage)
├─ Elevated target                 → fail or request user action (UIPI)
└─ Legacy / deprecated API         → never use keybd_event in new code
```

---

## 2. Key-combo patterns

Orynn exposes combos as `key_combo` with `keys` formatted `"ctrl+s"`, `"alt+tab"`, `"win+r"` (case-insensitive, `+`-separated). Parsed in `tools.py`:

```python
parts = [p.strip() for p in keys.split("+") if p.strip()]
pyautogui.hotkey(*parts)
```

### 2.1 Common patterns and semantics

| Combo | VK / behavior | Orynn use | Caveats |
|-------|---------------|-----------|---------|
| **Ctrl+S** | Save | Excel/Word/VS Code connectors; universal save | May trigger browser "Save page" in Chrome if focus wrong |
| **Ctrl+C / Ctrl+V** | Copy/paste | Clipboard tier in `uia_type`; `copy_selection` | Clipboard is shared system-wide — restore after paste (Orynn does) |
| **Ctrl+Z / Ctrl+Shift+T** | Undo / reopen tab | `desktop_features` recovery helpers | App-specific availability |
| **Alt+Tab** | Flip-window (hold Alt) | Switch apps when UIA can't find HWND | **Notoriously flaky** under automation — Alt menu activation, timing. Prefer `focus_window` + exe/title |
| **Alt+F4** | Close window | Last resort | **Blocked** as high-danger in `safety.py` (requires approval) |
| **Win+R** | Run dialog | Open URI/exe without Start Menu OCR | Run dialog is UIA-friendly; type path + Enter |
| **Win+E** | File Explorer | Fast folder navigation | Reliable |
| **Win+type** | Start search | Launch unknown apps | **Avoid for agents** — search results vary by locale, indexing, promoted apps |
| **Ctrl+Shift+P** | Command palette | VS Code, Cursor, Sublime | Palette is searchable — often faster than UIA tree walk |
| **Ctrl+K** | Command palette / quick open | VS Code, Notion, Slack, browsers | Same; some apps use Ctrl+K for link insert |
| **Ctrl+L** | Address bar | Browsers, Explorer | Type URL/path directly |
| **F10 / Alt** | Activate menu bar | Legacy Win32 | Shift+F10 = context menu |
| **Escape** | Dismiss modal | Calculator fast path, dismiss overlays | |

### 2.2 Windows key handling

pyautogui maps `"win"` → `VK_LWIN`. **Win+combinations** are handled by the shell and foreground app together:

- **Win+R** opens Run even from many fullscreen apps (shell registered).
- **Win+typing** opens Start search; each character waits for indexer — slow and nondeterministic.
- **Win+L** locks workstation — **dangerous**; in Orynn `safety.py` high-danger set.

**Recommendation for Orynn:** Prefer `start ms-settings:…`, `start "" "path"`, `open` launch tools, and `focus_window` over Win+search. Use **Win+R** only for arbitrary exe/URI the registry doesn't know.

### 2.3 Alt+Tab under automation

Alt+Tab requires **holding Alt** while pressing Tab one or more times. pyautogui's `hotkey("alt", "tab")` presses and releases Alt with Tab — works for **single** flip, not "third window in MRU list."

For multi-hop:

```python
pyautogui.keyDown("alt")
for _ in range(n):
    pyautogui.press("tab")
    time.sleep(0.15)
pyautogui.keyUp("alt")
```

**Prefer:** `focus_window(app_hint)` / HWND activation — deterministic, no MRU ambiguity.

### 2.4 Safety blocklist

`safety.py` treats these as **high danger** (approval required):

- `ctrl+alt+del`
- `win+l`
- `ctrl+alt+t` (terminal in some distros — legacy block)
- `alt+f4`

All other `key_combo` actions are medium danger (side effects) but auto-approved outside safe mode.

---

## 3. Accessibility keyboard navigation

Windows apps that support accessibility expose the same navigation model users with screen readers rely on. Orynn can exploit this **without** walking the full UIA tree.

### 3.1 Core keys

| Key | UIA / a11y role | Typical effect |
|-----|-----------------|----------------|
| **Tab** | `Navigate` next focusable | Move focus forward in tab order |
| **Shift+Tab** | Previous focusable | Move focus backward |
| **Enter** | `Invoke` default button | Activate focused button/link |
| **Space** | `Toggle` / `Invoke` | Toggle checkbox, press button, activate list item |
| **Arrow keys** | `Selection` within container | Move in lists, menus, radio groups, calendars |
| **Home / End** | First/last item | Lists, text fields |
| **Ctrl+Home / Ctrl+End** | Document top/bottom | Text editors |
| **Page Up/Down** | Scroll + move selection | Lists, documents |
| **F6** | Next pane | Split views (Explorer, Office) |
| **Menu key** (VK_APPS) | Context menu | Right-click equivalent |

### 3.2 Tab order vs UIA tree order

**Tab order** is the sequence Win32/WPF/WinUI computes for keyboard focus (`TabIndex`, `IsTabStop`). It **does not always match** visual left-to-right order or UIA tree depth-first order.

**Implications for Orynn:**

- `Tab` × N is a **blind navigation** strategy — count is fragile across locales, themes, and dynamic UI.
- Prefer **named UIA find** when labels exist; use Tab only as fallback or when playbooks record tab counts.
- After `electron_unlock`, tab order in VS Code often reaches editor, sidebar, panel predictably.

### 3.3 Space vs Enter

- **Buttons:** Enter and Space usually both invoke; Enter is safer for default button.
- **Checkboxes:** Space toggles; Enter may activate dialog default instead.
- **Lists (ListView, TreeView):** Arrows move selection; Enter activates; Space may toggle checkboxes in multi-select lists.

### 3.4 Menu navigation

Legacy menus: **Alt + mnemonic** (underlined letter), then arrow keys.  
Ribbon (Office): **Alt** activates keytips, then letter sequence.  
Modern WinUI: **Access keys** vary; UIA Name often better.

**Pattern:**

```
key_combo alt           # or F10
keyboard_type f         # mnemonic
press enter
```

Fragile across languages — prefer UIA `Invoke` on named items when tree is available.

### 3.5 When a11y navigation beats tree walks

| Scenario | Why keyboard wins |
|----------|-------------------|
| Virtualized list (Explorer details, Spotify) | Only visible rows in UIA tree; arrow keys materialize rows |
| Dense Electron sidebar | Hundreds of shallow nodes; palette (`Ctrl+P` / `Ctrl+K`) faster |
| Modal dialog with few controls | Tab to default button + Enter < 100 ms |
| Custom-drawn list with SelectionPattern | Arrows use provider logic; pixel click needs coordinates |
| Password field | UIA Value may be blocked; typed input works if focused |

---

## 4. Command palettes

Command palettes are the **highest-ROI keyboard pattern** for complex productivity apps.

### 4.1 Common bindings

| App class | Open palette | Quick open / variant | Type-to-filter |
|-----------|--------------|----------------------|----------------|
| VS Code / Cursor | Ctrl+Shift+P | Ctrl+P (file) | Yes |
| Sublime Text | Ctrl+Shift+P | Ctrl+P | Yes |
| JetBrains IDEs | Ctrl+Shift+A (action) | Double Shift | Yes |
| Notion | Ctrl+K (insert) | Ctrl+P (search) | Yes |
| Slack | Ctrl+K (link) | Ctrl+G / Ctrl+T | Partial |
| Chrome/Edge | — | Ctrl+L (address) | N/A |
| Windows Terminal | — | Ctrl+Shift+P | Yes |
| Figma desktop | Ctrl+/ | — | Yes |
| Microsoft Office | Alt+Q (Tell me) | — | Yes |

### 4.2 Agent recipe (generic)

```
1. focus_window(app)
2. key_combo ctrl+shift+p    # or app-specific
3. wait 150–300 ms           # palette animation
4. keyboard_type "save all"  # fuzzy matches "File: Save All"
5. key_combo enter
```

**Why this beats UIA:**

- One chord + typed filter vs dozens of `uia_find` calls through nested menus.
- Palettes expose **actions** aggregated across extensions/plugins.
- Electron apps: palette input is a native text field — paste tier works.

### 4.3 Orynn connector hints

`connectors.py` already steers agents:

- VS Code: `electron_unlock` if tree empty, then UIA or keyboard.
- Excel: `Ctrl+S` via `key_combo` for save.
- Discord/Slack: prefer `uia_type` paste tier for message box (React state).

**Suggested playbook entries** (`adaptive_windows_profiles.json`):

```json
{
  "Code.exe": { "preferred_shortcuts": ["ctrl+shift+p", "ctrl+p"] },
  "Cursor.exe": { "preferred_shortcuts": ["ctrl+shift+p", "ctrl+k"] }
}
```

### 4.4 Failure modes

| Failure | Mitigation |
|---------|------------|
| Palette shortcut captured by OS/other app | `focus_window` first; check `electron_unlock` |
| Fuzzy match ambiguous | Type more specific string; arrow down + Enter |
| Palette plugin conflict | `adaptive_observe` records working chord |
| Non-English UI | Command names locale-dependent — prefer English palette strings in EN installs; use UIA Name as fallback |

---

## 5. AutoHotkey v2 as optional layer

[AutoHotkey v2](https://www.autohotkey.com/docs/v2/) is a **user-land macro runtime**, not a replacement for Orynn's Python agent loop.

### 5.1 What AHK v2 offers

| Feature | Benefit | Orynn relevance |
|---------|---------|-----------------|
| **SendInput / SendEvent / SendText** | Mature keyboard simulation | Same Win32 SendInput underneath |
| **SendLevel / #InputLevel** | Control hotkey recursion | Useful for user-installed macros, not agent core |
| **Remapping** | `*LWin::` etc. | Conflicts with agent `key_combo` if both active |
| **Window hooks** | `#HotIf WinActive` | Scope shortcuts per app |
| **ControlSend** | Target HWND/class | Similar to UIA SendKeys; still fails many Electron inner frames |
| **Persistent hotkeys** | User emergency stop | Could complement Orynn `RegisterHotKey` idea |

### 5.2 When to add AHK (optional)

**Good fit:**

- User-authored fixups ("when I say X, run this .ahk macro").
- Long-running remaps the agent shouldn't own.
- Prototyping chords before promoting to `key_combo` in playbooks.

**Poor fit:**

- LLM agent loop (spawn latency, opaque state, second runtime).
- Headless/cloud agent — requires interactive desktop session.
- Anything requiring structured return values (AHK → stdout/JSON bridge adds fragility).

### 5.3 Integration pattern (if ever needed)

```
Orynn agent → subprocess → AutoHotkey.exe /CP65001 script.ahk arg1 arg2
                         ← stdout JSON line
```

Keep **one** choke-point script; never let the LLM write arbitrary AHK. Version-pin scripts in repo.

**Default recommendation:** Stay on pyautogui + UIA SendKeys. Revisit AHK only for **user skill packs**, not core tooling.

---

## 6. Input politeness & user idle detection

Orynn shares the PC with a live user. Keyboard and mouse injection **steals the real input channel** — unlike UIA `InvokePattern` clicks which can target background windows.

### 6.1 Design (from `desktop_features.py`)

```text
UIA reads / InvokePattern     → no politeness gate (background-safe)
focus + paste / SendKeys      → wait_for_user_idle() first
pyautogui click / key_combo   → wait_for_user_idle() first
```

**Environment toggle:** `ORYNN_INPUT_POLITE=0` disables waiting (tests, headless).

### 6.2 `wait_for_user_idle` algorithm

```python
def wait_for_user_idle(min_idle=1.5, max_wait=8.0) -> dict:
```

1. Poll `GetLastInputInfo` → seconds since **any** system-wide input.
2. If idle ≥ `min_idle` → proceed immediately.
3. If recent input → check `_user_actively_typing`:
   - Compare idle time with `_last_synthetic_input_ts` from `note_synthetic_input()`.
   - If we sent synthetic input at roughly the same moment → **not** user → don't wait.
4. Loop every 250 ms until idle or `max_wait`.
5. After `max_wait`, **proceed anyway** (`proceeded_anyway: True`) — avoids deadlock with active typist.

**Return payload:**

| Field | Meaning |
|-------|---------|
| `waited` | Seconds spent yielding |
| `yielded` | True if we waited > 0 |
| `proceeded_anyway` | True if user kept typing through max_wait |

`tools.py` appends `_politeness_note(gate)` to tool output so the agent knows it interrupted or yielded.

### 6.3 Synthetic input discrimination

**Problem:** `SendInput` (pyautogui, SendKeys) resets `GetLastInputInfo` exactly like human input.

**Solution:** Every synthetic path calls `note_synthetic_input()` immediately after injection. The guard treats recent global input as **user activity** only if our last synthetic timestamp is **older** than the idle gap (+ 0.5 s slack).

**Test coverage:** `test_wait_for_user_idle_discriminates_own_input` in `test_computer_control_regressions.py`.

### 6.4 Operational guidance

| Situation | Behavior |
|-----------|----------|
| User dictating while agent types | Agent waits up to 8 s, then proceeds with note |
| Agent rapid-fire shortcuts | Own `note_synthetic_input` prevents self-blocking |
| Long `keyboard_type` strings | User can interleave during per-char sleeps — prefer paste tier |
| Live voice front desk | Keep utterances short; avoid long typewrite while user may speak |
| Politeness off | `ORYNN_INPUT_POLITE=0` for CI/automation |

### 6.5 Future improvements

- **BlockInput(False)** during atomic paste chord — heavy-handed; blocks user entirely.
- **SendInput batch via ctypes** for whole-string typing without inter-char gaps.
- **Per-monitor idle** — not available from `GetLastInputInfo`; system-wide only.

---

## 7. When keyboard beats UIA on complex apps

### 7.1 Decision guide

| Signal | Prefer keyboard | Prefer UIA |
|--------|-----------------|------------|
| Electron `electron_check` locked | ✓ (after focus) | After `electron_unlock` |
| Known shortcut exists (Save, Find, Palette) | ✓ | — |
| Named button stable in tree | — | ✓ `uia_click` |
| Virtualized 10k-row list | ✓ arrows / type-ahead | Partial tree |
| Canvas / game / GPU | ✓ (limited) | ✗ → OCR/grid |
| React controlled input | ✓ paste events | SetValue alone fails |
| Background operation needed | ✗ (needs focus) | ✓ InvokePattern |
| Verification by property | — | ✓ read Name/Value |
| Cross-app workflow | ✓ Win+R, Ctrl+C/V | Per-window UIA |

### 7.2 App-class cheat sheet

| Class | Keyboard-first examples | UIA-first examples |
|-------|-------------------------|-------------------|
| **Electron (unlocked)** | Ctrl+Shift+P → command; Ctrl+S; type in editor | Click named sidebar item |
| **Electron (locked)** | Focus + paste into visible field | `electron_unlock` then UIA |
| **Office** | Alt+Q Tell me; Ctrl+S; F2 edit cell | Ribbon named controls |
| **Win32 dialog** | Tab×n + Enter | `uia_click("OK")` |
| **File Explorer** | Ctrl+L path bar; type-ahead in list | Address `Edit` by name |
| **Settings** | — | Nav items have good names |
| **Calculator** | `keyboard_type` expression (Orynn fast path) | Grid buttons optional |
| **Browser (desktop)** | Ctrl+L, Ctrl+T | Prefer CDP/Playwright connector |

### 7.3 Cost model (agent loop)

| Action | Typical latency | API cost |
|--------|-----------------|----------|
| `key_combo` | 50–200 ms | Free |
| `keyboard_type` (10 chars) | 200 ms–1 s | Free |
| `uia_find` + `uia_click` | 100 ms–2 s | Free |
| `uia_find` deep tree | 2–10 s | Free |
| `adaptive_observe` + recovery | 1–5 s | Free |
| Grid-locate | 3–15 s | Vision API $ |

**Agent prompt alignment** (`agent.py`): *"App answers to keystrokes → ONE keyboard_type/key_combo beats many clicks."*

### 7.4 Hybrid sequences (recommended)

**Save in VS Code:**

```
focus_window → key_combo ctrl+s
```

**Run task in unknown Electron app:**

```
electron_unlock → focus_window → key_combo ctrl+shift+p → keyboard_type "task" → enter
```

**File Explorer deep path:**

```
focus_window → key_combo ctrl+l → uia_type/paste path → enter
```

**Notepad find (when UIA misses):**

```
key_combo ctrl+f → keyboard_type query → enter
```

---

## 8. Orynn implementation map

| Concern | Location |
|---------|----------|
| `key_combo`, `keyboard_type` | `app/tools.py` |
| Politeness gate | `desktop_features.wait_for_user_idle`, `tools._input_politeness_gate` |
| Synthetic input tracking | `note_synthetic_input`, `_last_synthetic_input_ts` |
| Targeted SendKeys typing | `desktop_features.uia_type` |
| Safety blocklist | `app/safety.py` |
| Agent keyboard-first policy | `app/agent.py` prompts |
| Recovery shortcuts | `desktop_features` (Ctrl+Z, Ctrl+Shift+T) |
| Adaptive escalation | `app/adaptive_windows.py` → `key_combo` in `next_tools` |
| Calculator keyboard fast path | `tools.py` `_calculator_keyboard_*` |

---

## 9. Recommendations

1. **Keep SendInput via pyautogui** for global shortcuts; do not introduce `keybd_event`.
2. **Promote command-palette playbooks** for VS Code, Cursor, Office, Terminal.
3. **Default to paste tier** in `uia_type` for Electron; reserve `keyboard_type` for palettes and apps without focused controls.
4. **Never use Win+typing** in autonomous loops; use launch registry / Win+R / URIs.
5. **Always `focus_window` before chords**; verify foreground HWND when shortcuts misfire.
6. **Respect politeness** in production; document `ORYNN_INPUT_POLITE=0` for dev only.
7. **AutoHotkey optional** for user macros — not agent core.
8. **Consider ctypes SendInput batch** only if paste + typewrite still drop chars on RDP.

---

## References

- [SendInput (Microsoft Learn)](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [keybd_event — superseded note](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-keybd_event)
- [UI Automation keyboard navigation](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-supportkeyboardnavigation)
- [Chromium accessibility overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md)
- [AutoHotkey v2 Send / SendInput](https://www.autohotkey.com/docs/v2/lib/Send.htm)
- Orynn: `app/widget/desktop_features.py` (INPUT POLITENESS section)
- Orynn: `docs/windows-automation-research.md` §3.3, §4
