"""Orynn's knowledge memory — durable facts the user teaches it ("cowork is the
button top-right") plus things it auto-learns (where a control was found, what an
app is). Injected into the Live conversation and agent goals so Orynn understands
the user's setup and vocabulary instead of starting cold every time.

Persisted to workspace/knowledge.json (per-user, gitignored). Deliberately a small
flat list with keyword relevance — no vector DB needed for a personal fact list, and
it stays fail-soft so a corrupt file degrades to "no knowledge", never a crash.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .state_store import read_json, workspace_state_path, write_json

MAX_FACTS = 300          # hard cap; oldest non-pinned facts drop first
_INJECT_DEFAULT = 12     # how many facts to surface into a prompt


def store_path() -> Path:
    return workspace_state_path("knowledge.json")


def _load() -> list[dict[str, Any]]:
    data = read_json(store_path(), [])
    return data if isinstance(data, list) else []


def _save(facts: list[dict[str, Any]]) -> None:
    write_json(store_path(), facts[-MAX_FACTS:])


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def all_facts() -> list[dict[str, Any]]:
    return _load()


def add_fact(text: str, *, app: str = "", source: str = "taught") -> dict[str, Any] | None:
    """Store a fact. Near-identical text (same normalized lowercase) is de-duped:
    re-teaching just refreshes it rather than piling up. Returns the stored fact, or
    None if the text was empty."""
    body = _norm(text)
    if not body:
        return None
    facts = _load()
    key = body.lower()
    facts = [f for f in facts if _norm(f.get("text", "")).lower() != key]
    fact = {
        "id": f"k{int(time.time() * 1000)}",
        "text": body,
        "app": _norm(app),
        "source": source if source in ("taught", "learned") else "taught",
        "created_at": time.time(),
    }
    facts.append(fact)
    _save(facts)
    return fact


def forget(query: str) -> int:
    """Remove facts whose text contains the query (case-insensitive). Returns how
    many were removed."""
    q = _norm(query).lower()
    if not q:
        return 0
    facts = _load()
    kept = [f for f in facts if q not in _norm(f.get("text", "")).lower()]
    removed = len(facts) - len(kept)
    if removed:
        _save(kept)
    return removed


def _score(fact: dict[str, Any], terms: list[str]) -> int:
    hay = (_norm(fact.get("text", "")) + " " + _norm(fact.get("app", ""))).lower()
    return sum(1 for t in terms if t in hay)


def relevant(query: str, limit: int = _INJECT_DEFAULT) -> list[dict[str, Any]]:
    """Facts most relevant to a query (simple keyword overlap). With no query, or no
    overlap, returns the most recent facts — so Live always has *some* context."""
    facts = _load()
    if not facts:
        return []
    terms = [t for t in re.findall(r"[a-z0-9]+", _norm(query).lower()) if len(t) > 2]
    if terms:
        scored = sorted(facts, key=lambda f: (_score(f, terms), f.get("created_at", 0)), reverse=True)
        hits = [f for f in scored if _score(f, terms) > 0]
        if hits:
            return hits[:limit]
    return sorted(facts, key=lambda f: f.get("created_at", 0), reverse=True)[:limit]


def as_prompt_block(query: str = "", limit: int = _INJECT_DEFAULT) -> str:
    """A compact block of known facts to inject into a system prompt / goal, or "" if
    there's nothing worth saying."""
    facts = relevant(query, limit)
    if not facts:
        return ""
    lines = []
    for f in facts:
        app = f.get("app", "")
        lines.append(f"- {f['text']}" + (f" (in {app})" if app else ""))
    return "What you already know about the user and their setup:\n" + "\n".join(lines)
