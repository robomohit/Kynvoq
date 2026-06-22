# Proposal 03: `open_settings` Tool

**Storm workstream:** proposals/03  
**Status:** Draft — implementation-ready  
**Date:** 2026-06-22  
**Author:** subagent-storm (from ms-settings research)  
**Primary sources:**
- [02-uris-protocols-shell.md](../../windows-automation-research/02-uris-protocols-shell.md)
- [03-universal-launch.md](../../windows-automation-research/03-universal-launch.md)
- [07-app-framework-taxonomy.md](../../windows-automation-research/07-app-framework-taxonomy.md) §5.3
- [windows-automation-research.md](../../windows-automation-research.md) §5–8

**Related proposals:** [01-resolve-launch-target.md](./01-resolve-launch-target.md) (universal launch lane), [06-playbook-wiring.md](./06-playbook-wiring.md) (Settings UIA after open)

---

## 1. Problem

Windows Settings is a **WinUI 3 / UWP host** (`ApplicationFrameHost.exe`) with 265+ documented `ms-settings:` slugs on Win11 build 26200. The correct automation pattern is **deep-link first, UIA second** — never click through the Settings home tree or Start-menu search.

Orynn today has a partial implementation:

| Surface | What works | Gap |
|---------|------------|-----|
| Voice fast-path | `"settings"` → `start ms-settings:` via `_KNOWN_LAUNCH_APPS` | No deep links (`bluetooth`, `display`, `privacy-microphone`, …) |
| Back-office agent | `run_command {"command": "start ms-settings:…"}` | Model must invent slug syntax; no validation, aliases, or structured errors |
| Live orchestrator | Prompt says use `run_command start ms-settings:` | Same fragility; no first-class tool in Gemini Live tool list |
| Canary | `adaptive_windows_canary.py` uses raw `explorer.exe ms-settings:` | Ad-hoc; not exposed to agents |

**Observed failure modes** (from research + GOLDEN_FIVE):

1. **Wrong launch primitive** — `Start-Process ms-settings:display` without `-UseShellExecute`, or `Invoke-Item` (PowerShell parses `ms-settings` as a drive). Launch silently fails or opens wrong handler.
2. **Manual navigation** — Agent opens Settings home, then UIA-clicks left nav. Slow, flaky on sparse trees, and unnecessary when a stable URI exists.
3. **Slug guessing** — Model invents nonexistent pages (`ms-settings:wifi` vs correct `ms-settings:network-wifi`).
4. **Premature `done`** — Planner path reported success before Settings window painted (resolved for generic `"open settings"` via `open_known_app`, but not for deep links).
5. **Prompt contradiction (historical)** — Desktop hardening once forbade protocol links while Settings requires `ms-settings:`; fast-path bypasses planner but deep-link requests still hit the agent.

Research explicitly lists **“No ms-settings catalog in tools”** as a top gap and recommends **`open_settings(uri_suffix)`** as immediate high-ROI work.

---

## 2. Goal

Add a **deterministic, catalog-backed** `open_settings` tool that:

1. Launches any curated Settings page via the correct ShellExecute path.
2. Resolves spoken / natural-language intents to stable slugs (aliases).
3. **Verifies** success with `wait_for_window("Settings")` — same contract as `open_known_app`.
4. Returns structured output (URI opened, human label, optional nav hint for follow-up UIA).
5. Works in **back-office agent**, **Live** (when desktop control enabled), and optionally extends the **voice fast-path** without bloating `_KNOWN_LAUNCH_APPS` logic into the tool itself.

**Non-goals for v1:**

- Toggle Bluetooth/Wi‑Fi/microphone **state** via registry or service APIs (use URI to open page; user or UIA acts on toggle).
- Runtime enumeration of all 265 slugs from `SystemSettings.dll` (defer to v2 `list_settings_pages`).
- Replacing `open_uri` / `launch_aumid` (separate tools; see proposal 01).
- UIA navigation inside Settings (remains `uia_click` / `uia_type` after open).

---

## 3. Design

### 3.1 Tool contract

```python
# ActionType.open_settings = "open_settings"  (new enum value)

open_settings: {
    "page": str,           # slug after "ms-settings:" — "" or omitted = home
    "query": str | null,   # optional ?key=value (defaultapps deep links)
    "wait": bool,          # default true — wait_for_window before returning
    "timeout": float       # default 12.0
} -> ToolResult
```

**Examples:**

| Agent call | Resolved URI | User intent |
|------------|--------------|-------------|
| `{"page": ""}` | `ms-settings:` | Open Settings |
| `{"page": "bluetooth"}` | `ms-settings:bluetooth` | Bluetooth devices |
| `{"page": "privacy-microphone"}` | `ms-settings:privacy-microphone` | Microphone privacy |
| `{"page": "defaultapps", "query": "registeredAUMID=..."}` | `ms-settings:defaultapps?registeredAUMID=...` | Default app for AUMID |

**Success output (structured in `ToolResult.output` JSON or key lines):**

```
Opened Settings → Bluetooth (ms-settings:bluetooth)
Window: Settings (verified)
Hint: Use uia_find on toggle names from adaptive_observe; do not navigate from home.
```

**Failure output:**

```
Unknown settings page: "wifi". Did you mean "network-wifi"? Aliases: wifi, wi-fi → network-wifi
```

### 3.2 Launch implementation

Use the research-validated pattern only:

```python
def _shell_execute_uri(uri: str) -> None:
    subprocess.run(
        ["cmd", "/c", "start", "", uri],
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
```

**Do not** use bare `Start-Process`, `Invoke-Item`, or `subprocess.run(..., shell=True)` with unquoted URIs.

Alternative used in canary (`explorer.exe ms-settings:about`) is acceptable but **prefer `cmd /c start`** for consistency with `_KNOWN_LAUNCH_APPS` and `run_command` GUI detection.

After launch:

```python
self.wait_for_window("Settings", timeout=timeout, paint_seconds=0.3)
```

Settings is **not** single-instance — multiple pages may share one frame; focus existing Settings HWND if already open, then navigate via URI (Windows replaces in-app route).

### 3.3 Slug catalog and aliases

Ship a static module `app/settings_pages.py` (or JSON under `static/`) derived from the curated catalog in `02-uris-protocols-shell.md` (~40 pages, grouped):

| Category | Example slugs | Example aliases |
|----------|---------------|-----------------|
| System & display | `display`, `nightlight`, `powersleep`, `about` | `screen`, `brightness` → `display` |
| Sound | `sound`, `apps-volume` | `volume`, `audio` → `sound` |
| Network | `network-wifi`, `network`, `network-vpn` | `wifi`, `wi-fi` → `network-wifi` |
| Bluetooth & devices | `bluetooth`, `printers`, `mousetouchpad` | `bluetooth settings` → `bluetooth` |
| Privacy | `privacy-microphone`, `privacy-webcam`, `privacy-location` | `microphone`, `camera privacy` |
| Apps | `appsfeatures`, `defaultapps`, `startupapps`, `optionalfeatures` | `installed apps`, `startup` |
| Personalization | `personalization-background`, `taskbar`, `themes` | `wallpaper`, `background` |
| Update & recovery | `windowsupdate`, `recovery`, `troubleshoot` | `updates` → `windowsupdate` |
| Accounts | `yourinfo`, `signinoptions`, `otherusers` | `sign in`, `pin` → `signinoptions` |

**Resolution order:**

1. Normalize input: lowercase, strip `ms-settings:` prefix if model passed full URI, collapse whitespace/hyphens.
2. Exact slug match against catalog keys.
3. Alias table lookup.
4. Fuzzy suggest (Levenshtein or prefix match) — return error with suggestions, **do not** launch unknown slugs.

**Query strings:** Allow only on slugs that Microsoft documents with parameters (`defaultapps`, `appsfeatures-app`, `camera?cameraId=`). Validate `query` against an allowlist regex `^[a-zA-Z0-9_\-\.%=&]+$`.

### 3.4 Relationship to other launch mechanisms

```
User intent: "open Bluetooth settings"
        │
        ├─ Voice pure launch ("open bluetooth settings", no extra steps)
        │     └─ detect_app_launch_intent → _KNOWN_LAUNCH_APPS alias (proposal 01 addition)
        │           OR open_settings("bluetooth") if fast-path delegates to tool
        │
        ├─ Live / back-office agent
        │     └─ open_settings {"page": "bluetooth"}
        │
        └─ resolve_launch_target("bluetooth settings")  [proposal 01]
              └─ classifies as settings → calls open_settings internally
```

Keep **`open_settings` as the single implementation** for URI construction + verification; avoid duplicating slug logic in `_KNOWN_LAUNCH_APPS`, `run_command` prompts, and a future `open_uri` tool.

### 3.5 Safety and permissions

| Concern | Policy |
|---------|--------|
| Consent | **None** — opening Settings is low-risk (same as `run_command start ms-settings:*`) |
| Shell access | No arbitrary command; only whitelisted slugs → fixed URI template |
| Enterprise GP | Some pages hidden by policy; `wait_for_window` may succeed while target page shows “ unavailable” — agent should `adaptive_observe` and report honestly |
| Destructive toggles | Opening privacy/update pages is not destructive; **changing** toggles still follows existing UIA consent rules |

Register in `permissions.py` / `safety.py` as **low** danger, not in `_SHELL_ACTIONS` (no free-form shell).

---

## 4. Integration points

### 4.1 Files to modify (implementation phase)

| File | Change |
|------|--------|
| `app/models.py` | Add `ActionType.open_settings` |
| `app/settings_pages.py` | **New** — catalog, aliases, `resolve_settings_page(name) -> str` |
| `app/tools.py` | `ToolExecutor.open_settings(...)`; wire in `run_action` dispatch |
| `app/tool_registry.py` | Description + pack membership (`terminal` or new `desktop` pack) |
| `app/agent.py` | Prompt: prefer `open_settings` over `run_command` for Settings; inject catalog summary or “call with page slug” |
| `app/widget/textbox_overlay.py` | Live tool schema if Live exposes desktop tools; update `_DESKTOP_HARDENING` step 1 |
| `tests/test_open_settings.py` | **New** — slug resolution, URI build, mock launch |
| `tests/test_voice_and_env.py` | Optional: deep-link voice aliases if added to fast-path |
| `scripts/adaptive_windows_canary.py` | Switch to `tools.open_settings("about")` for consistency |

### 4.2 Agent prompt snippet (back-office)

Replace verbose `run_command` guidance for Settings with:

> To open a Windows Settings page, use `open_settings {"page": "<slug>"}`. Do **not** click through Settings home or use Start search. Common pages: `bluetooth`, `display`, `sound`, `network-wifi`, `privacy-microphone`, `windowsupdate`, `appsfeatures`. After open, use `focus_window` / `uia_find` on the target control.

### 4.3 Live orchestrator

Add to Live desktop tool allowlist (alongside `run_command`, `focus_window`, `uia_*`):

- `open_settings` — faster than spawning `start_desktop_task` for “open X settings” goals.
- Aligns with master strategy: *“Turn on Bluetooth → ms-settings:bluetooth OR expand launch registry; NOT UIA tree-walk from home.”*

### 4.4 Voice fast-path (optional, same PR or follow-up)

Research recommends adding to `_KNOWN_LAUNCH_APPS` without compound parsing:

```python
"bluetooth settings": ("start ms-settings:bluetooth", "Settings"),
"display settings": ("start ms-settings:display", "Settings"),
# ...
```

**Prefer:** fast-path entries call shared `resolve_settings_page` so slug strings are not duplicated. `detect_app_launch_intent` still **rejects** compounds like `"open settings and turn on bluetooth"` (`_LAUNCH_EXTRA_RE`).

---

## 5. Implementation plan

### Phase 1 — Core tool (MVP, ~1 day)

1. Add `settings_pages.py` with curated catalog + aliases from research doc §1.
2. Implement `ToolExecutor.open_settings` with `_shell_execute_uri` + `wait_for_window`.
3. Register action type, tool description, dispatch in `run_action`.
4. Unit tests: resolution, unknown slug errors, URI with query sanitization.
5. Manual canary: `open_settings("about")`, `open_settings("bluetooth")` on Win11 desktop.

### Phase 2 — Agent + Live wiring (~0.5 day)

1. Update `agent.py` desktop prompt and `textbox_overlay.py` hardening text.
2. Expose tool to Gemini Live function declarations if desktop pack is enabled.
3. Extend `adaptive_windows_canary.run_settings_canary` to use the tool.

### Phase 3 — Voice + resolver integration (~0.5 day)

1. Wire `resolve_launch_target` (proposal 01) to delegate settings intents to `open_settings`.
2. Add top ~10 spoken aliases to voice fast-path via shared resolver.
3. GOLDEN_FIVE script: add `"open bluetooth settings"`, `"open display settings"` reps.

### Phase 4 — Discovery (defer)

- `list_settings_pages`: read-only tool returning catalog groups for agent self-help.
- Optional machine-specific slug scan (`SystemSettings.dll` regex) cached at session start — 265 entries, many conditional; use for diagnostics only.

---

## 6. Test plan

| Test | Type | Pass criteria |
|------|------|---------------|
| `resolve_settings_page("wi-fi")` → `network-wifi` | Unit | Alias map |
| `resolve_settings_page("not-a-page")` | Unit | Error with suggestion |
| `open_settings("bluetooth")` | Manual / canary | Settings window visible ≤12s |
| `open_settings("")` vs existing fast-path | Integration | Same behavior as `"settings"` voice command |
| Agent uses `open_settings` not `run_command` for “open microphone privacy” | E2E task | Task JSON shows `open_settings`; no Start-menu search steps |
| Unknown slug on older Win10 | Manual | Window opens; page may differ — observe + honest finish |

**Regression:** Existing `tests/test_fast_path.py::test_open_app_uses_deterministic_fast_path_no_llm` for bare `"open settings"` must remain 10/10.

---

## 7. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Slug missing on older Windows builds | Catalog marks conditional pages; return warning in ToolResult; agent falls back to Settings search UIA |
| Model passes full URI in `page` | Strip `ms-settings:` prefix in normalizer |
| Duplicate Settings windows | Not single-instance; URI navigation updates in-place — document in tool output |
| Catalog drift on Windows updates | Periodic re-scan doc task; v2 optional DLL enumeration |
| Overlap with proposal 01 | `open_settings` is the settings-specific backend; 01 routes to it |

---

## 8. Success metrics

- **Golden Five:** `"open bluetooth settings"` and `"open display settings"` at 10/10 with deterministic path, ≤3s, verified window.
- **Task forensics:** Settings open tasks drop from multi-step UIA nav to 1× `open_settings` + act steps.
- **Agent token savings:** Remove repeated `run_command` + `wait_for_window` boilerplate from planner traces.

---

## 9. Appendix — Curated slug reference (v1 ship list)

Copy from research; implement as data, not prompt prose.

**System:** `about`, `display`, `nightlight`, `powersleep`, `clipboard`, `multitasking`, `quiethours`  
**Sound:** `sound`, `sound-devices`, `apps-volume`  
**Storage:** `storagesense`, `disksandvolumes`  
**Network:** `network-status`, `network-wifi`, `network`, `network-vpn`, `network-mobilehotspot`, `network-proxy`  
**Devices:** `bluetooth`, `connecteddevices`, `printers`, `mousetouchpad`, `typing`  
**Apps:** `appsfeatures`, `defaultapps`, `startupapps`, `optionalfeatures`, `developers`  
**Personalization:** `personalization-background`, `taskbar`, `themes`, `lockscreen`  
**Privacy:** `privacy`, `privacy-microphone`, `privacy-webcam`, `privacy-location`, `privacy-notifications`, `windowsdefender`, `signinoptions`  
**Update:** `windowsupdate`, `windowsupdate-optionalupdates`, `recovery`, `troubleshoot`  
**Accounts:** `yourinfo`, `otherusers`, `sync`  
**Accessibility:** `easeofaccess-display`, `easeofaccess-narrator`, `easeofaccess-keyboard`  
**Time & language:** `dateandtime`, `regionlanguage`, `speech`

**Launch command template:** `cmd /c start "" "ms-settings:{slug}"` (+ optional `?{query}`)

---

## 10. References

- Microsoft: [Launch Windows Settings](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings)
- Research: `docs/windows-automation-research/02-uris-protocols-shell.md` §1, §6–7
- Research: `docs/windows-automation-research/03-universal-launch.md` §8.1, §10.2
- Orynn canary: `scripts/adaptive_windows_canary.py` (`run_settings_canary`)
- Orynn fast-path: `app/tools.py` `_KNOWN_LAUNCH_APPS`, `open_known_app`
- Benchmark: `GOLDEN_FIVE.md` — `"open settings"` 10/10 via deterministic path
