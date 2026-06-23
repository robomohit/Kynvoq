# Windows UI Automation (UIA) — Deep Dive for Orynn

**Date:** 2026-06-22  
**Scope:** Exhaustive reference for UIA architecture, Python client stacks, performance, naming pitfalls, and how Orynn implements `uia_*` tools today.  
**Primary code:** `app/widget/desktop_features.py`, `app/tools.py`  
**Microsoft references:** [UI Automation overview](https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32), [Control patterns](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview), [Caching for clients](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients), [Tree walker](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationtreewalker), [Threading](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading), [Element properties](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-automation-element-propids)

---

## Table of Contents

1. [UIA Architecture](#1-uia-architecture)
2. [Control Patterns in Depth](#2-control-patterns-in-depth)
3. [Python Client Stacks](#3-python-client-stacks)
4. [Tree Walking, Caching, and HWND Scoping](#4-tree-walking-caching-and-hwnd-scoping)
5. [Control Naming Pitfalls](#5-control-naming-pitfalls)
6. [Speed Tactics](#6-speed-tactics)
7. [Orynn Implementation Map](#7-orynn-implementation-map)
8. [Stack Comparison Table](#8-stack-comparison-table)
9. [Code Patterns](#9-code-patterns)
10. [Orynn-Specific Recommendations](#10-orynn-specific-recommendations)

---

## 1. UIA Architecture

Microsoft UI Automation (UIA) is the successor to MSAA (Microsoft Active Accessibility). It exposes the desktop as a **tree of automation elements** connected via COM (`IUIAutomation` in `UIAutomationCore.dll`). Every HWND-backed UI surface can participate; providers on the server side implement `IRawElementProviderSimple` (and optionally fragment interfaces) and return pattern objects via `GetPatternProvider`.

### 1.1 Client / Provider Split

```
┌─────────────────────────────────────────────────────────────────┐
│  Orynn agent (client)                                           │
│  uiautomation / pywinauto / FlaUI / comtypes                    │
│       │ COM calls                                               │
│       ▼                                                         │
│  IUIAutomation (UI Automation Core)                             │
│       │ cross-process marshaling                                │
│       ▼                                                         │
│  Provider (per app)                                             │
│  Win32 common controls │ WPF/WinForms │ WinUI/XAML │ Chromium  │
└─────────────────────────────────────────────────────────────────┘
```

**Clients** read properties, request patterns, search (`FindFirst`/`FindAll`), walk (`IUIAutomationTreeWalker`), and subscribe to events. **Providers** map HWNDs and logical controls to properties and pattern interfaces (`IInvokeProvider`, `IValueProvider`, etc.). The core translates provider interfaces into client-facing `IUIAutomationInvokePattern`, `IUIAutomationValuePattern`, and so on ([control pattern overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview)).

### 1.2 Element Properties (what Orynn uses)

| Property | ID (concept) | Orynn usage |
|----------|--------------|-------------|
| **Name** | `UIA_NamePropertyId` | Primary query key in `uia_find` / `_score_match` |
| **AutomationId** | `UIA_AutomationIdPropertyId` | Secondary key; stable across locales when present |
| **ControlType** | `UIA_ControlTypePropertyId` | Maps to `Button`, `Edit`, `ListItem`, etc. |
| **BoundingRectangle** | — | Overlay tokens, OCR fallback coords |
| **IsOffscreen** | — | Rank penalty (−8 score); Electron often lies |
| **NativeWindowHandle** | — | HWND scoping via `ControlFromHandle` |
| **ClassName** | — | UWP frame chrome detection |
| **LocalizedControlType** | — | Not used directly; avoid duplicating in Name |

Per [Microsoft guidance on Name](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-automation-element-propids): Name should be a human-readable label, not necessarily identical to on-screen text; AutomationId is preferred for test stability; Name need not be unique across the desktop.

### 1.3 ControlType

`ControlType` is a well-known identifier (38+ types in UIA 3.0) describing appearance and **required/optional patterns**. Examples:

| ControlType | Typical patterns | Agent action |
|-------------|------------------|--------------|
| `Button` | Invoke | `InvokePattern.Invoke()` |
| `CheckBox` | Toggle, Invoke (sometimes) | `TogglePattern.Toggle()` |
| `Edit` | Value, Text | `ValuePattern.SetValue` or focus+paste |
| `ComboBox` | ExpandCollapse, Value, Selection | Expand then select item |
| `List` / `ListItem` | Selection, Scroll | `SelectionItemPattern.Select()` |
| `MenuItem` | Invoke, ExpandCollapse | Invoke or expand submenu |
| `TreeItem` | Selection, ExpandCollapse | Select / expand node |
| `Document` | Text, Value | Rich editors; paste preferred over SetValue |
| `Pane` / `Group` | Container only | Often noise; skip as click targets |
| `Window` | Transform, Window | Root scoping, not a button |

Orynn's `_INTERACTIVE_CTRL_TYPES` in `desktop_features.py` filters survey output to actionable types: `ButtonControl`, `ListItemControl`, `TabItemControl`, `MenuItemControl`, `HyperlinkControl`, `CheckBoxControl`, `RadioButtonControl`, `TreeItemControl`, `ComboBoxControl`, `SplitButtonControl`, `EditControl`.

### 1.4 Tree Structure and Scopes

- **Root:** `GetRootControl()` → desktop children = top-level windows.
- **TreeScope** (for `FindFirst`/`FindAll`):
  - `Element` — the element itself
  - `Children` — direct children only (**preferred for performance**)
  - `Descendants` — full subtree (**expensive**; can freeze browsers)
  - `Subtree` — element + descendants

Microsoft explicitly warns: when searching top-level windows on the desktop, use `TreeScope_Children`, not `Descendants`, or you may iterate thousands of elements and risk stack overflow ([FindFirst guidance](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationelement-findfirst)).

Orynn scopes searches to **ranked app roots** (`_uia_root_candidates`) rather than walking from the desktop root — correct architecture.

### 1.5 Events (not yet used by Orynn)

UIA supports `StructureChanged`, `PropertyChanged`, `AutomationFocusChanged`, etc. Subscribing to structure events on Electron can **activate the Chromium accessibility bridge** without relaunch (alternative to `--force-renderer-accessibility`). Orynn today uses relaunch + polling (`uia_wait`) instead.

---

## 2. Control Patterns in Depth

Patterns represent **capabilities**, not types. One element can expose multiple patterns. Orynn's `invoke_ui_element` and `type_into_ui_element` use a prioritized ladder.

### 2.1 InvokePattern

- **Provider:** `IInvokeProvider::Invoke`
- **Client:** `IUIAutomationInvokePattern::Invoke`
- **For:** buttons, hyperlinks, menu items that fire a single action
- **Orynn:** Primary activation in `invoke_ui_element`; also `ancestor_invoke` when child label lacks pattern but parent `ButtonControl` has Invoke
- **Advantage:** Works on **background/covered windows**; no mouse move

### 2.2 ValuePattern

- **Provider:** `IValueProvider::SetValue` / `get_Value`
- **For:** text fields, combo edit boxes, sliders with string values
- **Orynn:** `_try_background_setvalue` for non-Electron edits — verifies read-back before accepting
- **Limit:** React/Electron often updates DOM visually but not component state via SetValue; Orynn falls through to clipboard paste

### 2.3 TogglePattern

- **Provider:** `IToggleProvider::Toggle`, `get_ToggleState` (Off/On/Indeterminate)
- **For:** checkboxes, toggle switches, checkable menu items
- **Orynn:** Second tier in `invoke_ui_element` after Invoke fails

### 2.4 SelectionPattern / SelectionItemPattern

- **Selection:** container (`ISelectionProvider`) — which items selected, supports multiple?
- **SelectionItem:** `Select()`, `AddToSelection()`, `RemoveFromSelection()`, `get_IsSelected`
- **For:** list boxes, tabs, tree items, Discord servers/channels
- **Orynn:** `selection_pattern` method for list/tree navigation without pixel clicks

### 2.5 ScrollPattern / ScrollItemPattern

- **Scroll:** `Scroll`, `SetScrollPercent`, horizontal/vertical availability on containers
- **ScrollItem:** `ScrollIntoView()` on individual items in virtualized lists
- **Orynn:** Calls `ScrollItemPattern.ScrollIntoView()` before invoke on offscreen Electron list items

### 2.6 ExpandCollapsePattern

- **States:** `ExpandCollapseState` — Leaf, Collapsed, Expanded, PartiallyExpanded
- **Methods:** `Expand()`, `Collapse()`
- **For:** menus, tree nodes, combo drop-downs, accordions
- **Orynn:** **Not yet explicitly used** — combo/nested menu automation could add `ExpandCollapsePattern.Expand()` before child search. Today, substring find + invoke often suffices on Win32; WinUI/Office nested menus may need this pattern added.

### 2.7 Other Patterns (reference)

| Pattern | Use case |
|---------|----------|
| TextPattern | Rich text, selection ranges (Word, Notepad) |
| WindowPattern | Close, maximize, wait for idle |
| TransformPattern | Move/resize |
| GridPattern / TablePattern | Excel-like surfaces |
| LegacyIAccessiblePattern | MSAA bridge; Orynn uses `DoDefaultAction` as tier 2d |
| DockPattern | Toolbars |

---

## 3. Python Client Stacks

All serious Windows UIA clients ultimately call the same `IUIAutomation` COM API. Differences are ergonomics, backend maturity, and cache support.

### 3.1 `uiautomation` (Yinkang Liu) — **Orynn's choice**

```python
pip install uiautomation
```

- Thin Python wrapper over `UIAutomationClient.dll`
- High-level `Control`, `ButtonControl`, `WindowControl` with search helpers (`Control(searchDepth=..., Name=...)`)
- `ControlFromHandle(hwnd)`, `GetRootControl()`, `GetForegroundControl()`
- Global timeouts: `SetGlobalSearchTimeout`, `SetGlobalSearchInterval` (Orynn sets 1.0s / 0.05s)
- **Pros:** Minimal deps, fast to integrate, good for agent tools
- **Cons:** Limited explicit `CacheRequest` exposure; generic `Control` objects lack typed `GetInvokePattern()` — Orynn works around via `GetPattern(PatternId.InvokePattern)`

### 3.2 `pywinauto`

- Dual backend: **win32** (legacy) and **uia**
- `Application(backend="uia").connect(handle=hwnd)` → window wrapper
- `child_window(title="Save", control_type="Button")` — builds conditions
- **Pros:** Rich window/process attachment, good for scripted app tests
- **Cons:** Heavier; less ideal for hundreds of unknown apps; still cross-process per property without cache config

### 3.3 `comtypes` / raw `pywin32`

- Generate or hand-write COM bindings to `IUIAutomation`
- Full access to `IUIAutomationCacheRequest`, `FindFirstBuildCache`, `ElementFromHandleBuildCache`
- **Pros:** Maximum performance control; batch property fetch
- **Cons:** Verbose; maintenance burden; Orynn would duplicate `uiautomation` logic

### 3.4 `pywin32` UIA exposure

- `win32com.client` can dispatch some automation pieces but UIA is not first-class
- Orynn uses `pywin32` for **HWND operations** (`GetForegroundWindow`, `EnumWindows`, `AppActivate`) alongside `uiautomation`, not for tree walking

### 3.5 FlaUI (.NET) — conceptual peer

FlaUI is the modern .NET wrapper (UIA2/UIA3) often used in C# test automation.

| Concept | FlaUI | Orynn (`uiautomation`) |
|---------|-------|------------------------|
| Root | `Automation.GetDesktop()` | `GetRootControl()` |
| From HWND | `FromHandle(hwnd)` | `ControlFromHandle(hwnd)` |
| Conditions | `ConditionFactory.ByName("Save")` | `Control(Name="Save", searchDepth=...)` |
| Patterns | `AsButton().Invoke()` | `GetPattern(PatternId.InvokePattern)` |
| Cache | `CacheRequest` fluent API | Partial / library-internal |

**When FlaUI matters for Orynn:** If you port hot paths to a C# sidecar for cache-heavy observation, FlaUI is the idiomatic choice. Python can stay orchestration-layer.

### 3.6 Stack Selection Rationale for Orynn

Orynn correctly uses **`uiautomation` + `pywin32` HWND helpers**. Moving to raw `comtypes` is justified only for a dedicated **cached observation service** (batch survey of 500+ nodes). Replacing with `pywinauto` adds little for a multi-app agent.

---

## 4. Tree Walking, Caching, and HWND Scoping

### 4.1 Why Tree Walking Is Slow

Each `GetChildren()`, `Name`, `BoundingRectangle` call may cross process boundaries into the provider's apartment. Microsoft states that **manual tree walking via `IUIAutomationTreeWalker` is less efficient than `FindFirst`/`FindAll`** with conditions ([IUIAutomationTreeWalker](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationtreewalker)).

Reported pain points ([Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/2151409/why-uiautomation-findfirst-is-slow-and-can-i-corre)):

- `TreeScope_Descendants` on large trees (browsers) causes UI lag
- Fix: chained `TreeScope_Children` searches down known path, or scope to HWND subtree

### 4.2 Orynn's Hybrid Search Strategy

`find_ui_elements` and `_find_uia_control` implement a **two-phase search**:

1. **Native exact lookup:** `root.Control(searchDepth=0xFFFFFFFF, Name=q)` with `Exists(maxSearchSeconds=0)` — single immediate probe in UIA C++ core (~2× faster than Python walk per code comments)
2. **Scored DFS walk:** depth cap `_UIA_MAX_DEPTH = 40`, early exit on exact match (`score >= 100`), cap results at `limit`

Additional optimizations:

- Skip depth-0 root from matching (window title steals substring queries)
- Search up to **3 ranked roots** (cloaked UWP zombie frames)
- `_find_uia_control` retries every **200ms for 2s** before giving up

### 4.3 Caching (Microsoft vs Orynn)

**Microsoft model** ([caching for clients](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients)):

- Build `IUIAutomationCacheRequest` with property IDs + pattern IDs + `TreeScope`
- Pass to `FindFirstBuildCache`, `ElementFromHandleBuildCache`, `GetFirstChildElementBuildCache`
- Read via `GetCachedPropertyValue` — **one cross-process round trip for many properties**

**Orynn application-level cache** (`tools.py`):

| Cache | TTL | Key | Invalidation |
|-------|-----|-----|--------------|
| `_uia_find_cache` | 2.0s | query + app + limit + fg HWND | `_clear_uia_find_cache()` on click/type/sequence |
| `_adaptive_observe_cache` | ~4s | app + cap | separate path |

Window-scoped keys include foreground HWND so cache does not bleed across focus changes.

**Gap:** No COM-level `CacheRequest` during `survey_app_controls` / `_walk_survey` — each node still pays per-property COM cost. Highest ROI future improvement.

### 4.4 HWND-Scoped Search

**Correct pattern:**

```text
hwnd = GetForegroundWindow()  # or from EnumWindows + title match
element = Automation.ElementFromHandle(hwnd)  # C# / FlaUI
# Python uiautomation:
element = uia.ControlFromHandle(hwnd)
matches = element.FindFirst(TreeScope.Descendants, condition)  # scoped, not desktop-wide
```

Orynn's `_uia_root_candidates`:

1. Enumerate `GetRootControl().GetChildren()` with title scoring
2. Merge Win32 `EnumWindows` results via `ControlFromHandle(hwnd)` for HWNDs UIA tree missed
3. Score: exact title, `WindowControl`, `_has_real_content`, foreground bonus, cloaked penalty (−150)

This is **HWND-aware root selection** without requiring the agent to pass raw HWND.

### 4.5 Depth and Caps

| Constant | Value | Purpose |
|----------|-------|---------|
| `_UIA_MAX_DEPTH` | 40 | Electron DOM depth 12+; shallow walks miss controls |
| `survey cap` | 90 nodes | Stop walk early |
| `max_names` | 28–36 | Control menu size for LLM |
| `find limit` | 5 default | Top-N matches |

### 4.6 Threading

Microsoft requires UIA client calls from a **non-UI thread** if automating the same process ([threading issues](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading)). Orynn runs from agent worker threads — OK for external apps. **Risk:** if Orynn ever queries its own Qt capsule UI via UIA on the GUI thread, deadlock/slowdown can occur.

---

## 5. Control Naming Pitfalls

### 5.1 WinUI 3 / UWP

| Pitfall | Symptom | Orynn mitigation |
|---------|---------|------------------|
| **ApplicationFrameHost** zombie frames | Title matches live app; tree is empty chrome | `_window_cloaked`, `_has_real_content`, multi-root fallback |
| **LocalizedControlType in Name** | `"Button"` instead of `"Save"` | `_is_chrome_control` filters CamelCase type names |
| **Rehosted web content** | Shallow tree until WebView2 a11y loads | `uia_wait`, retry loop in `_find_uia_control` |
| **0×0 BoundingRectangle** | "Offscreen" but visible | Keep control, rank −8; Invoke still works |

### 5.2 Microsoft Office

| Pitfall | Symptom | Mitigation |
|---------|---------|------------|
| Deep nested panes | Slow walks | Search-first by Name; COM automation for bulk Excel/Word |
| Ribbon controls | Name may be `"Bold"` buried under tabs | Use KeyTips (`Alt`, sequences) keyboard fallback |
| Duplicate names | Multiple `"Sheet1"` regions | Prefer `AutomationId`; scope to foreground document HWND |
| Canvas charts | Single `Pane` | OCR / vision fallback |

### 5.3 Electron / Chromium

| Pitfall | Symptom | Orynn mitigation |
|---------|---------|------------------|
| **Accessibility bridge off** | 3–9 top-level controls only | `electron_check`, `electron_unlock` (`--force-renderer-accessibility`) |
| **Shadow DOM / web components** | Unnamed `Group` nodes | `ancestor_invoke` walks parent `ButtonControl` |
| **Virtualized lists** | Offscreen items | `ScrollItemPattern.ScrollIntoView()` |
| **React inputs** | SetValue doesn't update state | Clipboard paste via `ctrl.SendKeys("{Ctrl}v")` |
| **Security** | `password` fields blocked | Keyboard / user handoff |

### 5.4 Empty or Misleading Trees

| App class | Tree quality |
|-----------|--------------|
| Games / GPU canvas | Empty or single `Pane` → grid-locate |
| Custom Skia/DirectX | Sparse | OCR + vision |
| Electron (locked) | Nearly empty | `electron_unlock` |
| Electron (unlocked) | Thousands of nodes | Cap walks; exact name search |
| Win32 standard | Excellent | UIA-first |
| Windows Settings | Good nav items | `adaptive_observe` survey |

### 5.5 Orynn `_score_match` Ranking

```text
exact Name       → 100
exact AutomationId → 95
word boundary    → 60
name startswith  → 70
substring in name→ 50
substring in id  → 40
substring in role→ 20
```

Teaching errors (`_miss_error`) return **actual control names** from `_survey_controls_under` plus `difflib` nearest matches — reduces LLM hallucination loops.

---

## 6. Speed Tactics

### 6.1 Search-First, Walk Second

Always prefer conditioned `FindFirst` over DFS. Orynn:

```python
fast = root.Control(searchDepth=0xFFFFFFFF, Name=q)
if fast.Exists(maxSearchSeconds=0, searchIntervalSeconds=0):
    return fast  # immediate
# else scored walk
```

Extend with `AutomationId` condition when agents learn stable IDs from `adaptive_observe`.

### 6.2 Batch Invoke — `uia_click_sequence`

`tools.uia_click_sequence` collapses N clicks into **one tool round-trip**:

- Clears find cache before mutating UI
- Per target: `invoke_ui_element` → OCR fallback → stop on error
- `time.sleep(0.06)` between steps (minimal settle; not 0.5s blind wait)
- Calculator fast path: keyboard `pyautogui.write(expression)` when `read_result` set

**Why it matters:** Eliminates LLM drift between clicks; amortizes Python import and root resolution.

### 6.3 Keyboard Fallback

When UIA tree is reliable but clicking digits is slow (Calculator):

- `uia_click_sequence` → `_calculator_keyboard_fast_path` types `3*9=` via keyboard
- `type_into_ui_element` → `DocumentControl` uses foreground `Ctrl+V`
- Agent prompt: prefer `Ctrl+S`, `Alt+F4`, `Tab` over hunting buttons

### 6.4 `uia_wait` vs `sleep`

| Approach | Behavior | When |
|----------|----------|------|
| `time.sleep(2)` | Always waits 2s | **Avoid** |
| `uia_wait(query, timeout=6)` | Polls every 0.12s until found | After navigation, dialog open, app launch |
| `_find_uia_control` internal | 200ms × 10 retries | Transient render |
| `_wait_foreground` | HWND title poll | Before OCR/vision capture |

`wait_for_ui_element` calls `find_ui_element` in a loop — returns **as soon as** control appears with `waited_s` recorded.

Agent guidance (`agent.py`): *"Just navigated → uia_wait the next control. Never sleep."*

### 6.5 Other Orynn Speed Choices

- **InvokePattern over pixel click** — no focus steal, works covered windows
- **`SetValue` background tier** — no keyboard for plain Win32 edits
- **2s `uia_find` cache** — reread same query without tree walk
- **`survey_app_controls` once** via `adaptive_observe` — reduces bad guesses
- **DPI awareness** (`SetProcessDpiAwareness`) — correct rects, fewer OCR retries
- **Input politeness** — only before mouse/keyboard hijack, not before UIA read

### 6.6 Anti-Patterns

| Anti-pattern | Cost |
|--------------|------|
| Desktop-root `Descendants` search | Seconds + app freeze |
| Uncapped full tree dump | 10k+ nodes in unlocked Electron |
| Pixel click when Invoke works | Focus steal + user conflict |
| `sleep` after every click | 10× latency on sequences |
| Ignoring cloaked UWP window | Permanent miss |

---

## 7. Orynn Implementation Map

### 7.1 Layer Diagram

```text
Agent (agent.py)
  │ ActionType.uia_find | uia_click | uia_type | uia_wait | uia_click_sequence
  ▼
Tools (tools.py)
  │ cache, OCR/vision fallback, electron hints, overlay tokens
  ▼
desktop_features.py
  │ find_ui_elements, invoke_ui_element, type_into_ui_element, wait_for_ui_element
  ▼
uiautomation (COM) + pywin32 (HWND) + pyautogui (fallback input)
```

### 7.2 `desktop_features.py` — Core Functions

| Function | Role |
|----------|------|
| `_ensure_uia_config` | 1.0s search timeout, 0.05s interval |
| `_uia_root_candidates` | Ranked HWND roots, cloaked/content checks |
| `_score_match` | Fuzzy name/id scoring |
| `find_ui_elements` | Multi-match search + `_miss_error` teaching |
| `_find_uia_control` | Live `Control` object for mutations |
| `invoke_ui_element` | Scroll → Invoke → Toggle → Select → Focus → Ancestor → Legacy → pixel |
| `type_into_ui_element` | SetValue background → focus → paste → keystroke |
| `wait_for_ui_element` | Poll until found |
| `survey_app_controls` | One walk → count + interactive names |
| `electron_hint_for_app` | Relaunch guidance |
| `_uia_pattern` | `GetPattern(PatternId.X)` for generic controls |

### 7.3 `tools.py` — `uia_*` Tools

| Tool | Delegates to | Fallback ladder |
|------|--------------|-----------------|
| `uia_find` | `find_ui_elements` | OCR find → electron hint → adaptive recovery |
| `uia_click` | `invoke_ui_element` | OCR click → grid-locate vision |
| `uia_type` | `type_into_ui_element` | OCR type (click field + paste) |
| `uia_wait` | `wait_for_ui_element` | electron hint on timeout |
| `uia_click_sequence` | `invoke_ui_element` × N | OCR per step; calculator keyboard fast path |

**Cache rules:**

- `uia_find` → cached 2s (HWND-scoped key)
- `uia_click`, `uia_type`, `uia_click_sequence` → **clear cache** before mutate

**Overlay tokens:** `_uia_rect_token` embeds `[uia:left,top,w,h]` for widget focus ring; `_app_rect_token` for window glow (DWM extended frame bounds via `_dwm_visible_rect`).

### 7.4 Pattern Usage in Orynn Today

| Pattern | Used? | Where |
|---------|-------|-------|
| Invoke | ✅ | `invoke_ui_element` |
| Value | ✅ | `_try_background_setvalue` |
| Toggle | ✅ | `invoke_ui_element` |
| SelectionItem | ✅ | `invoke_ui_element` |
| ScrollItem | ✅ | pre-invoke scroll into view |
| ExpandCollapse | ❌ | Future: menus/combos |
| Scroll | ❌ | Future: container scroll before find |
| Text | ❌ | Future: read-only verification |
| Window | ❌ | Could replace some `focus_window` |

---

## 8. Stack Comparison Table

| Stack | Language | UIA access | Cache API | HWND scope | Invoke/Value | Maturity | Orynn fit |
|-------|----------|------------|-----------|------------|--------------|----------|-----------|
| **uiautomation** | Python | Native COM wrapper | Limited | `ControlFromHandle` | Via `GetPattern` | High | **Production** |
| **pywinauto (uia)** | Python | Via UIA backend | Some | `connect(handle=)` | Wrapper methods | High | Alternative |
| **comtypes** | Python | Raw `IUIAutomation` | Full | `ElementFromHandleBuildCache` | Full | DIY | Sidecar candidate |
| **pywin32** | Python | Partial / HWND focus | No | Excellent | N/A | HWND only | **Supplement** |
| **FlaUI** | C# | UIA3 primary | Excellent | `FromHandle` | Fluent | Excellent | Future sidecar |
| **AutoHotkey UIA** | AHK v2 | UIA plugin | Basic | By HWND | Scriptable | Niche | User macros |
| **WinAppDriver** | HTTP | Selenium-like | Server-side | Session window | Limited | Legacy | Not recommended |
| **Accessibility Insights** | Tool | Inspect only | N/A | Yes | N/A | Debug | Dev tool |

---

## 9. Code Patterns

### 9.1 Orynn-Style Pattern Invoke (from `desktop_features.py`)

```python
def _uia_pattern(ctrl, pattern_name: str):
    getter = getattr(ctrl, f"Get{pattern_name}", None)
    if getter is not None:
        pattern = getter()
        if pattern is not None:
            return pattern
    import uiautomation as uia
    pattern_id = getattr(uia.PatternId, pattern_name, None)
    if pattern_id is not None:
        return ctrl.GetPattern(pattern_id)
    return None

# Usage
ip = _uia_pattern(ctrl, "InvokePattern")
if ip is not None:
    ip.Invoke()
```

### 9.2 HWND-Scoped Exact Find

```python
import uiautomation as uia

hwnd = 0x00123456  # from win32gui.FindWindow / EnumWindows
root = uia.ControlFromHandle(hwnd)
btn = root.Control(searchDepth=0xFFFFFFFF, Name="Save")
if btn.Exists(maxSearchSeconds=0):
    btn.GetPattern(uia.PatternId.InvokePattern).Invoke()
```

### 9.3 Scored Walk with Early Exit (simplified)

```python
def walk(ctrl, depth=0):
    if depth > MAX_DEPTH or best_score >= 100:
        return
    score = score_match(query, ctrl.Name, ctrl.AutomationId, ctrl.ControlTypeName)
    if depth > 0 and score > best_score:
        best_score, best_ctrl = score, ctrl
    for child in ctrl.GetChildren():
        if best_score >= 100:
            break
        walk(child, depth + 1)
```

### 9.4 Value Set with Verification

```python
vp = ctrl.GetPattern(uia.PatternId.ValuePattern)
vp.SetValue("hello")
assert str(vp.Value) == "hello"  # Orynn: reject if read-back fails
```

### 9.5 comtypes CacheRequest (reference — not in Orynn yet)

```python
# Conceptual — full COM boilerplate omitted
cache_request = automation.CreateCacheRequest()
cache_request.AddProperty(UIA_NamePropertyId)
cache_request.AddProperty(UIA_ControlTypePropertyId)
cache_request.AddPattern(UIA_InvokePatternId)
cache_request.TreeScope = TreeScope_Element | TreeScope_Children

element = automation.ElementFromHandleBuildCache(hwnd, cache_request)
# Subsequent GetCachedPropertyValue calls avoid extra round-trips
```

### 9.6 FlaUI Equivalent (C# reference)

```csharp
var app = AutomationElement.FromHandle(hwnd);
var condition = new PropertyCondition(AutomationElement.NameProperty, "Save");
var button = app.FindFirst(TreeScope.Descendants, condition);
var invoke = button.Patterns.Invoke.Pattern;
invoke.Invoke();
```

### 9.7 Agent Tool Sequence (recommended)

```text
focus_window("Notepad")
uia_wait("Edit", app="Notepad", timeout=6)
adaptive_observe(app="Notepad")   # optional: get exact control menu
uia_type("Edit", "Hello world", app="Notepad")
uia_click_sequence(["File", "Save As"], app="Notepad")  # prefer exact names from observe
```

---

## 10. Orynn-Specific Recommendations

### 10.1 Keep (already correct)

1. **UIA-first resolver ladder** with OCR → vision only on classified miss
2. **`invoke_ui_element` pattern ladder** before pixel click
3. **Multi-root search** with cloaked/UWP zombie handling
4. **`uia_click_sequence`** for multi-step UI (Calculator, forms)
5. **`uia_wait` over sleep** in agent prompts
6. **Electron unlock** via `--force-renderer-accessibility` (no DLL injection)
7. **Teaching errors** with real control names on miss
8. **Clipboard paste** for React/Electron inputs
9. **2s find cache** with invalidation on mutations
10. **Generic `GetPattern` workaround** for typed-control AttributeError bug

### 10.2 High-ROI Improvements

| Priority | Change | Benefit |
|----------|--------|---------|
| P0 | Add `ExpandCollapsePattern.Expand()` in invoke ladder for menus/combos | Fixes WinUI/Office submenu misses |
| P1 | COM `CacheRequest` in `_walk_survey` / `find_ui_elements` | 3–10× faster observation |
| P1 | `FindFirst` on `AutomationId` when observe records IDs | Stable across localized UIs |
| P2 | UIA `StructureChanged` listener for Electron unlock without relaunch | Better UX than restart |
| P2 | Pass optional `hwnd` to tools for multi-window same-title apps | Disambiguate 5× Notepad |
| P3 | C# FlaUI sidecar microservice for bulk cache walks | Scale to 100+ apps observation |

### 10.3 Agent Prompt Rules (encoded in `agent.py`)

- Use exact names from `uia_find` / `adaptive_observe` output
- After navigation → `uia_wait`, not `sleep`
- Electron empty tree → `electron_check` / `electron_unlock` before vision
- Prefer `uia_click_sequence` over N× `uia_click` for ordered digit/form entry
- Live fast path: `allow_pixel_fallback=False` on `uia_click`/`uia_type` for clean escalation

### 10.4 Testing Checklist

| Scenario | Expected path |
|----------|---------------|
| Calculator `1+2=` | `uia_click_sequence` or keyboard fast path |
| Notepad typing | `ValuePattern` background or paste |
| Discord channel click (unlocked) | `SelectionItemPattern` or `Invoke` |
| Discord (locked) | Miss + `electron_hint` |
| Settings nav | `survey_app_controls` names match |
| Cloaked UWP frame | Fall through to 2nd ranked root |
| Covered window button | `InvokePattern` without foreground |

### 10.5 When UIA Should Not Be Attempted

- Full-screen games / GPU-only rendering
- System watermark ("Activate Windows") — demoted but still noise
- Bulk Excel mutation — prefer COM
- Web SaaS in browser — prefer CDP/Playwright connector
- Password fields in hardened browsers — user handoff

---

## Appendix A — Official Microsoft Documentation Index

| Topic | URL |
|-------|-----|
| UI Automation entry | https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32 |
| Control patterns overview | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview |
| Provider pattern interfaces | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cpinterfaces |
| Client pattern interfaces | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-client-controlpatterninterfaces |
| Caching for clients | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients |
| Tree walker | https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationtreewalker |
| FindFirst | https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationelement-findfirst |
| ElementFromHandle | https://learn.microsoft.com/en-us/dotnet/api/system.windows.automation.automationelement.fromhandle |
| Property IDs (Name, AutomationId) | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-automation-element-propids |
| Threading | https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading |
| Server-side provider impl | https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/server-side-ui-automation-provider-implementation |

---

## Appendix B — Glossary

| Term | Meaning |
|------|---------|
| **UIA** | Windows UI Automation API (UIA 3.0) |
| **MSAA** | Legacy Microsoft Active Accessibility (`IAccessible`) |
| **Provider** | Server-side code exposing a control tree |
| **Pattern** | Interface for action (Invoke, Value, …) |
| **ControlType** | Well-known role (Button, Edit, …) |
| **AutomationId** | Developer-assigned stable id string |
| **HWND** | Win32 window handle; scope boundary |
| **Cloaked** | DWM-hidden window (suspended UWP) |
| **Bridge** | Chromium accessibility tree exporter |

---

*This document is part of the Orynn windows-automation-research series. See also `docs/windows-automation-research.md` for the broader method comparison and scaling playbook.*
