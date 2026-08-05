"""Reasoned proactivity — the judgment layer between raw triggers and the user.

watchers.py stays what it is: dumb, deterministic, always-on senses. What
changes is what happens AFTER a trigger fires. Previously the answer was
hardwired — severity picked a ladder rung, the message was a fixed template,
and that was the entire "decision". This module replaces that reflex with
judgment, in two directions:

INBOUND (triage): when a watcher fires, an LLM — given the event, the local
time, recent activity, recent proactive decisions, and Orynn's knowledge
memory — decides whether this is actually worth the user's attention right
now, at what loudness, phrased how, and what Orynn could offer to DO about
it. The deterministic path is the floor, not the ceiling: any model failure,
timeout, or low-confidence verdict falls back to exactly the old behavior.

OUTBOUND (patterns): a small observation journal records what the user
actually does (completed task goals, watcher fires). Deterministic miners
read it and derive candidate triggers from the user's own history — habits
("around this time you usually X"), sequences ("after Y you usually X"),
staleness ("you haven't done Z in a while"). Mining is pure math; the LLM is
only consulted to judge worth and phrasing before one surfaces.

Trust contract (every guard here is deterministic — the model never enforces
its own leash):
* ``critical`` events NEVER wait on, and can never be suppressed or rephrased
  by, an LLM — urgent conditions surface instantly on the rule path;
* the LLM may drop a rung or suppress noise (confidence-gated), but can never
  escalate anything to the voice rung;
* suggestions are OFFERS on the silent info rung — glow + toast, never voice,
  never auto-run; acting requires the user to say yes;
* anti-spam is layered: per-suggestion 24 h cooldown, a small daily budget,
  twice-ignored → a week of silence, an explicit mute list, and a
  ``proactive_suggestions`` preference that turns the whole pipeline off;
* every decision (surfaced / suppressed / fallback, by whom, why) is
  journaled so proactivity is inspectable, not vibes.

Fail-soft everywhere: no API key, a bad store, a dead model — all degrade to
the deterministic behavior that shipped before this module existed.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import threading
import time
import uuid
from typing import Any, Callable

from .state_store import read_json, workspace_state_path, write_json

# ── knobs (deterministic; the LLM cannot loosen them) ────────────────────────
OBS_MAX = 2000                 # observation journal cap
DECISIONS_MAX = 100            # decision journal cap
TRIAGE_TIMEOUT_S = 12.0        # max seconds a verdict may take; then fallback
MIN_SUPPRESS_CONF = 0.6        # below this, a "don't surface" verdict is ignored
MIN_SUGGEST_CONF = 0.6         # mined suggestions below this never surface
SUGGEST_COOLDOWN_S = 24 * 3600         # one surfacing per suggestion per day
SUGGEST_DAILY_BUDGET = 5               # max suggestions surfaced per local day
IGNORED_MUTE_AFTER = 2                 # ignored twice in a row → long sleep
IGNORED_SLEEP_S = 7 * 24 * 3600        # the long sleep (matches promotion.py)
DAEMON_INTERVAL_S = 30 * 60            # pattern-mining cadence

HABIT_MIN_DAYS = 3             # distinct days before "around now you usually…"
HABIT_SPREAD_H = 1.5           # max mean deviation from the habitual hour
HABIT_FIRE_WINDOW_H = 0.75     # fires only within ±45 min of the habitual hour
SEQ_MIN_COUNT = 3              # times A→B must repeat before it's a pattern
SEQ_WINDOW_S = 45 * 60         # max gap for "B follows A"
STALE_MIN_COUNT = 3            # occurrences before a cadence is "established"
STALE_MIN_INTERVAL_S = 20 * 3600       # cadences shorter than ~a day aren't habits
STALE_OVERDUE_FACTOR = 1.5     # overdue by 1.5× the usual interval → mention it

TRIAGE_SYSTEM = (
    "You are the proactive-judgment layer of Orynn, a Windows desktop voice "
    "assistant. A deterministic system sensor just fired. Decide whether this "
    "is worth the user's attention right now, how loudly, and what Orynn "
    "could offer to do about it. Respond with ONLY a JSON object:\n"
    '{"surface": true|false, "severity": "info"|"notice", '
    '"message": "what the user sees, <=200 chars, concrete and calm", '
    '"suggestion": "one next step Orynn could take if the user says yes, or \\"\\"", '
    '"confidence": 0.0-1.0, "reason": "one short sentence"}\n'
    "Rules: suppress only genuine noise (e.g. the same condition the user was "
    "just told about, or something their recent activity shows they already "
    "handled). When in doubt, surface at the quieter severity. Fold the "
    "suggestion into the message so the user can just say yes. Never invent "
    "numbers not present in the event."
)

SUGGEST_SYSTEM = (
    "You are the proactive-judgment layer of Orynn, a Windows desktop voice "
    "assistant. A pattern miner found a candidate habit in the user's own "
    "history and wants to offer it. Decide if it is worth surfacing right "
    "now and phrase it well. Respond with ONLY a JSON object:\n"
    '{"surface": true|false, "message": "the offer, <=200 chars, phrased as a '
    'question the user can answer with yes", "confidence": 0.0-1.0, '
    '"reason": "one short sentence"}\n'
    "Rules: the offer must stay an offer — never imply the action was already "
    "taken. Skip it if recent activity suggests the user already did it or is "
    "busy with something that should not be interrupted."
)


# ── stores ───────────────────────────────────────────────────────────────────
_OBS_LOCK = threading.RLock()      # read-modify-write guards (state_store only
_BRAIN_LOCK = threading.RLock()    # locks individual reads/writes)


def observations_path():
    return workspace_state_path("memory/observations.json")


def brain_path():
    return workspace_state_path("memory/proactivity.json")


def note_observation(kind: str, text: str, ts: float | None = None,
                     meta: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Append one data point to the observation journal — the raw material the
    pattern miners read. Cheap (one JSON read/write), capped, fail-soft."""
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    if not body:
        return None
    entry: dict[str, Any] = {
        "ts": float(time.time() if ts is None else ts),
        "kind": str(kind or "event"),
        "text": body[:300],
    }
    if isinstance(meta, dict) and meta:
        entry["meta"] = meta
    with _OBS_LOCK:
        data = read_json(observations_path(), {"version": 1, "events": []})
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list):
            events = []
        events.append(entry)
        write_json(observations_path(), {"version": 1, "events": events[-OBS_MAX:]})
    return entry


def observations(limit: int = OBS_MAX) -> list[dict[str, Any]]:
    data = read_json(observations_path(), {})
    events = data.get("events") if isinstance(data, dict) else None
    out = [e for e in (events or [])
           if isinstance(e, dict) and e.get("text") and e.get("ts") is not None]
    return out[-max(1, int(limit)):]


def _load_brain() -> dict[str, Any]:
    data = read_json(brain_path(), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    if not isinstance(data.get("muted"), dict):
        data["muted"] = {}
    if not isinstance(data.get("surfaced"), dict):
        data["surfaced"] = {}
    if not isinstance(data.get("decisions"), list):
        data["decisions"] = []
    if not isinstance(data.get("budget"), dict):
        data["budget"] = {}
    return data


def _save_brain(data: dict[str, Any]) -> None:
    write_json(brain_path(), data)


def _journal_decision(event: dict[str, Any], action: str, source: str,
                      confidence: float, reason: str,
                      now: float | None = None) -> None:
    """Record what the judgment layer did and why — the transparency half of
    the trust contract, and context for the next triage call."""
    entry = {
        "ts": float(time.time() if now is None else now),
        "kind": str(event.get("kind") or ""),
        "label": str(event.get("label") or "")[:60],
        "severity": str(event.get("severity") or ""),
        "action": action,          # surfaced | suppressed
        "source": source,          # rule | llm | fallback
        "confidence": round(float(confidence), 2),
        "reason": str(reason or "")[:160],
    }
    with _BRAIN_LOCK:
        brain = _load_brain()
        brain["decisions"].append(entry)
        brain["decisions"] = brain["decisions"][-DECISIONS_MAX:]
        _save_brain(brain)


def recent_decisions(limit: int = 10) -> list[dict[str, Any]]:
    brain = _load_brain()
    return [dict(d) for d in brain["decisions"][-max(1, int(limit)):]]


# ── the LLM plumbing (always optional, always bounded) ───────────────────────

def llm_enabled() -> bool:
    """LLM judgment is opt-out (ORYNN_PROACTIVE_LLM=0) and requires a key —
    without one, every path degrades to the deterministic behavior."""
    flag = (os.getenv("ORYNN_PROACTIVE_LLM") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return any(os.getenv(k) for k in (
        "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "GOOGLE_API_KEY", "GROQ_API_KEY"))


def _default_llm(system: str, prompt: str) -> str:
    """One cheap low-effort call through the existing provider stack (its own
    fallback chain included). Constructed lazily so importing this module
    never drags in httpx/provider machinery."""
    from .providers import PlannerProvider, effort_model
    provider = PlannerProvider(model=effort_model("low"))
    try:
        return provider._call_llm(system, prompt)
    finally:
        provider.close()


def _call_with_timeout(fn: Callable[[str, str], str], system: str, prompt: str,
                       timeout_s: float) -> str | None:
    """Bound any LLM call with a hard deadline. A verdict that misses the
    deadline is simply a missing verdict — the caller falls back."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["out"] = fn(system, prompt)
        except Exception as exc:
            box["err"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(max(0.05, timeout_s))
    out = box.get("out")
    return str(out) if out is not None else None


def _parse_verdict(text: str | None) -> dict[str, Any] | None:
    """Extract the first {...} JSON object from a model reply (handles code
    fences and chatter around it). None on anything unusable."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _conf(verdict: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(verdict.get("confidence", 0.0))))
    except Exception:
        return 0.0


# ── inbound: triage of fired events ──────────────────────────────────────────

def _triage_prompt(event: dict[str, Any], now_ts: float) -> str:
    lines = [
        f"Local time: {time.strftime('%A %H:%M', time.localtime(now_ts))}",
        "Event: " + json.dumps({k: event.get(k)
                                for k in ("kind", "label", "severity", "message")}),
    ]
    decisions = recent_decisions(6)
    if decisions:
        lines.append("Recent proactive decisions (do not repeat what was just "
                     "surfaced): " + json.dumps(decisions))
    tail = observations(8)
    if tail:
        lines.append("Recent user activity: " + "; ".join(
            f"[{e.get('kind')}] {str(e.get('text'))[:80]}" for e in tail))
    try:
        from . import knowledge
        block = knowledge.as_prompt_block(str(event.get("message") or ""), limit=8)
        if block:
            lines.append(block)
    except Exception:
        pass
    lines.append("Respond with ONLY the JSON object.")
    return "\n\n".join(lines)


def _apply_guardrails(event: dict[str, Any], verdict: dict[str, Any] | None,
                      ) -> tuple[dict[str, Any], str, str, float, str]:
    """Turn a raw model verdict into a safe decision. Returns
    (final_event, action, source, confidence, reason). The rules here are the
    leash: no escalation to critical, suppression only with confidence, the
    original event as the floor whenever the verdict is unusable."""
    if not isinstance(verdict, dict):
        return dict(event), "surfaced", "fallback", 0.0, "triage unavailable"
    conf = _conf(verdict)
    reason = re.sub(r"\s+", " ", str(verdict.get("reason") or "")).strip()[:160]
    if verdict.get("surface") is False:
        if conf >= MIN_SUPPRESS_CONF:
            return dict(event), "suppressed", "llm", conf, reason
        return dict(event), "surfaced", "fallback", conf, \
            "suppress verdict below confidence gate"
    out = dict(event)
    sev = str(verdict.get("severity") or "").strip().lower()
    if sev in ("info", "notice"):        # never critical — voice stays rule-earned
        out["severity"] = sev
    msg = re.sub(r"\s+", " ", str(verdict.get("message") or "")).strip()
    if 0 < len(msg) <= 240:
        out["message"] = msg
    sug = re.sub(r"\s+", " ", str(verdict.get("suggestion") or "")).strip()
    if sug:
        out["suggestion"] = sug[:200]
    return out, "surfaced", "llm", conf, reason


def decide(event: dict[str, Any], render: Callable[[dict[str, Any]], None], *,
           llm: Callable[[str, str], str] | None = None,
           now: float | None = None, block: bool = False,
           timeout_s: float = TRIAGE_TIMEOUT_S) -> None:
    """Route one fired event through the judgment layer, then hand the
    (possibly refined) event to ``render`` — or suppress it. Never raises;
    never calls ``render`` more than once.

    ``critical`` renders immediately and untouched — the rule path. Everything
    else is triaged on a background thread (``block=True`` runs inline for
    tests), with the original event as the fallback for every failure mode.
    """
    def safe_render(e: dict[str, Any]) -> None:
        try:
            render(e)
        except Exception:
            pass                    # a bad renderer never propagates (and the
                                    # fallback below must not render twice)

    try:
        ev = dict(event or {})
        now_ts = time.time() if now is None else float(now)
        if str(ev.get("kind") or "") != "suggestion":
            try:
                note_observation(
                    "watcher",
                    f"{ev.get('label') or ev.get('kind')}: {ev.get('message', '')}",
                    ts=now_ts)
            except Exception:
                pass
        severity = str(ev.get("severity") or "notice").lower()
        if severity == "critical":
            try:
                _journal_decision(ev, "surfaced", "rule", 1.0,
                                  "critical bypasses triage", now=now_ts)
            except Exception:
                pass
            safe_render(ev)
            return
        use_llm = llm if llm is not None else \
            (_default_llm if llm_enabled() else None)
        if use_llm is None:
            try:
                _journal_decision(ev, "surfaced", "fallback", 0.0,
                                  "llm judgment unavailable", now=now_ts)
            except Exception:
                pass
            safe_render(ev)
            return

        def worker() -> None:
            try:
                text = _call_with_timeout(
                    use_llm, TRIAGE_SYSTEM, _triage_prompt(ev, now_ts), timeout_s)
                verdict = _parse_verdict(text)
            except Exception:
                verdict = None
            final, action, source, conf, reason = _apply_guardrails(ev, verdict)
            try:
                _journal_decision(final, action, source, conf, reason, now=now_ts)
            except Exception:
                pass
            if action == "surfaced":
                safe_render(final)

        if block:
            worker()
        else:
            threading.Thread(target=worker, name="proactivity-triage",
                             daemon=True).start()
    except Exception:
        # Something upstream of rendering broke (bad event dict, dead store):
        # the floor is still "the user hears about it".
        safe_render(dict(event or {}))


# ── outbound: mining the user's own history for triggers ─────────────────────

def _norm_goal(text: str) -> str:
    try:
        from .promotion import normalize_goal
        return normalize_goal(text)
    except Exception:
        return ""


def _local_day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _local_hour(ts: float) -> float:
    lt = time.localtime(ts)
    return lt.tm_hour + lt.tm_min / 60.0


def _hour_dist(a: float, b: float) -> float:
    d = abs(a - b) % 24.0
    return min(d, 24.0 - d)


def _circular_hour_stats(hours: list[float]) -> tuple[float, float]:
    """Mean hour-of-day and mean deviation, on the 24 h circle (so a 23:30 /
    00:30 habit averages to midnight, not lunchtime)."""
    angles = [h * math.tau / 24.0 for h in hours]
    x = sum(math.cos(a) for a in angles) / len(angles)
    y = sum(math.sin(a) for a in angles) / len(angles)
    center = (math.atan2(y, x) % math.tau) * 24.0 / math.tau
    spread = sum(_hour_dist(h, center) for h in hours) / len(hours)
    return center, spread


def _task_history(events: list[dict[str, Any]]) -> list[tuple[float, str, str]]:
    """(ts, normalized_goal, raw_text) for every completed-task observation,
    oldest first."""
    out = []
    for e in events:
        if e.get("kind") != "task":
            continue
        goal = _norm_goal(str(e.get("text") or ""))
        if goal:
            out.append((float(e["ts"]), goal, str(e.get("text"))[:200]))
    out.sort(key=lambda t: t[0])
    return out


def mine_patterns(events: list[dict[str, Any]] | None = None,
                  now: float | None = None) -> list[dict[str, Any]]:
    """Deterministic pattern mining over the observation journal. Pure math —
    no LLM (judgment about surfacing comes later). Returns suggestion dicts:
    {key, kind, goal, text, confidence}, at most one per goal."""
    now_ts = time.time() if now is None else float(now)
    evs = observations() if events is None else events
    tasks = _task_history(evs)
    if not tasks:
        return []
    by_goal: dict[str, list[tuple[float, str]]] = {}
    for ts, goal, raw in tasks:
        by_goal.setdefault(goal, []).append((ts, raw))

    found: list[dict[str, Any]] = []
    today = _local_day(now_ts)
    now_hour = _local_hour(now_ts)

    for goal, items in by_goal.items():
        raw = items[-1][1]
        # habit: same thing, same time of day, several distinct days — and we
        # are inside that window right now, and it hasn't been done today.
        days = {_local_day(ts) for ts, _ in items}
        if len(items) >= 3 and len(days) >= HABIT_MIN_DAYS:
            center, spread = _circular_hour_stats([_local_hour(ts) for ts, _ in items])
            if (spread <= HABIT_SPREAD_H
                    and _hour_dist(now_hour, center) <= HABIT_FIRE_WINDOW_H
                    and today not in days):
                found.append({
                    "key": f"habit:{goal}", "kind": "habit", "goal": raw,
                    "confidence": round(min(0.95, 0.45 + 0.1 * len(days)), 2),
                    "text": f"Around this time you usually “{raw}”. "
                            "Want me to do that now?",
                })
                continue                     # one suggestion per goal, habit wins
        # staleness: an established cadence that's now well overdue.
        if len(items) >= STALE_MIN_COUNT:
            ts_list = sorted(ts for ts, _ in items)
            intervals = [b - a for a, b in zip(ts_list, ts_list[1:])]
            median = statistics.median(intervals)
            gap = now_ts - ts_list[-1]
            if median >= STALE_MIN_INTERVAL_S and gap >= STALE_OVERDUE_FACTOR * median:
                gap_days = max(1, int(gap // 86400))
                usual_days = max(1, round(median / 86400))
                found.append({
                    "key": f"stale:{goal}", "kind": "stale", "goal": raw,
                    "confidence": round(min(0.9, 0.55 + 0.05 * len(items)), 2),
                    "text": f"It's been about {gap_days} day(s) since you last "
                            f"“{raw}” — you usually do it every "
                            f"~{usual_days} day(s). Want me to do it now?",
                })

    # sequences: B keeps following A within the window, A just happened, and
    # B hasn't happened since (if it had, B would be the latest task).
    pair: dict[tuple[str, str], dict[str, Any]] = {}
    for (ts_a, goal_a, raw_a), (ts_b, goal_b, raw_b) in zip(tasks, tasks[1:]):
        if goal_a != goal_b and 0 < ts_b - ts_a <= SEQ_WINDOW_S:
            rec = pair.setdefault((goal_a, goal_b),
                                  {"count": 0, "a_raw": raw_a, "b_raw": raw_b})
            rec["count"] += 1
            rec["a_raw"], rec["b_raw"] = raw_a, raw_b
    last_ts, last_goal, _last_raw = tasks[-1]
    if now_ts - last_ts <= SEQ_WINDOW_S:
        for (goal_a, goal_b), rec in pair.items():
            if goal_a == last_goal and rec["count"] >= SEQ_MIN_COUNT:
                found.append({
                    "key": f"seq:{goal_a}>{goal_b}", "kind": "sequence",
                    "goal": rec["b_raw"],
                    "confidence": round(min(0.9, 0.5 + 0.1 * rec["count"]), 2),
                    "text": f"You usually “{rec['b_raw']}” after "
                            f"“{rec['a_raw']}”. Want me to do that now?",
                })

    # at most one suggestion per goal text, strongest first
    best: dict[str, dict[str, Any]] = {}
    for s in found:
        cur = best.get(s["goal"])
        if cur is None or s["confidence"] > cur["confidence"]:
            best[s["goal"]] = s
    return sorted(best.values(), key=lambda s: s["confidence"], reverse=True)


# ── the suggestion pipeline: gates, budget, consent, feedback ────────────────

def _suggestions_pref_enabled() -> bool:
    try:
        from . import preferences
        return bool(preferences.get_all().get("proactive_suggestions", True))
    except Exception:
        return True


def pending_suggestions(now: float | None = None,
                        events: list[dict[str, Any]] | None = None,
                        ) -> list[dict[str, Any]]:
    """Mined patterns that survive every deterministic gate: confidence floor,
    mute list, per-key cooldown, ignored-too-often sleep, and the daily
    budget. What comes out is allowed to be offered — not yet offered."""
    now_ts = time.time() if now is None else float(now)
    mined = mine_patterns(events, now_ts)
    if not mined:
        return []
    with _BRAIN_LOCK:
        brain = _load_brain()
        muted = brain["muted"]
        surfaced = brain["surfaced"]
        budget = brain["budget"]
    today = _local_day(now_ts)
    used = int(budget.get("used", 0)) if budget.get("date") == today else 0
    room = max(0, SUGGEST_DAILY_BUDGET - used)
    if room == 0:
        return []
    out = []
    for s in mined:
        if s["confidence"] < MIN_SUGGEST_CONF:
            continue
        key = s["key"]
        until = muted.get(key)
        if until is not None and (float(until) < 0 or float(until) > now_ts):
            continue
        rec = surfaced.get(key) or {}
        last = float(rec.get("last_ts", 0.0))
        if last and now_ts - last < SUGGEST_COOLDOWN_S:
            continue
        if int(rec.get("ignored", 0)) >= IGNORED_MUTE_AFTER \
                and last and now_ts - last < IGNORED_SLEEP_S:
            continue
        out.append(s)
        if len(out) >= room:
            break
    return out


def _mark_surfaced(key: str, now_ts: float, counted: bool) -> None:
    with _BRAIN_LOCK:
        brain = _load_brain()
        rec = brain["surfaced"].setdefault(key, {})
        rec["last_ts"] = now_ts
        rec["count"] = int(rec.get("count", 0)) + 1
        if counted:
            # "ignored" = surfacings since the last acceptance; reset by
            # record_feedback(accepted=True).
            rec["ignored"] = int(rec.get("ignored", 0)) + 1
            today = _local_day(now_ts)
            budget = brain["budget"]
            if budget.get("date") != today:
                budget["date"], budget["used"] = today, 0
            budget["used"] = int(budget.get("used", 0)) + 1
        _save_brain(brain)


def record_feedback(key: str, accepted: bool, now: float | None = None) -> None:
    """The learning half of consent: a yes resets the ignore counter (and is
    the signal a habit is real); a no puts the suggestion to sleep for a week."""
    now_ts = time.time() if now is None else float(now)
    with _BRAIN_LOCK:
        brain = _load_brain()
        rec = brain["surfaced"].setdefault(key, {})
        if accepted:
            rec["ignored"] = 0
            rec["accepted"] = int(rec.get("accepted", 0)) + 1
        else:
            brain["muted"][key] = now_ts + IGNORED_SLEEP_S
        _save_brain(brain)


def mute(key: str, forever: bool = True, now: float | None = None) -> None:
    now_ts = time.time() if now is None else float(now)
    with _BRAIN_LOCK:
        brain = _load_brain()
        brain["muted"][key] = -1.0 if forever else now_ts + IGNORED_SLEEP_S
        _save_brain(brain)


def unmute(key: str) -> None:
    with _BRAIN_LOCK:
        brain = _load_brain()
        brain["muted"].pop(key, None)
        _save_brain(brain)


def emit_due_suggestions(on_event: Callable[[dict[str, Any]], None], *,
                         llm: Callable[[str, str], str] | None = None,
                         now: float | None = None,
                         events: list[dict[str, Any]] | None = None,
                         timeout_s: float = TRIAGE_TIMEOUT_S,
                         ) -> list[dict[str, Any]]:
    """One mining pass: surface every suggestion that clears the gates, each
    optionally judged/phrased by the LLM first. Suggestions are emitted as
    info-severity events on the same ladder watchers use — silent glow +
    toast, never voice."""
    if not _suggestions_pref_enabled():
        return []
    now_ts = time.time() if now is None else float(now)
    due = pending_suggestions(now_ts, events)
    if not due:
        return []
    use_llm = llm if llm is not None else \
        (_default_llm if llm_enabled() else None)
    emitted = []
    for s in due:
        message = s["text"]
        if use_llm is not None:
            verdict = None
            try:
                prompt = (
                    f"Local time: {time.strftime('%A %H:%M', time.localtime(now_ts))}\n"
                    f"Candidate ({s['kind']}, mined confidence "
                    f"{s['confidence']}): {s['text']}\n"
                    "Recent user activity: " + "; ".join(
                        f"[{e.get('kind')}] {str(e.get('text'))[:80]}"
                        for e in (events or observations(8))[-8:])
                    + "\n\nRespond with ONLY the JSON object.")
                verdict = _parse_verdict(
                    _call_with_timeout(use_llm, SUGGEST_SYSTEM, prompt, timeout_s))
            except Exception:
                verdict = None
            if isinstance(verdict, dict):
                if verdict.get("surface") is False \
                        and _conf(verdict) >= MIN_SUPPRESS_CONF:
                    # vetoed: starts the cooldown (so we don't re-ask the model
                    # every cycle) but consumes no budget and no ignore strike.
                    _mark_surfaced(s["key"], now_ts, counted=False)
                    _journal_decision(
                        {"kind": "suggestion", "label": s["kind"],
                         "severity": "info"},
                        "suppressed", "llm", _conf(verdict),
                        str(verdict.get("reason") or ""), now=now_ts)
                    continue
                better = re.sub(r"\s+", " ",
                                str(verdict.get("message") or "")).strip()
                if 0 < len(better) <= 240:
                    message = better
        event = {
            "id": uuid.uuid4().hex,
            "ts": now_ts,
            "kind": "suggestion",
            "label": s["kind"],
            "severity": "info",           # offers never chime, never speak
            "message": message,
            "suggestion_key": s["key"],
            "confidence": s["confidence"],
        }
        _mark_surfaced(s["key"], now_ts, counted=True)
        _journal_decision(event, "surfaced", "llm" if use_llm else "rule",
                          s["confidence"], f"mined {s['kind']} pattern",
                          now=now_ts)
        try:
            on_event(dict(event))
        except Exception:
            pass
        emitted.append(event)
    return emitted


def start_suggestion_daemon(on_event: Callable[[dict[str, Any]], None], *,
                            interval_s: float = DAEMON_INTERVAL_S,
                            llm: Callable[[str, str], str] | None = None,
                            stop_event: threading.Event | None = None,
                            ) -> threading.Event:
    """Background mining loop (same in-process daemon pattern as the watcher
    engine). Returns the stop event. A cycle that explodes is skipped, never
    fatal — proactivity must never take the app down."""
    stop = stop_event or threading.Event()

    def run() -> None:
        while not stop.wait(max(60.0, float(interval_s))):
            try:
                emit_due_suggestions(on_event, llm=llm)
            except Exception:
                pass

    threading.Thread(target=run, name="proactivity-suggestions",
                     daemon=True).start()
    return stop
