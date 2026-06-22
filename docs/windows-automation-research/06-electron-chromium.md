# 06 — Electron/Chromium Desktop Apps on Windows (Automation Research)

**Scope:** Why Chromium-based desktop shells hide their UI Automation (UIA) tree, how Orynn unlocks them, per-app web-vs-desktop strategy for the ten most common targets, CDP as an alternative, and how CEF/WebView2/Electron differ for automation.

**Related Orynn code:** `app/widget/desktop_features.py`, `app/tools.py` (`electron_check`, `electron_unlock`), `app/connectors.py`, `docs/windows-automation-research.md`.

---

## Executive Summary

Chromium-derived desktop apps (Electron, CEF, WebView2) **do not expose their DOM to Windows UIA by default**. Chromium keeps accessibility off until it detects assistive technology or is launched with `--force-renderer-accessibility`. Without unlock, UIA sees only a shallow window chrome — buttons like Minimize/Close, maybe a single `Document` node — and automation agents falsely conclude "control not found."

Orynn's default path is **unlock + UIA**: detect Electron/CEF, relaunch with the Chromium flag, then use existing `uia_find` / `uia_click` / `uia_type`. CDP is kept as an opt-in power-user path because Electron upgrades have broken remote debugging ports (Figma 126+, Electron #41325). For SaaS-heavy workflows, **browser automation (Playwright/CDP in Edge/Chrome) often beats desktop UIA** even when a desktop app exists.

---

## 1. Why the UIA Tree Is "Locked"

### 1.1 Chromium's lazy accessibility model

Chromium accessibility is **off by default and enabled on demand** for performance ([Chromium accessibility overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md)). The renderer process owns the DOM and builds the internal AX (accessibility) tree; the browser process mirrors it into OS APIs (MSAA/IAccessible, IAccessible2, UI Automation). That mirror is expensive and is skipped unless needed.

On Windows, Chromium historically probes for assistive technology by firing `NotifyWinEvent(EVENT_SYSTEM_ALERT)` with a custom object id and waiting for a `WM_GETOBJECT` response ([Chromium design doc](https://www.chromium.org/developers/design-documents/accessibility/)). Screen readers and some UIA clients trigger this handshake; a typical automation agent walking the tree **does not**, so the tree stays sparse.

Modern Chromium also respects `UiaClientsAreListening()` — if no UIA client has subscribed to events, the full provider may never materialize. Subscribing to `FocusChanged` (or similar) at session start is an alternative unlock that avoids relaunch; Orynn documents this as a gap ([parent research §7](windows-automation-research.md)).

### 1.2 Multi-process architecture

Electron/CEF/WebView2 all inherit Chromium's split:

| Process | Role | UIA relevance |
|---------|------|---------------|
| **Browser / main** | Owns HWND, receives OS input | Exposes root window to UIA |
| **Renderer** | Runs HTML/CSS/JS, owns DOM | Holds real AX tree |
| **GPU / utility** | Compositing, network, etc. | Usually invisible to UIA |

Renderer processes **cannot** talk to the OS directly. Accessibility data must be serialized browser-side and mapped to UIA nodes. Until accessibility mode is active, UIA clients see the native window frame, not individual buttons, tabs, or text fields inside the web view.

### 1.3 What "locked" looks like in practice

Symptoms Orynn agents hit:

- `survey_app_controls` returns **≤5 controls** (title bar only: Minimize, Maximize, Close).
- `uia_find` for obvious labels ("Search", "File", "Send") returns no match.
- OCR may still find visible text, but **semantic click-by-name fails**.
- `count_app_controls` below Orynn's **40-control threshold** triggers unlock suggestion.

This is not a bug in UIA or Orynn — it is intentional Chromium behavior.

### 1.4 `--force-renderer-accessibility`

Official Chromium switch ([overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md)):

```
--force-renderer-accessibility=[basic|form-controls|complete]
```

- Without parameter: defaults to `complete` mode at launch.
- Forces AX serialization for the entire session regardless of AT detection.
- Maps DOM elements → UIA roles (`ButtonControl`, `EditControl`, `Document`, etc.).

**Version caveat:** Recent Chrome/Edge builds sometimes require `=complete` explicitly (Blue Prism community reports for Chrome 117+). Orynn currently passes the bare flag; consider upgrading to `--force-renderer-accessibility=complete` if unlock regressions appear on newer Chromium.

**Alternatives without relaunch:**

| Method | Mechanism | Orynn status |
|--------|-----------|--------------|
| `chrome://accessibility` | In-browser toggle | Manual only |
| UIA event subscription | Wakes provider when client listens | Documented gap |
| Screen reader running | Triggers AT detection | Not relied upon |
| CDP `Accessibility.getFullAXTree` | Programmatic AX via DevTools | Opt-in (`also_remote_debug`) |

### 1.5 Input path note

Even with a locked tree, **SendInput / pyautogui** still delivers keystrokes and clicks to the focused HWND. PostMessage to child HWNDs does not reliably reach Electron renderers. Orynn correctly uses physical input for OCR/grid fallbacks and keyboard shortcuts.

---

## 2. Orynn `electron_unlock` — Implementation

### 2.1 Architecture overview

```
Agent: uia_find miss
    → electron_hint_for_app() / _electron_unlock_hint()
    → electron_check(exe)
    → electron_unlock(exe)
         ├─ count_app_controls >= 40 → skip (already unlocked)
         └─ relaunch_with_accessibility(exe, args, also_remote_debug=False)
              → subprocess.Popen([exe, ...args, "--force-renderer-accessibility"])
    → retry uia_find / uia_click / uia_type
```

### 2.2 Detection — `is_electron_app()`

Location: `desktop_features.py` (~L1160).

Heuristics (any match → Electron/CEF shell):

1. **Known exe basename** in `ELECTRON_EXES` set (`code.exe`, `cursor.exe`, `discord.exe`, `slack.exe`, `notion.exe`, `spotify.exe`, `obsidian.exe`, `figma.exe`, `teams.exe`, `ms-teams.exe`, `github desktop.exe`, etc.).
2. **`resources/app.asar`** adjacent to exe (classic Electron packaging).
3. **`chrome_100_percent.pak`** adjacent (Chromium content bundle — catches CEF apps like Spotify).

**Note:** Spotify is **CEF-native**, not Electron, but shares the same accessibility unlock behavior; Orynn groups it correctly for unlock purposes.

### 2.3 Name resolution — `resolve_app_exe()`

Agents pass friendly names (`"Discord"`, `"VS Code"`). Resolver:

1. Returns path unchanged if it already exists on disk.
2. Scans visible windows for exact exe basename match.
3. Falls back to window title containing the app stem.

This avoids requiring full install paths in agent prompts.

### 2.4 Richness gate — `count_app_controls()`

Before relaunch, `electron_unlock` in `tools.py` counts UIA nodes under the app window (cap 60, depth-limited). If **≥ 40**, unlock is skipped:

```python
if count_app_controls(app_name, cap=60) >= 40:
    return "already exposes a rich UIA tree (no relaunch needed)"
```

Rationale: Discord and some apps already expose trees (user ran with flag, or AT is active). Relaunching wastes ~15s and disrupts the user.

### 2.5 Relaunch — `relaunch_with_accessibility()`

```python
cmd = [exe_path] + list(args or []) + ["--force-renderer-accessibility"]
if also_remote_debug:
    cmd.append("--remote-debugging-port=9222")
proc = subprocess.Popen(cmd, close_fds=True)
```

**Critical behaviors:**

- **Does NOT kill** the existing instance. Electron single-instance locks mean the new process may exit immediately; user must close the running copy first.
- **`also_remote_debug`** is implemented but **not used** by default `electron_unlock` — CDP is opt-in only.
- Explicitly **no DLL injection** (AV/anti-cheat/maintenance).

### 2.6 Agent integration

| Component | Role |
|-----------|------|
| `electron_check` | Returns `is_electron` for resolved exe |
| `electron_unlock` | Relaunch with flag or skip if rich tree |
| `electron_hint_for_app` | Appended to `uia_find` miss messages |
| `smart_uia_find_with_unlock` | Adds `electron_hint` on Electron foreground |
| `survey_app_controls` | Control "menu" for agent after focus |
| Agent prompt (`agent.py`) | UIA-first; unlock on Electron miss; **never drive Cursor/Chrome/Edge** |

### 2.7 Known gaps (from parent research)

1. **No kill-and-relaunch** — single-instance apps block unlock.
2. **No session-wide FocusChanged subscription** — would reduce relaunch need.
3. **Flag may need `=complete`** on newest Chromium.
4. **`github desktop.exe` in ELECTRON_EXES** — actual binary is `GitHubDesktop.exe`; title/exe scan still resolves via heuristics #2/#3.

---

## 3. Major Apps — Web vs Desktop Strategy

Legend:

| Strategy | Meaning |
|----------|---------|
| **Desktop UIA** | `focus_window` → `electron_unlock` if needed → `uia_*` |
| **Web CDP** | Playwright/connector in Chrome/Edge against web URL |
| **URI deep link** | `start slack:`, `spotify:`, `msteams:` — navigation without UI |
| **Keyboard** | Shortcuts via `key_combo` / `keyboard_type` when tree partial |
| **Vision/OCR** | Canvas/custom surfaces where DOM ≠ pixels |
| **Local/API** | File system, COM, REST — bypass UI entirely |

### 3.1 Summary matrix

| App | Shell | Exe (typical) | Default for Orynn | Web alternative | Notes |
|-----|-------|---------------|-------------------|-----------------|-------|
| **VS Code** | Electron | `Code.exe` | **Desktop UIA** (+ unlock) | Web vscode.dev (limited) | Extension host, terminal, git need desktop. Connectors: `vscode` auth_kind `app`. |
| **Cursor** | Electron (VS Code fork) | `Cursor.exe` | **Blocked** — agent must not drive | — | Same unlock mechanics; Orynn safety rule excludes self-automation. |
| **Discord** | Electron | `Discord.exe` | **Web CDP** for read-heavy; **Desktop UIA** for voice/presence | `discord.com/app` connector | `discord:` URI for deep links. Often already unlocked (rich tree). |
| **Slack** | Electron | `slack.exe` | **Web CDP** (connector default) | `app.slack.com` | `slack:` URI. Desktop for notifications/huddle. |
| **Spotify** | **CEF** (native + embedded Chromium) | `Spotify.exe` | **URI + keyboard** > UIA | `open.spotify.com` connector | Not Electron; same a11y flag works. Media keys via OS. |
| **Notion** | Electron | `Notion.exe` | **Web CDP** | `notion.so` connector | Desktop = web wrapper; offline cache only on desktop. |
| **Teams** | **WebView2** (new client) | `ms-teams.exe` | **Web CDP** or **Desktop UIA** | `teams.microsoft.com` | Classic Teams was Electron; new client uses evergreen Edge WebView2 ([MS blog](https://techcommunity.microsoft.com/blog/microsoftteamsblog/microsoft-teams-advantages-of-the-new-architecture/3775704)). `msteams:` URI. |
| **Figma** | Electron | `Figma.exe` | **Web CDP** (inspect/read) | `figma.com` connector | **Canvas is GPU/custom** — UIA sparse even unlocked. CDP port blocked in 126.1.2+; pipe transport workarounds exist. |
| **Obsidian** | Electron | `Obsidian.exe` | **Local/API** (vault files) | — | `.md` files on disk; UI automation secondary. Plugin API needs desktop. |
| **GitHub Desktop** | Electron | `GitHubDesktop.exe` | **Desktop UIA** (+ unlock) | `github.com` for PRs/issues | Git operations local; connector uses web for notifications. |

### 3.2 Per-app detail

#### VS Code (`Code.exe`)

- **Stack:** Electron + Monaco editor + extension host + integrated terminal (native PTY).
- **Desktop when:** Running tests, terminal commands, multi-root workspaces, extensions, local git.
- **Web when:** Quick file edit on github.dev / vscode.dev — no extension host parity.
- **Automation:** Unlock → UIA for menus, sidebar, settings. Terminal buffer is partial in UIA — prefer `run_command` in integrated terminal via keyboard (`Ctrl+`` ` focus) or extension APIs for heavy tasks.
- **Orynn connector:** `vscode`, `default_mode: coding`.

#### Cursor (`Cursor.exe`)

- **Stack:** Electron fork of VS Code; AI features in renderer.
- **Automation:** Technically identical unlock path; **Orynn agent prompt forbids driving Cursor** (infinite loop / safety).
- **Strategy:** User tasks in Cursor are out of scope for Orynn desktop agent; use VS Code connector or project tools instead.

#### Discord (`Discord.exe`)

- **Stack:** Electron; heavy voice/video (native modules).
- **Desktop when:** Voice channels, push-to-talk, overlay, rich presence.
- **Web when:** Reading messages, summarizing channels (connector template).
- **Automation:** Tree often rich without unlock on some builds; Orynn skips relaunch when count ≥ 40. Channel list and message area unlock reliably with flag.
- **URI:** `discord://`-/`discord:` deep links to servers/channels.

#### Slack (`slack.exe`)

- **Stack:** Electron.
- **Desktop when:** Huddles, notifications, multiple workspaces.
- **Web when:** Unread summaries, search (Orynn connector default).
- **Automation:** Unlock + UIA for sidebar channels, message input (`uia_type` + `submit=true`). Prefer web connector for triage at scale.

#### Spotify (`Spotify.exe`)

- **Stack:** **Native C++ container + CEF** for React UI ([Spotify Engineering 2021](https://engineering.atspotify.com/2021/4/building-the-future-of-our-desktop-apps)). **Not Electron.**
- **Desktop when:** Offline downloads, local files, device picker.
- **Web when:** Search/play via connector (`open.spotify.com`).
- **Automation:** `--force-renderer-accessibility` applies to CEF renderer. **`spotify:` URI** for play/search intents. Global media keys via keyboard. UIA for in-app search/play; API/URI preferred for reliability.

#### Notion (`Notion.exe`)

- **Stack:** Electron wrapper around web app.
- **Desktop when:** Offline pages, OS integrations.
- **Web when:** Search, read, summarize (connector default).
- **Automation:** Unlock exposes sidebar and blocks; nested blocks/toggles can produce deep trees — use `survey_app_controls` first. Web Playwright often simpler for read-only.

#### Microsoft Teams (`ms-teams.exe`)

- **Stack:** **WebView2** (Chromium via evergreen Edge runtime), not Electron since "new Teams" ([Learn: Teams updates](https://learn.microsoft.com/en-us/microsoftteams/platform/resources/teams-updates)).
- **Desktop when:** Calls, meetings, OS calendar integration.
- **Web when:** Chat triage (connector).
- **Automation:** Same Chromium a11y flag on `ms-teams.exe` if launched from shortcut with modified target. WebView2 UIA support improved in enterprise tools (UiPath WebView2 native automation). **`msteams:` URI** for meeting join. Expect occasional orphaned WebView2 HWND issues.

#### Figma (`Figma.exe`)

- **Stack:** Electron (~v39.x per Desktop Insights).
- **Desktop when:** Offline cache, OS file drag-drop, plugin dev.
- **Web when:** Read frames, design tokens (connector); **Figma MCP** for read.
- **Automation:** **Canvas drawing surface is not fully represented in UIA** even when unlocked — use web CDP/read APIs for structure, vision/grid for pixel-precise canvas clicks. **`--remote-debugging-port` disabled in 126.1.2+**; `--remote-debugging-pipe` workaround for CDP automation tools.

#### Obsidian (`Obsidian.exe`)

- **Stack:** Electron; vault = plain `.md` on disk.
- **Desktop when:** Plugins, graph view, daily notes.
- **Web when:** N/A (no official web app).
- **Automation:** **Prefer file-system operations** on vault path over UI. Unlock + UIA for settings, command palette (`Ctrl+P`). Plugin/community API for advanced automation.

#### GitHub Desktop (`GitHubDesktop.exe`)

- **Stack:** Electron + TypeScript/React ([desktop/desktop](https://github.com/desktop/desktop)).
- **Desktop when:** Clone, commit, push, branch operations local.
- **Web when:** PR review, issues, notifications (GitHub connector).
- **Automation:** Unlock + UIA for repo list, commit summary field, "Commit to main" button. Git CLI via `run_command` often beats UI for batch git.

---

## 4. CDP / DevTools Protocol vs UIA

### 4.1 What CDP provides

Chrome DevTools Protocol exposes:

- DOM queries (`DOM.querySelector`, `DOM.getDocument`)
- Input synthesis (`Input.dispatchMouseEvent`, `Input.insertText`)
- Accessibility tree (`Accessibility.getFullAXTree`, `Accessibility.queryAXTree`)
- Network, console, screenshots

Playwright and Puppeteer speak CDP to Chromium. Electron apps can expose CDP when launched with `--remote-debugging-port=9222` or `--remote-debugging-pipe`.

### 4.2 Comparison

| Dimension | UIA (Orynn default) | CDP |
|-----------|---------------------|-----|
| **Scope** | Any Windows app with providers | Chromium surfaces only |
| **Setup** | Unlock flag or AT wake | Debug port/pipe; may be disabled (Figma 126+) |
| **Security** | OS accessibility API | Opens debugger attack surface; some apps block in prod |
| **Stability across upgrades** | Flag stable; tree shape varies | Ports/flags break (Electron #41325, Figma 126+) |
| **Semantic model** | OS roles + names (screen-reader oriented) | DOM + AX tree (web-oriented) |
| **Input** | Real SendInput via control bounds | Synthetic DOM events (some apps detect) |
| **Multi-app** | One stack for Notepad + Discord + Excel | Separate session per Chromium app |
| **Agent integration** | Already in Orynn tools | Would need Playwright sidecar |
| **Canvas / WebGL** | Poor | Still poor for pixels; DOM side channels only |
| **Performance** | Tree walk cost; cache helps | Fast DOM queries; no cross-process UIA hop |

### 4.3 When to prefer UIA

- Unified desktop agent across **Win32 + Electron + Office** without per-app debug ports.
- Consumer product: no debugger port, no injection.
- Live/voice path: `uia_click` by name is explainable and overlay-friendly.
- After `--force-renderer-accessibility`, UIA names match visible labels agents already use.

### 4.4 When to prefer CDP / Playwright

- **Web SaaS connectors** (Gmail, Slack web, Notion web) — Orynn parent doc recommends Playwright over screenshot `computer_use`.
- **DOM-stable workflows** (form fill, scrape, test assertions).
- **Electron main process** debugging or extension development.
- Read-heavy Figma/Notion where desktop UIA tree is huge or canvas-empty.

### 4.5 Hybrid strategy (recommended for Orynn)

```
Classify target
├─ SaaS with web connector     → Playwright/CDP in Edge
├─ Electron/CEF desktop task   → electron_unlock → UIA
├─ Canvas/custom (Figma draw)  → Web read API / MCP + vision fallback
├─ File-local (Obsidian vault) → Filesystem API
└─ System integration          → URI / keyboard / COM
```

Orynn already implements the Electron branch; gap is **Playwright for `auth_kind: browser` connectors** instead of vision browser mode.

---

## 5. CEF vs WebView2 vs Electron

All three embed Chromium. Automation implications differ by **packaging, process model, and who ships the runtime**.

### 5.1 Electron

| Aspect | Detail |
|--------|--------|
| **What ships** | Full Chromium + Node.js bundled per app |
| **Examples** | VS Code, Discord, Slack, Notion, Obsidian, GitHub Desktop, Figma, Cursor |
| **Exe layout** | `resources/app.asar`, `chrome_*.pak` |
| **UIA unlock** | `--force-renderer-accessibility` on exe |
| **CDP** | `--remote-debugging-port` / `--remote-debugging-pipe` (app-dependent) |
| **Single-instance** | Common — relaunch must close old process |
| **Automation maturity** | Highest; Orynn `ELECTRON_EXES` tuned for this |

### 5.2 CEF (Chromium Embedded Framework)

| Aspect | Detail |
|--------|--------|
| **What ships** | App embeds CEF library; **no Node.js** |
| **Examples** | **Spotify desktop**, some game launchers, legacy embedded browsers |
| **Process model** | Browser UI in app process or child; app controls CEF init flags |
| **UIA unlock** | Same Chromium flag via ` CefSettings.command_line_args_disabled` / append switch |
| **Embedding gotcha** | Offscreen/windowless CEF may expose **no HWND-attached tree** until `SetAsChild` attaches browser HWND ([CefSharp #3173](https://github.com/cefsharp/CefSharp/pull/2495)) |
| **Input** | CEF can dispatch "real" browser events via `SendMouse*` / `SendKey*` — richer than WebView2 for embedded automation |
| **Orynn detection** | `chrome_100_percent.pak` heuristic; listed in unlock path via `is_electron_app` |

### 5.3 WebView2

| Aspect | Detail |
|--------|--------|
| **What ships** | Shared **Evergreen Edge WebView2 runtime** (system component) |
| **Examples** | **New Microsoft Teams**, Outlook hybrid views, Windows widgets, many enterprise apps |
| **Process model** | Renderer often **separate process** shared across apps using Edge runtime |
| **UIA unlock** | Same Chromium flags on host exe; plus **WebView2-specific automation** in enterprise RPA (UiPath "WebView2 Native Automation") |
| **CDP** | `CoreWebView2.OpenDevToolsWindow`; debugging via `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` env var |
| **Input** | **No first-class input simulation API** — rely on UIA + SendInput or JS injection via `ExecuteScript` |
| **Orphan HWND** | Detached WebView2 windows reported in RPA tools — may need HWND-specific targeting |

### 5.4 Decision table for automation authors

| If the app is… | Detect by… | Unlock by… | Prefer… |
|----------------|------------|------------|---------|
| Electron | `app.asar`, known exe | `--force-renderer-accessibility` | UIA after unlock |
| CEF-native | `chrome_*.pak`, no `app.asar` | Same flag on exe | UIA; URI/API if available |
| WebView2 | `msedgewebview2.exe` child process, WebView2 loader DLL | Flag on host + env `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` | UIA; enterprise WebView2 selectors if available |
| Pure browser tab | `chrome.exe` / `msedge.exe` | CDP / Playwright | Never desktop UIA for page content |

---

## 6. Recommendations for Orynn

### Immediate

1. **Upgrade flag** to `--force-renderer-accessibility=complete` when bare flag fails on Chrome 117+.
2. **Optional `force=true`** on `electron_unlock` to `taskkill` + relaunch (user-approved) for single-instance apps.
3. **Session FocusChanged subscription** at agent start to wake Chromium without relaunch.
4. **Fix `ELECTRON_EXES` entry** → `githubdesktop.exe` (match actual binary).
5. **Classify Spotify/Teams** in agent hints: CEF vs WebView2 (unlock same, expectations differ).

### Medium term

6. **Playwright driver** for browser connectors (Slack, Notion, Gmail, Figma web).
7. **Per-app routing table** injected into agent prompt from exe sniff (Electron vs CEF vs WebView2 vs native).
8. **CDP sidecar** (opt-in) for power users who accept `--remote-debugging-port=9222`.

### Per-app defaults (Orynn routing)

| User intent | Route |
|-------------|-------|
| "Summarize Slack" | Connector → web |
| "Join Teams meeting" | `msteams:` URI or desktop UIA |
| "Commit in GitHub Desktop" | Desktop UIA + unlock |
| "Edit notes" | Obsidian vault filesystem |
| "Play song on Spotify" | `spotify:` URI or web connector |
| "Click Figma canvas tool" | Vision/grid — not UIA |
| "Run tests in VS Code" | Desktop UIA + terminal keyboard |

---

## 7. Sources

| Topic | URL |
|-------|-----|
| Chromium accessibility overview | https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md |
| Chromium AT detection design | https://www.chromium.org/developers/design-documents/accessibility/ |
| Chromium inspect / force a11y | https://chromium.googlesource.com/chromium/src/+/HEAD/tools/accessibility/inspect/README.md |
| Microsoft Teams WebView2 architecture | https://techcommunity.microsoft.com/blog/microsoftteamsblog/microsoft-teams-advantages-of-the-new-architecture/3775704 |
| Teams client updates | https://learn.microsoft.com/en-us/microsoftteams/platform/resources/teams-updates |
| Spotify CEF architecture | https://engineering.atspotify.com/2021/4/building-the-future-of-our-desktop-apps |
| GitHub Desktop (Electron) | https://github.com/desktop/desktop |
| CefSharp UIA / force-renderer-accessibility | https://github.com/cefsharp/CefSharp/pull/2495 |
| CefSharp vs WebView2 automation | https://stackoverflow.com/questions/70360189/cefsharp-vs-webview2 |
| UiPath WebView2 / Chromium embedded | https://docs.uipath.com/activities/other/latest/ui-automation/release-notes-uipath-uiautomation-activities-v23-4 |
| Figma CDP port regression | https://forum.figma.com/report-a-problem-6/remote-debugging-port-not-working-in-figma-desktop-126-1-2-50858 |
| Orynn parent research | `docs/windows-automation-research.md` |

---

*Document 06 in the Windows automation research series. Verify behavior on target Windows 11 builds — Chromium and app auto-update cadences change unlock and CDP semantics without notice.*
