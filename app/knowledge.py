"""Orynn's knowledge memory — an organized, durable store of what it knows.

Two owners:
  - "user"      : things the user told/taught it — rules, preferences, facts
                  ("always confirm before sending", "my budget sheet is in Documents").
  - "assistant" : things Orynn figured out on its own — where it found a control or
                  app, what a term means ("slack is pinned on the taskbar").

Each entry also has a category for organization (rule / preference / location /
vocab / fact / app). Persisted to a dedicated workspace/memory/knowledge.json
(per-user, gitignored). Injected into the Live conversation and agent goals so Orynn
understands the user's setup/vocabulary instead of starting cold.

Deliberately a small flat list with keyword relevance + grouped rendering — no vector
DB needed for a personal store, and it's fail-soft (a corrupt file degrades to "no
knowledge", never a crash).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .state_store import read_json, workspace_state_path, write_json

MAX_FACTS = 400
_INJECT_DEFAULT = 16

OWNERS = ("user", "assistant")
CATEGORIES = ("rule", "preference", "location", "vocab", "fact", "app")


def store_path() -> Path:
    # A dedicated memory/ area, not loose in the workspace root.
    return workspace_state_path("memory/knowledge.json")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _migrate(fact: dict[str, Any]) -> dict[str, Any]:
    """Upgrade an older flat fact (source=taught/learned, no owner/category)."""
    if "owner" not in fact:
        fact["owner"] = "assistant" if fact.get("source") == "learned" else "user"
    if "category" not in fact:
        fact["category"] = "fact"
    return fact


def _load() -> list[dict[str, Any]]:
    data = read_json(store_path(), [])
    if not isinstance(data, list):
        return []
    return [_migrate(f) for f in data if isinstance(f, dict)]


def _save(facts: list[dict[str, Any]]) -> None:
    write_json(store_path(), facts[-MAX_FACTS:])


def all_facts() -> list[dict[str, Any]]:
    return _load()


def add_fact(text: str, *, owner: str = "user", category: str = "fact", app: str = "") -> dict[str, Any] | None:
    """Store a fact. Re-adding the same text refreshes it (de-duped). Returns the
    stored fact, or None if empty."""
    body = _norm(text)
    if not body:
        return None
    owner = owner if owner in OWNERS else "user"
    category = (_norm(category).lower() or "fact")
    facts = _load()
    key = body.lower()
    facts = [f for f in facts if _norm(f.get("text", "")).lower() != key]
    fact = {
        "id": f"k{int(time.time() * 1000)}",
        "text": body,
        "owner": owner,
        "category": category,
        "app": _norm(app),
        "created_at": time.time(),
    }
    facts.append(fact)
    _save(facts)
    return fact


def forget(query: str) -> int:
    """Remove facts whose text contains the query (case-insensitive). Returns count."""
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
    hay = (_norm(fact.get("text", "")) + " " + _norm(fact.get("app", "")) + " "
           + _norm(fact.get("category", ""))).lower()
    return sum(1 for t in terms if t in hay)


def relevant(query: str, limit: int = _INJECT_DEFAULT) -> list[dict[str, Any]]:
    """Facts most relevant to a query (keyword overlap); falls back to most recent so
    Live always has some context."""
    facts = _load()
    if not facts:
        return []
    terms = [t for t in re.findall(r"[a-z0-9]+", _norm(query).lower()) if len(t) > 2]
    if terms:
        hits = [f for f in facts if _score(f, terms) > 0]
        if hits:
            return sorted(hits, key=lambda f: (_score(f, terms), f.get("created_at", 0)), reverse=True)[:limit]
    return sorted(facts, key=lambda f: f.get("created_at", 0), reverse=True)[:limit]


def _render(fact: dict[str, Any]) -> str:
    cat = fact.get("category", "")
    app = fact.get("app", "")
    prefix = f"[{cat}] " if cat in ("rule", "preference") else ""
    suffix = f" (in {app})" if app else ""
    return f"- {prefix}{fact['text']}{suffix}"


def as_prompt_block(query: str = "", limit: int = _INJECT_DEFAULT) -> str:
    """A compact, ORGANIZED block of known facts to inject into a prompt — grouped by
    who established it (user vs. learned), so Orynn reads its memory clearly. "" if
    there's nothing worth saying."""
    facts = relevant(query, limit)
    if not facts:
        return ""
    user = [f for f in facts if f.get("owner") == "user"]
    learned = [f for f in facts if f.get("owner") == "assistant"]
    blocks = []
    if user:
        blocks.append("What the user has told you (their rules, preferences & facts):\n"
                      + "\n".join(_render(f) for f in user))
    if learned:
        blocks.append("What you've learned about their setup on your own:\n"
                      + "\n".join(_render(f) for f in learned))
    return "ORYNN MEMORY — things you already know (don't ask or re-look for these):\n\n" + "\n\n".join(blocks)
