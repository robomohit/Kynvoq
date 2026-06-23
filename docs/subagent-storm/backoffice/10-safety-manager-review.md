# SafetyManager — Back-Office Code Review

**Doc:** `10-safety-manager-review.md`  
**Date:** 2026-06-22  
**Scope:** `SafetyManager` in `app/safety.py` — per-action danger classification and approval gating for the Orynn desktop agent  
**Audience:** Orynn back-office / agent engineering  
**Related:** `app/agent.py`, `app/permissions.py`, `app/widget/textbox_overlay.py`, `tests/test_new_actions.py`, `tests/test_approval.py`

> **Naming note:** There is no `safety_manager.py`. The class is `SafetyManager` in `app/safety.py` (~172 lines, stateless).

---

## Executive Summary

`SafetyManager.evaluate(action, safe_mode=True)` is the **first layer** of Orynn’s safety stack. It returns an `ActionDecision` (`danger`, `reason`, `requires_approval`) consumed by `AgentService._approval_gated()` before tool execution.

It works alongside two other layers:

| Layer | Module | Role |
|-------|--------|------|
| **1. Action safety** | `app/safety.py` | Classify danger; require per-action approval |
| **2. Scope permissions** | `app/permissions.py` | Grant/deny filesystem, shell, screen, desktop, MCP, etc. |
| **3. Live voice consent** | `textbox_overlay.py` | Spoken consent for destructive (non-catastrophic) terminal commands and disruptive goals |

**Strengths:** Clear tiering (hard-block → high-risk → medium → low); catastrophic shell patterns always gate even in autonomous mode; kill/MCP/desktop-lifecycle actions never auto-approve in coding mode; good test coverage for Windows destructive commands, MCP, folder analysis, and terminal helpers.

**Main gaps:** Substring-based command blocking is bypassable; many sensitive action types fall through to a permissive default; Live reuses `requires_approval` as a hard block (different semantics from desktop); no dedicated `test_safety.py` — tests are scattered in `test_new_actions.py`.

---

## 1. Architecture & Call Sites

### 1.1 Core API

```python
class SafetyManager:
    def evaluate(self, action: Action, safe_mode: bool = True) -> ActionDecision
```

- **Input:** `Action` (type + args), `safe_mode` flag  
- **Output:** `ActionDecision` with `DangerLevel` (`low` | `medium` | `high`), human-readable `reason`, and `requires_approval: bool`

### 1.2 Where it runs

| Call site | File | `safe_mode` |
|-----------|------|-------------|
| `AgentService.__init__` | `app/agent.py:1258` | Instance held as `self.safety` |
| Streaming agent loop | `app/agent.py:3006` | `safe_mode=not is_auto_approve` |
| Hierarchical `SubTaskWorker` | `app/agent.py:1006` | `safe_mode=not (is_coding or auto_approve)` |
| Live `run_terminal` | `textbox_overlay.py:2534` | Always `safe_mode=False` |
| Tests | `tests/test_new_actions.py`, `tests/test_approval.py`, `tests/test_computer_control_regressions.py` | Various |

### 1.3 Integration with approval flow

```python
# agent.py — _approval_gated
if not (action.requires_approval or decision.requires_approval):
    return False
if task_id in self._approval_bypass_tasks:  # autonomy_level == "autonomous"
    return str(decision.reason or "").startswith("Hard-blocked")
return True
```

**Autonomous tasks** (floating bubble / voice) skip all approval prompts **except** commands whose reason starts with `"Hard-blocked"`. That string prefix is a contract between `safety.py` and `agent.py`.

### 1.4 `safe_mode` semantics (inverted at call site)

In `agent.py`, `safe_mode=True` means **strict** — more popups. `safe_mode=False` means **coding/auto-approve** for high-risk file/shell ops:

```python
is_auto_approve = mode in ("coding", "chat", "auto", "computer", ...)
if autonomy_level == "careful":
    is_auto_approve = False
decision = self.safety.evaluate(act, safe_mode=not is_auto_approve)
```

---

## 2. Decision Logic (Flow)

```
evaluate(action, safe_mode)
│
├─ type in {run_command, bash, run_tests, run_and_watch}?
│   └─ command matches dangerous_patterns? → HIGH, requires_approval=True, "Hard-blocked..."
│
├─ safe_mode=False AND type in high_risk?
│   └─ MEDIUM, requires_approval=False, "coding mode — auto-approved"
│
├─ type in high_risk?
│   └─ HIGH, requires_approval=True, "filesystem/shell mutation"
│
├─ type == analyze_folder?
│   ├─ action != scan → HIGH, requires_approval=True
│   └─ else → LOW, no approval
│
├─ Explicit branches: scroll, browser_*, clicks, key_combo, force_close_window,
│   kill_process, electron_unlock, mcp_*, api_call, clipboard, notify, finish, etc.
│
└─ default → LOW, requires_approval=False, "default — unclassified action"
```

### 2.1 High-risk action types (`high_risk` set)

Shell/command: `run_command`, `bash`, `run_tests`, `run_and_watch`  
Filesystem/code: `git`, `lint_code`, `write_file`, `move_file`, `text_editor`, `text_create`, `text_str_replace`, `text_insert`

### 2.2 Hard-blocked command patterns (substring match, lowercase)

POSIX: `rm -rf /`, `rm -rf ~`, fork bomb, `chmod -r 000`, `mkfs`, `dd if=`, …  
Windows: `del /f /s`, `remove-item -recurse`, `format c:`, `diskpart`, `reg delete`, `shutdown`, `reboot`, …

Normalization: collapse whitespace, lowercase, strip.

### 2.3 Always require approval (even when `safe_mode=False`)

- Hard-blocked shell commands  
- `force_close_window`, `kill_process`, `electron_unlock`  
- `mcp_tool`, `list_mcp_servers`, `list_mcp_tools`  
- Dangerous `key_combo`: `ctrl+alt+del`, `win+l`, `ctrl+alt+t`, `alt+f4`  
- Mutating `api_call` (POST/PUT/PATCH/DELETE)  
- Non-scan `analyze_folder` actions  

---

## 3. Three-Tier Terminal Safety (Desktop vs Live)

| Tier | Mechanism | Examples | Bypass in autonomous? |
|------|-----------|----------|----------------------|
| **Catastrophic** | `SafetyManager` hard-block | `format c:`, `rm -rf /`, `shutdown` | **No** — always gated |
| **Destructive** | Live `LIVE_TERMINAL_CONSENT_RE` + spoken confirm | `del`, `git push`, `taskkill`, `pip uninstall` | Yes (voice consent only) |
| **Routine** | Permission scope + optional approval | `pytest`, `git status`, `mkdir` | Yes (with pre-granted scopes) |

Live `_live_run_terminal` treats **any** `requires_approval=True` as a **hard block** (not a UI approval dialog). With `safe_mode=False`, benign `run_command` auto-approves; only hard-blocked patterns and (separately) consent-tier commands are stopped.

---

## 4. Unclassified Actions (Design Choice)

~40 `ActionType` values are **not** explicitly handled and receive:

```python
ActionDecision(danger=LOW, reason="default — unclassified action", requires_approval=False)
```

Examples: `read_file`, `screenshot`, `screen_context`, `mouse_click`, `keyboard_type`, `uia_*`, `hold_key`, `wait_for_window`, `delegate_coding`, `web_fetch`, connector actions (`weather`, `wikipedia`, …).

**This is intentional:** scope gating in `permissions.py` handles these. For example, `read_file` → `PermissionScope.filesystem`; `screenshot` → `screen`. SafetyManager focuses on **mutation risk** and **irreversible ops**, not read-only privacy scopes.

**Risk:** If a new action type is added without both a safety branch **and** a permission mapping, it executes with no gate.

---

## 5. Test Coverage

| Area | Test file | Notes |
|------|-----------|-------|
| Hard-blocked Windows commands | `test_new_actions.py::test_safety_flags_destructive_windows_commands` | Parametrized: Remove-Item, del, diskpart, reg delete |
| Coding auto-approve vs dangerous | `test_safety_and_permissions_classify_terminal_helpers` | `pytest` vs `shutdown /s` |
| Desktop lifecycle | `test_safety_desktop_lifecycle_actions_always_require_approval` | force_close, electron_unlock |
| Process/MCP | `test_safety_process_and_watch_actions_are_classified`, `test_safety_and_permissions_classify_dynamic_mcp_execution` | |
| Autonomous bypass | `test_approval.py::test_autonomous_tasks_bypass_approval` | Hard-blocked prefix contract |
| E2E approval for force_close/MCP | `test_computer_control_regressions.py` | Integration with streaming loop |

**Missing tests (recommended):**

- Obfuscation bypass attempts (`f o r m a t`, base64, aliases)  
- `api_call` GET vs DELETE  
- `key_combo` edge cases (spacing, casing)  
- Unclassified actions that should **not** default to low (if any are added)  
- Live terminal: benign command passes, hard-block fails, consent-tier needs confirm  

---

## 6. Findings & Recommendations

### 6.1 Security — command pattern matching

**Issue:** `any(p in cmd for p in dangerous_patterns)` is substring-based. Bypass vectors include:

- Command chaining: `echo ok && format c:`  
- PowerShell aliases / `-EncodedCommand`  
- Variable expansion, comment insertion, alternate spellings (`Remove-Item` vs `ri`)  
- Paths that embed patterns as innocuous substrings (rare false positive)

**Recommendation:** Consider token/boundary-aware matching (similar to `LIVE_TERMINAL_CONSENT_RE` in `textbox_overlay.py`) or a small parser for the first command in a chain. Keep hard-block list aligned between Live consent regex and SafetyManager patterns.

### 6.2 Semantic mismatch — Live hard block vs desktop approval

**Issue:** Live uses `requires_approval` as “blocked entirely.” Desktop uses it as “show approval UI.” Same flag, different UX.

**Recommendation:** Add an explicit `ActionDecision.blocked: bool` or separate `evaluate_for_live()` to avoid conflating “needs human OK once” with “never run via voice.”

### 6.3 Fragile autonomous contract

**Issue:** Autonomous bypass depends on reason string prefix `"Hard-blocked"`.

**Recommendation:** Add `ActionDecision.hard_blocked: bool` or `DangerLevel.catastrophic` enum value instead of string matching in `_approval_gated`.

### 6.4 `kill_process` / `force_close_window` in coding mode

**Good:** Always `requires_approval=True` regardless of `safe_mode`. Verified by tests.

### 6.5 `set_clipboard` — medium danger, never requires approval

**Issue:** `requires_approval=False` always; only scope permission applies.

**Assessment:** Acceptable if clipboard scope is explicit-grant-only (`can_auto_grant_scope` returns False). Document this pairing.

### 6.6 `read_file` unclassified

**Assessment:** OK — filesystem permission required. SafetyManager correctly does not double-gate reads.

### 6.7 Stateless instantiation in Live

Live creates `SafetyManager()` per call rather than reusing `AgentService.safety`. Harmless (no state) but inconsistent.

### 6.8 Maintenance — action type registry

**Recommendation:** Generate or test that every `ActionType` enum member is either explicitly classified in `safety.py` or documented as “permission-only default.” A single parametrized test over all enum values would catch drift.

---

## 7. Action Classification Reference

| Category | Action types | Default danger | Approval (safe_mode=True) | Approval (safe_mode=False) |
|----------|--------------|----------------|---------------------------|------------------------------|
| Hard-blocked shell | run_command/bash/run_tests/run_and_watch + pattern | high | yes | yes |
| High-risk mutation | git, lint, write/move/text_* | high | yes | **no** (auto) |
| Folder mutate | analyze_folder (non-scan) | high | yes | yes |
| Desktop terminate | force_close_window, kill_process, electron_unlock | high | yes | yes |
| MCP | mcp_tool, list_mcp_* | high | yes | yes |
| UI read-only | scroll, browser_get_text, wait_action, … | low | no | no |
| UI interactive | double_click, browser_click, … | medium | yes | no |
| Key combo | key_combo (most) | medium | no | no |
| Key combo (dangerous) | ctrl+alt+del, win+l, alt+f4 | high | yes | yes |
| API | api_call GET | low | no | no |
| API mutate | api_call POST/PUT/PATCH/DELETE | high | yes | yes |
| Unclassified | read_file, screenshot, uia_*, … | low | no | no |

---

## 8. File Map

| Path | Role |
|------|------|
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\safety.py` | **SafetyManager** implementation |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\models.py` | `Action`, `ActionType`, `ActionDecision`, `DangerLevel` |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\agent.py` | Approval gating, safe_mode wiring, autonomous bypass |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\permissions.py` | Scope mapping (complementary layer) |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\app\widget\textbox_overlay.py` | Live terminal safety + consent tier |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_new_actions.py` | Primary SafetyManager unit tests |
| `C:\Users\ACER\Desktop\Ai_computer\Orynn\tests\test_approval.py` | Autonomous bypass + permission integration |

---

## 9. Verdict

**Overall:** `SafetyManager` is a focused, readable policy module that correctly anchors Orynn’s irreversible-action defenses. It is not a sandbox — command blocking is advisory pattern matching, and many actions rely on the permission layer.

**Priority follow-ups:**

1. Replace string-prefix `"Hard-blocked"` contract with a typed flag  
2. Add enum-coverage test for all `ActionType` values  
3. Harden command parsing (boundary-aware, chain-aware)  
4. Clarify Live vs desktop semantics for `requires_approval`  

**Suitable for back-office storm doc series:** Yes — this module is a critical control point and should stay synchronized with Live consent rules and permission scopes as new tools are added.
```

---
