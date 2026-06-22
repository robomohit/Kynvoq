# Proposal 07 — Playwright Connector Driver

**Status:** Draft (subagent-storm)  
**Priority:** P1 — Scale surfaces  
**Scope:** `auth_kind: browser` connectors only  
**Related research:** [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md) §4.4, [06-electron-chromium.md](../../windows-automation-research/06-electron-chromium.md) §4.5, [windows-automation-research.md](../../windows-automation-research.md) §3.8 / §8  
**Related code:** `app/connectors.py`, `app/agent.py`, `app/background_browser.py`, `app/plugins/browser_plugin.py`, `app/mcp_browser.py`, `app/tool_registry.py`

---

## 1. Summary

Orynn already ships Playwright (`BackgroundBrowser`, `browser_plugin`, `computer_use` mode). Every `auth_kind: browser` connector (Gmail, Slack, Notion, …) declares `default_mode: "computer_use"`, which *does* route to headless Playwright tools — not desktop vision. The gap is not “add Playwright”; it is **unify, authenticate, and route** browser connectors through a single persistent driver so connector tasks are fast, logged-in, and DOM-first instead of fragile coordinate loops or fresh anonymous sessions.

This proposal defines a **Playwright Connector Driver** — a thin product layer that:

1. Resolves connector → mode → URL → skill at spawn time.
2. Reuses a **persistent browser profile** (cookies / `storage_state`) per linked connector.
3. Consolidates the three existing Playwright stacks into one session manager.
4. Updates connector skills to teach **locator-first** workflows (`browser_accessibility_tree` → `browser_click` / `browser_type`), not screenshot coordinates.

---

## 2. Problem statement

### 2.1 What works today

| Piece | Location | Behavior |
|-------|----------|----------|
| Connector registry | `connectors.py` | 20+ `auth_kind: browser` entries with `task_template` + `default_mode: computer_use` |
| Headless browser mode | `agent.py` (`mode == "computer_use"`) | Starts `BackgroundBrowser`, sets `tools._background_mode`, exposes `browser_*` tool pack |
| Browser tools | `plugins/browser_plugin.py` | `browser_open`, `browser_click`, `browser_type`, `browser_accessibility_tree`, … |
| Connector skills | `CONNECTOR_SKILLS` | Per-surface manuals injected via `relevant_briefs(goal)` |
| Link consent | `workspace/connectors.json` | `link()` marks user consent; no OAuth yet |

`computer_use` is **already** Playwright-backed: the agent system prompt explicitly says “headless browser automation agent” and lists `browser_open` → `browser_get_text` → interact. GUI actions in `tools.run_action` route mouse/keyboard to `BackgroundBrowser` when `_background_mode` is set.

### 2.2 What is broken or missing

| Gap | Symptom | Impact |
|-----|---------|--------|
| **No persistent auth** | Fresh Chromium per task; no `user_data_dir` or `storage_state` | Gmail/Slack tasks hit login walls; skills say “user is already signed in” but browser is empty |
| **Three Playwright stacks** | `BackgroundBrowser`, `browser_plugin` globals, `MCPBrowserBridge` | Duplicate launch/teardown, zombie Chromium risk, inconsistent viewport/headless defaults |
| **Mode naming confusion** | `computer_use` sounds like Anthropic Computer Use (vision pixels) | Research docs repeatedly say “migrate to Playwright” — engineers re-litigate a solved routing problem |
| **Connector mode not enforced at spawn** | `default_mode` lives in registry; capsule uses `_detect_mode(goal)` heuristics | Dashboard/API may not pass connector `default_mode`; voice may pick `computer` for “check Gmail” |
| **Inconsistent per-connector routing** | `discord` → `default_mode: computer` (Electron UIA); others → `computer_use` | Correct for Discord desktop, but no central `resolve_connector_driver()` documents why |
| **Skills still desktop-flavored** | e.g. Spotify skill: “prefer UIA desktop app” while `default_mode` is `computer_use` | Agent gets conflicting L2 manuals |
| **No one-time login UX** | `link()` stores a boolean flag only | User links Gmail, task immediately fails at Google sign-in |
| **No CDP attach option** | Cannot reuse Edge/Chrome profile cookies | Power users expect “drive my logged-in browser” |

Research conclusion (repeated in three docs): *“Playwright/CDP beats screenshot `computer_use` on cost, speed, and reliability.”* In Orynn’s codebase that sentence is **half true** — DOM tools are wired, but **session persistence and spawn routing** are not.

---

## 3. Goals

1. **Linked browser connectors open authenticated** — or fail fast with a clear “sign in once” path.
2. **Single browser session manager** shared by `computer_use`, connector spawns, and optional headed debug.
3. **Deterministic spawn routing** — `connector_id` → `{mode, url, skill}` without goal-text guessing.
4. **Locator-first agent prompts** for all `auth_kind: browser` skills (align with `browser_plugin` + Playwright MCP guidance).
5. **Observable resolver path** — log `driver=playwright_connector`, `connector_id`, `profile_hit|miss`.

## 4. Non-goals (this proposal)

- OAuth / API token flows for Gmail, Slack, etc. (future `auth_kind: token`).
- Driving the user’s visible Chrome/Edge tab via desktop UIA (wrong layer).
- Electron CDP debug ports for desktop apps (separate power-user track in `06-electron-chromium.md`).
- Bundling Playwright Chromium in `Orynn.spec` (packaging stays on-demand per `PACKAGING.md`).
- Replacing `auth_kind: app` connectors (Excel, VS Code) — those stay UIA-first.

---

## 5. Proposed architecture

### 5.1 Connector driver resolution

Add `resolve_connector_task(connector_id: str, user_goal: str) -> ConnectorTask | None` in `connectors.py`:

```python
@dataclass
class ConnectorTask:
    connector_id: str
    mode: str              # "browser_connector" (new) or legacy "computer_use"
    start_url: str         # parsed from task_template / CONNECTOR_URLS table
    goal: str              # task_template + user_goal
    auth_kind: str
    skill_id: str
```

**Routing table** (initial):

| `auth_kind` | `default_mode` today | Proposed mode | Driver |
|-------------|---------------------|---------------|--------|
| `browser` | `computer_use` | `browser_connector` | Playwright persistent profile |
| `app` | `computer` / `coding` | unchanged | UIA / coding tools |
| `api` | `auto` | unchanged | single-shot API tools |
| `local` | `coding` / `auto` | unchanged | filesystem / clipboard |

`browser_connector` is an alias of today’s `computer_use` behavior **plus** profile injection. Keep `computer_use` as deprecated alias for one release to avoid breaking API clients.

### 5.2 Unified session manager — `PlaywrightSessionManager`

New module: `app/playwright_session.py`

Responsibilities:

- One **process-wide** Playwright instance (lazy start).
- **Profiles** under `workspace/browser-profiles/{connector_id}/` (`user_data_dir` per connector).
- Optional **shared profile** `workspace/browser-profiles/_default/` for connectors without isolation requirements.
- `get_context(connector_id, *, headed=False) -> BrowserContext` — create or reuse.
- `save_storage_state(connector_id)` on graceful shutdown / after login flow.
- `connect_over_cdp(url)` optional path for `ORYNN_BROWSER_CDP_URL` env (attach to user Chrome).

**Consolidation map:**

| Current | Fate |
|---------|------|
| `BackgroundBrowser` | Thin wrapper delegating to `PlaywrightSessionManager` |
| `browser_plugin._sessions` | Remove globals; call session manager with `session_id=connector_id` |
| `MCPBrowserBridge` | Defer; not on critical path for connectors |

### 5.3 Authentication model (free-tier realistic)

Phase 1 — **headed one-time login** (no OAuth):

1. User clicks **Link** on dashboard for `gmail`.
2. Backend runs `playwright_session.ensure_logged_in("gmail", start_url="https://mail.google.com")`:
   - If `storage_state.json` exists and `mail.google.com` loads inbox → linked.
   - Else launch **headed** Chromium (`headless=False`), open URL, emit SSE `browser_login_required` with instructions.
3. User completes Google login manually in the visible window.
4. Agent/tool calls `browser_save_session` (or auto-detect URL change) → persist `storage_state.json`.
5. Future tasks use headless context with that state.

Phase 2 — **CDP attach** (optional, env-gated):

- `ORYNN_BROWSER_CDP=http://127.0.0.1:9222` → `chromium.connect_over_cdp`.
- Document: user starts Edge with `--remote-debugging-port=9222` once.
- Skip profile dirs when CDP active.

Phase 3 — **token connectors** (out of scope here): GitHub PAT, Slack bot token → REST tools, not browser.

### 5.4 Spawn integration points

Wire `resolve_connector_task` at every connector entry:

| Entry point | File | Change |
|-------------|------|--------|
| Dashboard “Run connector” | `static/app.js` / task API | POST includes `connector_id`; server sets `mode` + prepends `task_template` |
| Capsule recipes | `widget/qt_shell.py` `CONNECTORS` | Replace duplicate list with import from `connectors.py` OR generate at build time |
| Voice → `start_desktop_task` | `gemini_live.py` | When goal matches linked connector keywords, pass `connector_id` in task envelope |
| Direct API | `main.py` `/api/tasks` | Accept optional `connector_id`; validate linked |

**Task JSON envelope** (handoff-friendly):

```json
{
  "goal": "Scan inbox…",
  "mode": "browser_connector",
  "connector_id": "gmail",
  "start_url": "https://mail.google.com",
  "driver": "playwright"
}
```

### 5.5 Agent prompt updates

For `browser_connector` / `computer_use`:

- Lead with **accessibility tree workflow** (already partially in `agent.py`).
- Add connector-specific **starting URL** in system prompt when `connector_id` present — skip `web_search` for known surfaces.
- Explicit rule: **never use `mouse_click` coordinates** when `browser_click(selector)` or role-based click is available.
- On `storage_state` miss: call `finish` with “Gmail not signed in — open Settings → Connectors → Gmail → Sign in”.

Update `CONNECTOR_SKILLS` for all `auth_kind: browser` entries:

- Replace “user is already signed in” with “session profile provides login; if login page appears, stop and report”.
- Standard tool chain: `browser_open` → `browser_accessibility_tree` → `browser_click` / `browser_type` → `browser_get_text`.
- Remove references to desktop UIA for pure web connectors (keep Spotify hybrid note: web default, UIA only when goal says “desktop app”).

### 5.6 Discord / hybrid connectors

Keep `discord` on `default_mode: computer` (Electron UIA). Add explicit branch in `resolve_connector_task`:

- Goal mentions “discord.com” or “web” → override to `browser_connector` + `https://discord.com/app`.
- Goal mentions “Discord app” / server names → `computer` + `electron_unlock` skill.

Document in routing table; do not flatten all connectors to browser.

---

## 6. Implementation plan

### Phase A — Routing & naming (small diff, ~1 day)

1. Add `ConnectorTask` + `resolve_connector_task()` + `CONNECTOR_START_URLS` dict (id → canonical URL).
2. Add `browser_connector` as alias in `preferences.py` validation + `main.py` task schema.
3. Dashboard / API: pass `connector_id` when spawning from connector tile.
4. Deprecation log when `mode=computer_use` used without `connector_id`.

**Files:** `connectors.py`, `main.py`, `agent.py` (mode check: `is_browser_connector = mode in ("computer_use", "browser_connector")`), `preferences.py`.

### Phase B — Session manager (medium, ~2–3 days)

1. Implement `PlaywrightSessionManager` with per-connector `user_data_dir`.
2. Refactor `BackgroundBrowser` to delegate; delete duplicate launch args.
3. Refactor `browser_plugin` to use session manager (`session_id=connector_id or task_id`).
4. `agent.py` startup: `await playwright_session.get_context(connector_id)` before loop.
5. Cleanup: extend existing atexit / task-finalize hooks (already kill zombie Chromium in `agent.py`).

**Files:** new `playwright_session.py`, `background_browser.py`, `plugins/browser_plugin.py`, `agent.py`.

### Phase C — Login UX (medium, ~2 days)

1. `POST /api/connectors/{id}/login` — headed window, blocks until `storage_state` saved or timeout.
2. Dashboard button: “Sign in” vs “Link” for `auth_kind: browser`.
3. SSE event `browser_login_required` for in-app status.
4. Health check in `main.py` readiness: `playwright` package + `chromium` installed (already partially present).

**Files:** `main.py`, `static/app.js`, `connectors.py`, `widget/desktop_features.py` (privacy copy).

### Phase D — Skills & observability (small, ~1 day)

1. Bulk-update `CONNECTOR_SKILLS` browser entries (locator-first, session-aware).
2. Log fields: `connector_id`, `browser_profile`, `auth_state=ok|login_wall`.
3. Add `docs/BENCHMARKS.md` row: Gmail triage (10 unread) — steps, tokens, wall time vs baseline.

### Phase E — CDP attach (optional, ~1 day)

1. Env `ORYNN_BROWSER_CDP` → `connect_over_cdp` in session manager.
2. Document in `README.md` / connector settings panel.

---

## 7. API & schema changes

### 7.1 `connectors.json` state (extended)

```json
{
  "gmail": {
    "linked": true,
    "linked_at": "2026-06-22T12:00:00Z",
    "auth_state": "ready",
    "profile_dir": "browser-profiles/gmail",
    "last_login_at": "2026-06-22T12:05:00Z"
  }
}
```

`auth_state`: `pending` | `ready` | `expired` | `failed`

### 7.2 New endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/connectors/{id}/login` | Headed login flow; persist session |
| `GET` | `/api/connectors/{id}/auth-status` | `ready` / `login_required` without starting agent |
| `DELETE` | `/api/connectors/{id}/session` | Clear `storage_state` + profile dir |

### 7.3 Task create body

```json
{
  "goal": "Summarize unread",
  "connector_id": "slack",
  "mode": "browser_connector"
}
```

Server overrides `mode` and prepends `task_template` when `connector_id` set.

---

## 8. Security & privacy

- **Profile dirs live in workspace** — same trust boundary as `connectors.json`; warn in Settings copy (already lists connector state).
- **Headed login window** is user-visible by design; auto-close after save.
- **No password storage** — only Playwright `storage_state` (cookies/localStorage).
- **Untrusted web content** — keep `wrap_untrusted_web_content` on all `browser_get_text` / `browser_accessibility_tree` outputs (already in `browser_plugin.py`).
- **Scheme blocking** — retain `browser_open` http(s)-only guard.
- **CDP attach** — localhost only; reject non-loopback URLs.

---

## 9. Test plan

| Test | Type | Pass criteria |
|------|------|---------------|
| `resolve_connector_task("gmail", …)` | unit | `mode=browser_connector`, correct URL |
| `resolve_connector_task("discord", "open discord.com")` | unit | browser override |
| `resolve_connector_task("discord", "server General")` | unit | `mode=computer` |
| Session manager reuse | unit | two `get_context("gmail")` → same `user_data_dir`, no double launch |
| `storage_state` round-trip | integration | save after mock login → headless load skips login form |
| `browser_open` blocks `file://` | unit | existing `test_browser_plugin` |
| Connector spawn API | integration | `connector_id=slack` → task record includes `driver=playwright` |
| Auth wall handling | integration | empty profile → agent `finish` mentions sign-in, no infinite browse loop |
| Cleanup | integration | task end → context closed; no orphan `chromium` (psutil check) |

Add `tests/test_playwright_connectors.py`; extend `tests/test_connectors_api.py`.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Google blocks automated login | Headed manual login; don’t fight CAPTCHA in agent loop |
| Profile corruption | `DELETE /session` reset; version profile schema |
| Zombie Chromium (known issue) | Reuse existing `agent.py` atexit + task finalize cleanup |
| Large profile disk use | One dir per linked connector; cap retained connectors |
| 2FA session expiry | `auth_state=expired` → dashboard “Sign in again” |
| Breaking `computer_use` clients | Alias period + deprecation log |
| Qt shell duplicate `CONNECTORS` list drifts | Single source of truth import from `connectors.py` |

---

## 11. Success metrics

| Metric | Baseline (today) | Target |
|--------|------------------|--------|
| Gmail triage task success (linked) | Often fails at login | ≥90% on repeat runs with saved profile |
| Avg tool steps for Slack unread summary | Unknown; login loops inflate | ≤15 steps |
| Vision/screenshot tool calls in browser connectors | Low but non-zero via `computer` mis-route | 0 |
| Chromium orphans after 10 connector tasks | Occasional (see cleanup scripts) | 0 |
| Token cost per Gmail triage | DOM + text model | ≤50% of mis-routed `computer` vision path |

---

## 12. Open questions

1. **Shared vs per-connector profile** — Gmail + GCal + GDocs could share `google` profile; proposal defaults per-connector for isolation, with optional `profile_group` field later.
2. **Headed debug default** — keep `BROWSER_HEADED=1` for dev; production connector tasks stay headless.
3. **Live voice path** — should Live call `/api/connectors/{id}/auth-status` before promising “checking your inbox”? Recommendation: yes, short-circuit spoken “you need to sign in to Gmail first”.
4. **Rename `computer_use` → `browser`** in UI? Recommendation: UI label “Browser (background)”; internal mode `browser_connector`.

---

## 13. Files touched (checklist)

| File | Action |
|------|--------|
| `app/playwright_session.py` | **Add** — session manager |
| `app/connectors.py` | **Extend** — `resolve_connector_task`, URLs, skill updates |
| `app/background_browser.py` | **Refactor** — delegate to session manager |
| `app/plugins/browser_plugin.py` | **Refactor** — remove globals |
| `app/agent.py` | **Update** — `browser_connector` mode, profile bootstrap |
| `app/main.py` | **Extend** — login/auth-status endpoints, task `connector_id` |
| `app/preferences.py` | **Extend** — mode enum |
| `app/widget/qt_shell.py` | **Dedup** — import connectors from registry |
| `static/app.js` | **Extend** — Sign in button, spawn with `connector_id` |
| `tests/test_playwright_connectors.py` | **Add** |
| `README.md` | **Note** — connector sign-in + optional CDP |

**Explicitly not in scope:** `gemini_live.py` tool surface changes (Live should still `start_desktop_task` with `connector_id` in envelope), Office COM shim (Proposal 08+).

---

## 14. Recommendation

Approve Phase A+B immediately — they fix the architectural lie that “connectors still use screenshot browser mode” while reusing 80% of existing code. Phase C (login UX) is **required for product credibility**; without it, linking a connector is a consent flag with no teeth. Phase E (CDP) is optional sugar for power users.

**Single-sentence decision:** Treat browser connectors as a **first-class Playwright driver with persistent profiles**, not as a misnamed vision mode — and enforce that at spawn time via `connector_id`, not goal-regex luck.
