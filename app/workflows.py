"""Orynn's workflow memory -- the PROCEDURE layer (knowledge.py is the FACT layer;
app/skills.py is a separate expertise-persona system, not this).

A workflow is a named, reusable multi-step task Orynn repeats reliably on command:
"post my anime edit", "morning setup". Where the back-office agent re-plans every
task from scratch, a workflow is a SAVED PLAN -- an ordered list of steps that run
straight through Orynn's already-verified click/type/press tiers, so a known task
is fast and deterministic instead of re-reasoned each time.

Design (ported from NousResearch/hermes-agent's SKILL.md idea, adapted for Orynn's
desktop automation + Gemini Live):
  - Steps reference UIA TARGET NAMES, never pixel coordinates, so a workflow
    survives the window moving/resizing and stays testable.
  - Triggers are keywords Live matches a spoken request against, so it knows when
    to offer/run a workflow ("post my edit" -> the "post-anime-edit" workflow).
  - Centered on Live: the snapshot is injected into Live's prompt, Live runs them
    with run_workflow and saves new ones with save_workflow.

Small flat JSON list + keyword relevance + a compact snapshot render -- no vector
DB, fail-soft (a corrupt file degrades to "no workflows", never a crash).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .state_store import read_json, workspace_state_path, write_json

MAX_WORKFLOWS = 200
MAX_STEPS = 40
# The step vocabulary a workflow may use. Each maps to an already-verified tool path
# in the controller's runner -- so a workflow never introduces new, untested behavior.
STEP_ACTIONS = ("open", "click", "type", "press_keys", "scroll", "focus", "wait", "run")


def store_path() -> Path:
    return workspace_state_path("workflows/workflows.json")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _norm(name).lower()).strip("-")
    return s[:60] or ""


def _load() -> list[dict[str, Any]]:
    data = read_json(store_path(), [])
    if not isinstance(data, list):
        return []
    return [w for w in data if isinstance(w, dict) and w.get("name")]


def _save(workflows: list[dict[str, Any]]) -> None:
    write_json(store_path(), workflows[-MAX_WORKFLOWS:])


def clean_steps(steps: Any) -> list[dict[str, Any]]:
    """Keep only well-formed steps with a known action. A step is a small dict:
    {action, target?, app?, text?, keys?, command?, seconds?}. Drops junk rather
    than raising, so a sloppy author still gets a runnable (possibly shorter) plan."""
    out: list[dict[str, Any]] = []
    if not isinstance(steps, list):
        return out
    for raw in steps[:MAX_STEPS]:
        if not isinstance(raw, dict):
            continue
        action = _norm(raw.get("action")).lower().replace("-", "_")
        if action not in STEP_ACTIONS:
            continue
        step: dict[str, Any] = {"action": action}
        for k in ("target", "app", "text", "keys", "command"):
            v = _norm(raw.get(k))
            if v:
                step[k] = v
        if action == "wait":
            try:
                step["seconds"] = max(0.1, min(10.0, float(raw.get("seconds") or 1.0)))
            except Exception:
                step["seconds"] = 1.0
        out.append(step)
    return out


def all_workflows() -> list[dict[str, Any]]:
    return _load()


def get(name: str) -> dict[str, Any] | None:
    slug = slugify(name)
    if not slug:
        return None
    workflows = _load()
    for w in workflows:
        if w.get("name") == slug:
            return w
    want = _norm(name).lower()
    for w in workflows:
        if _norm(w.get("title", "")).lower() == want:
            return w
    return None


def add_workflow(name: str, *, description: str = "", triggers: Any = None,
                 steps: Any = None, owner: str = "user") -> dict[str, Any] | None:
    """Save (or overwrite) a workflow. Returns it, or None if it has no name or no
    valid steps (an empty workflow is useless and we won't store it)."""
    slug = slugify(name)
    clean = clean_steps(steps)
    if not slug or not clean:
        return None
    if isinstance(triggers, str):
        triggers = [triggers]
    trig = [_norm(t).lower() for t in (triggers or []) if _norm(t)][:12]
    workflow = {
        "name": slug,
        "title": _norm(name),
        "description": _norm(description),
        "triggers": trig,
        "steps": clean,
        "owner": owner if owner in ("user", "assistant") else "user",
        "created_at": time.time(),
        "runs": 0,
    }
    workflows = [w for w in _load() if w.get("name") != slug]
    workflows.append(workflow)
    _save(workflows)
    return workflow


def forget_workflow(query: str) -> int:
    """Remove workflows whose name/title/description matches the query. Returns count."""
    q = _norm(query).lower()
    if not q:
        return 0
    qslug = slugify(query)
    workflows = _load()
    kept = [
        w for w in workflows
        if w.get("name") != qslug
        and q not in _norm(w.get("title", "")).lower()
        and q not in _norm(w.get("description", "")).lower()
    ]
    removed = len(workflows) - len(kept)
    if removed:
        _save(kept)
    return removed


def mark_run(name: str) -> None:
    slug = slugify(name)
    workflows = _load()
    for w in workflows:
        if w.get("name") == slug:
            w["runs"] = int(w.get("runs", 0)) + 1
            w["last_run_at"] = time.time()
            _save(workflows)
            return


def _haystack(w: dict[str, Any]) -> str:
    return " ".join([
        _norm(w.get("title", "")), _norm(w.get("name", "")),
        _norm(w.get("description", "")), " ".join(w.get("triggers", []) or []),
    ]).lower()


def relevant(query: str, limit: int = 8) -> list[dict[str, Any]]:
    workflows = _load()
    if not workflows:
        return []
    terms = [t for t in re.findall(r"[a-z0-9]+", _norm(query).lower()) if len(t) > 2]
    if terms:
        scored = [(sum(1 for t in terms if t in _haystack(w)), w) for w in workflows]
        hits = [w for n, w in sorted(scored, key=lambda x: x[0], reverse=True) if n > 0]
        if hits:
            return hits[:limit]
    return sorted(workflows, key=lambda w: w.get("created_at", 0), reverse=True)[:limit]


def as_prompt_block(query: str = "", limit: int = 8) -> str:
    """A compact snapshot of available workflows (name + what it does) to inject into
    Live's prompt, so it knows which saved workflows it can run. "" if none."""
    workflows = relevant(query, limit)
    if not workflows:
        return ""
    lines = []
    for w in workflows:
        desc = w.get("description") or f"{len(w.get('steps', []))}-step workflow"
        lines.append(f"- {w.get('title') or w.get('name')}: {desc}")
    return ("ORYNN WORKFLOWS -- saved multi-step tasks you can run with run_workflow "
            "(pass the exact name). Offer to run one when the user's request matches:\n"
            + "\n".join(lines))
