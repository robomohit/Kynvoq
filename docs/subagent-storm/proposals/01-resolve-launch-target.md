# Proposal 01 — `resolve_launch_target`

**Date:** 2026-06-22  
**Storm track:** Universal launch layer  
**Source research:** [03-universal-launch.md](../../windows-automation-research/03-universal-launch.md)  
**Scope:** Design only — no code changes in this document  
**Primary files (future):** `app/tools.py`, `app/widget/desktop_features.py` (optional `.lnk` helper), `app/agent.py`, `tests/test_launch_resolver.py`

---

## Executive Summary

Orynn today opens apps through two lanes: a **narrow voice fast-path** (`detect_app_launch_intent` → `open_known_app`, 7 built-ins) and a **planner path** that often falls back to Win+Search UI simulation (`DESKTOP_HARDENING`). The gap between them is a missing **runtime app index** that maps spoken/display names to deterministic launch primitives.

This proposal defines `resolve_launch_target(name)`: a session-scoped resolver that builds an index once from `Get-StartApps` + Start Menu `.lnk` files, merges curated overrides from `_KNOWN_LAUNCH_APPS`, and returns `(launch_command, window_title)` for any indexed app. The back-office agent and (optionally, phase 2) voice fast-path call this before launching; execution still flows through existing `open_known_app` / `_launch_gui_command` + `wait_for_window` verification.

**Outcome:** "open Discord", "open Cursor", and ~100–200 other Start-visible apps resolve to `start "" "…\Discord.lnk"` or `explorer shell:AppsFolder\<AUMID>` without per-app hard-coding or Win+Search fragility.

---

## Problem Statement

### Current behavior

| Path | Trigger | Coverage | Gap |
|------|---------|----------|-----|
| Voice fast-path | `detect_app_launch_intent(goal)` exact match on `_KNOWN_LAUNCH_APPS` | 7 OS built-ins | Third-party apps return `None` |
| Planner | `start_desktop_task` + `DESKTOP_HARDENING` | Theoretically all indexed apps | Relies on Win+Search (tier 6): slow, ambiguous, build-dependent |
| `run_command start …` | Agent emits shell | Works when model guesses correctly | No discovery; model may hallucinate paths |
| `resolve_app_exe` | Electron unlock / control plane | Running processes only | **Not** cold launch — must not be reused for open |

### Architectural insight (from research)

Windows already exposes a tiered launch stack. Orynn needs a **resolver** that sits between intent detection and launch primitives:

```
USER: "open <app>"
        │
        ├─ detect_app_launch_intent (tier 0, curated)
        │
        └─ resolve_launch_target (tiers 2–4, index-backed)
                │
                ▼
        open_known_app / _launch_gui_command
                │
                ▼
        wait_for_window(title)
```

Tier 6 (Win+Search) remains a **prompt-only fallback** when the index returns no match — never wired into `detect_app_launch_intent`.

---

## Goals

1. **Resolve** a normalized app name to `(launch_command, window_title)` using OS discovery APIs.
2. **Build once per session** (or on first resolve) — no full `Program Files` exe scan at launch time.
3. **Preserve verification contract** — callers must still `wait_for_window`; resolver only picks the command.
4. **Rank duplicates** — e.g. two `Calculator` entries: prefer `Microsoft.*!App` over Chrome PWA CRX IDs.
5. **Prefer `.lnk` over raw AUMID** when both exist — preserves working directory and arguments.
6. **Keep lanes separate** — do not bloat `_KNOWN_LAUNCH_APPS` with Discord/Chrome; curated table remains tier-0 override.

## Non-Goals (this proposal)

- Fuzzy / typo correction in voice fast-path (phase 2 optional; document interface only).
- `winget list` as launch primitive (supplementary inventory for agent reasoning only).
- Win+Search automation as primary resolver.
- Hard-coded `C:\Program Files\…` paths for Electron apps.
- Replacing `resolve_app_exe` (running-process resolution for control/unlock).
- `launch_aumid` / `list_start_apps` as separate public tools (fold into resolver + optional debug export).

---

## Proposed API

### Core function

```python
@dataclass(frozen=True)
class LaunchEntry:
    """One resolvable launch target in the session index."""
    display_name: str          # Original casing from index source
    normalized_key: str        # lower(), collapsed whitespace
    kind: Literal["curated", "lnk", "aumid", "exe_path", "protocol"]
    launch_command: str        # e.g. 'start "" "C:\\...\\Discord.lnk"'
    window_title: str          # Substring for wait_for_window
  # Optional metadata for ranking / debugging
    source_path: str = ""      # .lnk path or AppID
    rank: int = 0              # Higher = preferred among duplicates


def resolve_launch_target(
    name: str,
    *,
    index: dict[str, list[LaunchEntry]] | None = None,
) -> LaunchEntry | None:
    """Resolve a bare app name to a launch entry.

    Lookup order on normalized key:
      1. Exact key match (best-ranked entry if multiple)
      2. None — caller falls back to planner / Win+Search prompt

    Does NOT launch; does NOT verify window appeared.
    """
```

### Index lifecycle (on `ToolExecutor`)

```python
def _refresh_launch_index(self) -> dict[str, list[LaunchEntry]]:
    """Build or rebuild session launch index. Called lazily on first resolve."""

def _get_launch_index(self) -> dict[str, list[LaunchEntry]]:
    """Return cached index; refresh if empty or stale (optional TTL)."""
```

### Agent-facing tool (phase 1b)

```python
def launch_app(self, name: str, timeout: float = 12.0) -> ToolResult:
    """Resolve + launch + verify. Thin wrapper:
    entry = resolve_launch_target(name) or detect via curated path
    → open_known_app(entry.launch_command, entry.window_title, timeout)
    """
```

---

## Index Build Algorithm

### Step 1 — Curated overrides (highest precedence)

Seed index from `_KNOWN_LAUNCH_APPS` with `kind="curated"`, `rank=1000`. These win over any OS-discovered duplicate (e.g. user-pinned Notepad `.lnk` vs AUMID).

Also apply research-recommended expansions (phase 0, separate small PR): `explorer`, `cmd`, `powershell`, `wt`, `control`, `ms-settings:` deep links — all verified `start` + `wait_for_window` pairs. See [03-universal-launch.md §10.2](../../windows-automation-research/03-universal-launch.md).

### Step 2 — Start Menu `.lnk` enumeration

```powershell
$roots = @(
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
  "$env:ProgramData\Microsoft\Windows\Start Menu\Programs"
)
$roots | ForEach-Object {
  Get-ChildItem $_ -Recurse -Filter *.lnk -ErrorAction SilentlyContinue
}
```

For each `.lnk`:

1. **Key** = basename without `.lnk`, normalized (`re.sub(r"\s+", " ", s).strip().lower()`).
2. **Display name** = basename without extension (preserve casing).
3. **Resolve shortcut** via WScript.Shell COM (see below) — store `target`, `arguments`, `working_directory` for debug only; **launch the `.lnk`**, not bare `TargetPath`.
4. **Launch command** = `start "" "<full_lnk_path>"` (quoted path, empty title per `start` syntax).
5. **Window title** = display name (works for most Win32/Electron; UWP shortcuts often delegate to AUMID target).
6. **Kind** = `"lnk"`, **rank** = `500` (+ `50` if under user Programs vs common Programs).

**Test machine baseline:** 16 user `.lnk` files; common Programs may be empty or nested — recursion is required.

### Step 3 — `Get-StartApps` enumeration

```powershell
Get-StartApps | ForEach-Object { [PSCustomObject]@{ Name = $_.Name; AppID = $_.AppID } }
```

For each row:

1. **Key** = normalized `Name`.
2. **Classify AppID:**
   - Contains `!` → packaged AUMID (`kind="aumid"`).
   - Contains `\` → Win32 path-style ID (`kind="exe_path"` if ends in `.exe`).
3. **Launch command:**
   - AUMID: `explorer shell:AppsFolder\<AppID>` (escape `!` in shell if needed; prefer list form without extra escaping in Python `Popen`).
   - Path-style: `start "" "<path_from_appid_after_guid>"` only if path exists on disk.
4. **Window title** = `Name` (UWP runs under `ApplicationFrameHost`; title is display name).
5. **Rank** = base by kind:
   - `Microsoft.*!App` → `400`
   - Other `!App` (non-Microsoft package) → `300`
   - Chrome `._crx_` / PWA duplicates → `100`
   - Path-style `{GUID}\foo.exe` → `350`

**Skip** adding AUMID entry if same normalized key already has a `.lnk` entry with equal or higher rank (`.lnk` preserves args).

### Step 4 — Merge & duplicate handling

- Index type: `dict[str, list[LaunchEntry]]` — multiple entries per key allowed.
- On resolve, pick `max(entries, key=lambda e: e.rank)`.
- Store all entries for `list_start_apps` debug output (phase 1b).

### Step 5 — Optional protocol registry (phase 2)

Low-priority augmentation: read `HKCR\<protocol>\shell\open\command` for apps like `spotify:` only when name matches and protocol is registered. **Do not guess** `start spotify:` without registry proof — unregistered protocols show error dialogs.

---

## Resolution Algorithm

```
resolve_launch_target(name):
  key = normalize(name)
  if not key: return None

  index = _get_launch_index()

  # 1. Exact key
  if key in index:
    return best_ranked(index[key])

  # 2. (Phase 2) Fuzzy: single close match via difflib / Levenshtein threshold
  #    Only if exactly one candidate within edit distance ≤ 2

  return None
```

**Decision tree** (matches research §7.3):

```
App request "open X"
├─ _KNOWN_LAUNCH_APPS / curated in index?     → start command (tier 0)
├─ Start Menu X.lnk in index?                  → start "" "path\X.lnk"
├─ Get-StartApps single high-rank match?       → explorer shell:AppsFolder\<AppID>
├─ Get-StartApps multiple?                     → best rank (Microsoft.*!App > .exe > PWA)
├─ Protocol registered (phase 2)?              → start protocol:
└─ else                                        → None (planner / Win+Search fallback)
```

---

## `.lnk` Resolution Helper

Add to `desktop_features.py` (or private module `app/launch_index.py` if `tools.py` grows too large):

```python
def read_shortcut(lnk_path: str) -> tuple[str, str, str]:
    """Return (target_path, arguments, working_directory) via WScript.Shell COM."""
```

Use `win32com.client.Dispatch("WScript.Shell")` — already a Windows-only dependency path in Orynn. COM read is for metadata and tests; launch always uses the `.lnk` path.

---

## Launch Primitive Mapping

| `LaunchEntry.kind` | `launch_command` | `window_title` | Notes |
|--------------------|------------------|----------------|-------|
| `curated` | From `_KNOWN_LAUNCH_APPS` | Known title | Tier 0 |
| `lnk` | `start "" "<lnk>"` | `.lnk` display name | Prefer over AUMID |
| `aumid` | `explorer shell:AppsFolder\<AppID>` | `display_name` | UWP / Store |
| `exe_path` | `start "" "<exe>"` | `display_name` or stem | Path-style AppID |
| `protocol` | `start <protocol>:` | Mapped or display name | Registry-verified only |

All executions route through existing detached launch:

- `open_known_app(launch_command, window_title)` for agent fast-path and `launch_app` tool.
- `_launch_gui_command` when agent uses `run_command` with a pre-resolved command.

Extend `_guess_launch_target_title` only for new URI schemes added to curated table (`ms-screenclip:`, etc.) — index-backed launches pass explicit `window_title` from `LaunchEntry`, bypassing guess.

---

## Integration Points

### 1. `ToolExecutor.__init__`

- Add `self._launch_index: dict[str, list[LaunchEntry]] | None = None`.
- Optional: `self._launch_index_built_at: float` for TTL refresh (e.g. 30 min) if user installs app mid-session.

### 2. Back-office agent (`agent.py`)

Before LLM loop, after `detect_app_launch_intent` miss:

```python
_launch = detect_app_launch_intent(goal)
if _launch:
    # existing fast-path
elif _is_pure_launch(goal):  # reuse _LAUNCH_VERB_RE + _LAUNCH_EXTRA_RE helpers
    entry = tools.resolve_launch_target(_extract_app_name(goal))
    if entry:
        res = await asyncio.to_thread(tools.open_known_app, entry.launch_command, entry.window_title)
```

Extract `_extract_app_name` by sharing normalization logic with `detect_app_launch_intent` (refactor to avoid drift).

### 3. `launch_app` tool registration

Expose to agent tool schema with description: *"Open an installed app by display name. Uses Start Menu index. Prefer over run_command start when app name is known."*

### 4. Voice overlay (`textbox_overlay.py`)

Phase 1: **no change** — keep voice path on curated registry only.  
Phase 2: optional index lookup with **strict** single-match fuzzy; still reject `_LAUNCH_EXTRA_RE` multi-step goals.

### 5. `DESKTOP_HARDENING` prompt

Add one line: *"If `launch_app` is available and returns not found, then use Win+Search."* — reinforces tier ordering.

---

## Module Layout (recommended)

| Module | Responsibility |
|--------|----------------|
| `app/launch_index.py` (new) | `LaunchEntry`, `build_launch_index()`, `normalize_app_name()`, `rank_start_app()`, `read_shortcut()` |
| `app/tools.py` | `ToolExecutor._refresh_launch_index`, `resolve_launch_target`, `launch_app`; call into `launch_index` |
| `app/agent.py` | Pure-launch fast-path after curated miss |
| `tests/test_launch_resolver.py` (new) | Unit tests with mocked PowerShell / fixture JSON |

Keeping index build out of `tools.py` reduces file size and allows testing without full `ToolExecutor` setup.

---

## Phased Rollout

### Phase 0 — Curated expansion (prerequisite, tiny)

- Add safe OS built-ins to `_KNOWN_LAUNCH_APPS` per research §10.2.
- Extend `_guess_launch_target_title` / `uri_titles` for new `ms-settings:` / `ms-screenclip:` schemes.
- **No** `resolve_launch_target` yet.

### Phase 1a — Index + resolver (read-only)

- Implement `build_launch_index()` + `resolve_launch_target()`.
- Unit tests with frozen `Get-StartApps` / `.lnk` fixture from test machine.
- Manual CLI/script: `python -m app.launch_index --dump` for QA on target hardware.

### Phase 1b — `launch_app` tool + agent fast-path

- Wire `launch_app` into agent tool list.
- Pure-launch agent bypass when index hits.
- `list_start_apps` or debug field on `launch_app` failure: *"Known apps: …"* (truncated).

### Phase 2 — Fuzzy voice + protocol registry

- Optional fuzzy match in `resolve_launch_target` (voice only, high confidence bar).
- Protocol registry lookup for registered URI handlers.
- Index TTL refresh on install-detect (optional).

---

## Testing Plan

### Unit tests (`tests/test_launch_resolver.py`)

| Case | Expected |
|------|----------|
| Normalize `"  Open   Discord  "` → key `discord` | Stable normalization |
| Curated `notepad` overrides `.lnk` Notepad | `rank` precedence |
| Duplicate `Calculator`: Microsoft AUMID vs Chrome PWA | Microsoft wins |
| `.lnk` present for `Cursor` | `kind=lnk`, command contains `.lnk` |
| Unknown `xyzzy` | `None` |
| `read_shortcut` on fixture `.lnk` | Correct `TargetPath` |

### Integration tests (Windows CI / manual)

| Utterance / call | Expected |
|------------------|----------|
| `launch_app("Discord")` | `ok=True`, window title contains Discord |
| `launch_app("Calculator")` | Opens UWP Calculator, not PWA |
| `detect_app_launch_intent("open notepad")` | Still curated fast-path (unchanged) |
| `detect_app_launch_intent("open notepad and type hi")` | `None` — planner |
| Index build time | < 3 s on 121-entry machine |

### Fixture strategy

Capture once per machine:

```powershell
Get-StartApps | ConvertTo-Json -Depth 3 | Out-File tests/fixtures/start_apps_acer.json
# + copy representative .lnk files or mock COM
```

Tests run against JSON fixture on non-Windows runners; full integration on Windows only.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Duplicate display names | Rank table; prefer `.lnk` and `Microsoft.*!App` |
| Index stale after install | Lazy rebuild on miss + optional TTL; document `launch_app` retry |
| `Get-StartApps` unavailable / empty | Graceful degrade to `.lnk`-only index |
| Wrong window title for Electron | Use `.lnk` display name; agent can `focus_window` after |
| PowerShell startup cost | `-NoProfile -Command`; cache for session |
| Conflation with `resolve_app_exe` | Separate names, docstrings, and modules |
| `explorer shell:AppsFolder\…` quoting | Test on Win11 26200; use single-string `Popen` |

---

## Success Criteria

1. **Coverage:** ≥ 90% of user Start Menu `.lnk` apps resolve on test machine (16/16).
2. **Latency:** Index build < 3 s; resolve < 1 ms (dict lookup).
3. **Correctness:** No `ok=True` without `wait_for_window` — unchanged contract.
4. **Regression:** All existing `test_voice_and_env.py` launch tests pass unchanged.
5. **Fallback:** Unindexed app returns clear `ok=False` with hint to use planner — not silent wrong app.

---

## Anti-Patterns (do not implement)

- Scanning all of `Program Files` at resolve time.
- Adding Chrome/Firefox/Discord to `_KNOWN_LAUNCH_APPS`.
- Win+Search in `detect_app_launch_intent`.
- `where.exe` as sole discovery source.
- Guessing `start spotify:` without registry check.
- Reporting launch success without window verification.

---

## References

- [03-universal-launch.md](../../windows-automation-research/03-universal-launch.md) — tier model, index build pseudocode, duplicate ranking
- [00-master-strategy.md](../../windows-automation-research/00-master-strategy.md) — launch → navigate → act; back-office vs Live boundaries
- `app/tools.py` — `_KNOWN_LAUNCH_APPS`, `detect_app_launch_intent`, `open_known_app`, `_launch_gui_command`
- `app/widget/desktop_features.py` — `resolve_app_exe` (control only, not launch)
- Microsoft: [Find AUMID](https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid), [WScript.Shell Shortcut](https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/windows-scripting/fdfdimyh(v=vs.84))

---

*Re-run `Get-StartApps` and Start Menu enumeration on target hardware before shipping. Verified behaviors vary by Windows 11 build, SKU, and installed software.*
