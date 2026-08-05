"""Always-on awareness — deterministic watchers, zero LLM in the loop.

Orynn's proactive layer follows the same doctrine as the Golden Five: a FEW
concrete primitives that never surprise you. A watcher is a dumb, cheap,
rule-based sensor (CPU pegged, disk nearly full, battery dying, a process
vanished, a download landed). The polling loop samples the machine ONCE per
tick and evaluates every watcher against that shared snapshot — no model, no
network, no guessing. Intelligence only wakes AFTER a trigger fires, and even
then the message the user sees is a deterministic template.

Trust contract (the alert-fatigue guards, all enforced here):
* every watcher has a cooldown AND must re-arm (condition observed false)
  before it may fire again — a pegged CPU fires once, not every 5 seconds;
* severity is decided by rule, not vibes: ``info`` < ``notice`` < ``critical``.
  The output ladder (glow → chime+toast → voice) maps onto these; only
  ``critical`` may ever reach the voice rung;
* the tick has a hard time budget — awareness must never become a tax.

Watchers are persisted in ``watchers.json`` (same atomic store as scheduled
recipes) so voice-created watchers survive restarts. This is the input-side
half of "grow with the user": Orynn starts with a handful of built-in senses
and gains new ones only when the user asks for them.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .state_store import read_json, workspace_state_path, write_json

SEVERITIES = ("info", "notice", "critical")

TICK_BUDGET_SECONDS = 1.0     # hard cap for one full evaluation pass
DEFAULT_POLL_SECONDS = 5.0
DEFAULT_COOLDOWN_S = 900      # 15 min between repeat fires of one watcher
MAX_RECENT_EVENTS = 50

# Watcher kinds: {kind: (default params, default severity, one-line help)}.
# Params are validated in add(); anything unknown is rejected loudly at
# creation time so a bad voice command can never plant a silently-dead sensor.
KINDS: dict[str, dict[str, Any]] = {
    "cpu_load": {
        "params": {"threshold_pct": 90.0, "sustain_s": 180.0},
        "severity": "notice",
        "help": "CPU stays above threshold_pct for sustain_s seconds",
    },
    "memory_low": {
        "params": {"threshold_pct": 5.0},
        "severity": "notice",
        "help": "available RAM drops below threshold_pct percent",
    },
    "disk_low": {
        "params": {"drive": "C:\\", "min_free_gb": 10.0, "critical_free_gb": 2.0},
        "severity": "notice",
        "help": "free space on drive drops below min_free_gb",
    },
    "battery_low": {
        "params": {"threshold_pct": 20.0, "critical_pct": 8.0},
        "severity": "notice",
        "help": "battery below threshold_pct while discharging",
    },
    "process_exit": {
        "params": {"name": ""},
        "severity": "notice",
        "help": "a process whose name contains `name` disappears",
    },
    "process_start": {
        "params": {"name": ""},
        "severity": "info",
        "help": "a process whose name contains `name` appears",
    },
    "new_download": {
        "params": {"folder": ""},   # empty → the user's Downloads folder
        "severity": "info",
        "help": "a new finished file appears in the folder",
    },
}

_PARTIAL_SUFFIXES = (".crdownload", ".part", ".tmp", ".partial", ".download")


def watchers_path() -> Path:
    return workspace_state_path("watchers.json")


def _downloads_dir() -> str:
    return str(Path.home() / "Downloads")


def take_snapshot() -> dict[str, Any]:
    """One machine-state sampling pass shared by every watcher this tick
    (per-watcher sampling multiplied the cost for nothing — same trick as the
    verifier's shared window enumeration). Every field is best-effort: a
    sensor that can't be read is None, and watchers that need it stay idle
    rather than fire on garbage."""
    snap: dict[str, Any] = {
        "cpu_pct": None,
        "mem_avail_pct": None,
        "disks": {},          # {"C:\\": free_gb}
        "battery": None,      # {"pct": float, "plugged": bool}
        "process_names": None,  # set[str], lowercase
    }
    try:
        import psutil
    except Exception:
        return snap
    try:
        # interval=None → average since the previous call: free at a 5s cadence.
        snap["cpu_pct"] = float(psutil.cpu_percent(interval=None))
    except Exception:
        pass
    try:
        vm = psutil.virtual_memory()
        snap["mem_avail_pct"] = float(vm.available) * 100.0 / float(vm.total)
    except Exception:
        pass
    try:
        batt = psutil.sensors_battery()
        if batt is not None:
            snap["battery"] = {"pct": float(batt.percent),
                               "plugged": bool(batt.power_plugged)}
    except Exception:
        pass
    try:
        names = set()
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name:
                names.add(name)
        snap["process_names"] = names
    except Exception:
        pass
    return snap


def _disk_free_gb(snap: dict[str, Any], drive: str) -> float | None:
    """Disk usage is sampled lazily per drive (only drives someone watches)."""
    disks = snap.setdefault("disks", {})
    if drive in disks:
        return disks[drive]
    free_gb: float | None = None
    try:
        import psutil
        free_gb = psutil.disk_usage(drive).free / (1024 ** 3)
    except Exception:
        pass
    disks[drive] = free_gb
    return free_gb


def _match_process(names: set[str] | None, fragment: str) -> bool | None:
    if names is None:
        return None
    frag = fragment.strip().lower()
    if not frag:
        return None
    return any(frag in n for n in names)


def evaluate(watcher: dict[str, Any], snap: dict[str, Any],
             state: dict[str, Any], now: float) -> dict[str, Any] | None:
    """Evaluate one watcher against the shared snapshot. Pure decision logic:
    returns an event dict when the condition FIRES, else None. ``state`` is the
    watcher's private runtime scratch (armed flags, sustain timers) mutated in
    place; ``now`` is a monotonic clock so tests can drive time."""
    kind = watcher.get("kind")
    params = watcher.get("params") or {}
    severity = watcher.get("severity") or "notice"

    def fire(message: str, sev: str | None = None) -> dict[str, Any]:
        return {
            "watcher_id": watcher.get("id"),
            "kind": kind,
            "label": watcher.get("label") or kind,
            "severity": sev or severity,
            "message": message,
        }

    if kind == "cpu_load":
        pct = snap.get("cpu_pct")
        if pct is None:
            return None
        threshold = float(params.get("threshold_pct", 90.0))
        sustain = float(params.get("sustain_s", 180.0))
        if pct < threshold:
            state.pop("above_since", None)
            state["armed"] = True
            return None
        since = state.setdefault("above_since", now)
        if now - since >= sustain and state.get("armed", True):
            state["armed"] = False
            return fire(f"CPU has been above {threshold:.0f}% for "
                        f"{int(sustain // 60) or 1} minutes (now {pct:.0f}%).")
        return None

    if kind == "memory_low":
        avail = snap.get("mem_avail_pct")
        if avail is None:
            return None
        threshold = float(params.get("threshold_pct", 5.0))
        if avail > threshold:
            state["armed"] = True
            return None
        if state.get("armed", True):
            state["armed"] = False
            return fire(f"Memory is nearly full — only {avail:.1f}% available.")
        return None

    if kind == "disk_low":
        drive = str(params.get("drive") or "C:\\")
        free_gb = _disk_free_gb(snap, drive)
        if free_gb is None:
            return None
        threshold = float(params.get("min_free_gb", 10.0))
        critical_at = float(params.get("critical_free_gb", 2.0))
        if free_gb > threshold:
            state["armed"] = True
            return None
        if state.get("armed", True):
            state["armed"] = False
            sev = "critical" if free_gb <= critical_at else None
            return fire(f"Drive {drive} is down to {free_gb:.1f} GB free.", sev)
        return None

    if kind == "battery_low":
        batt = snap.get("battery")
        if not batt:
            return None
        threshold = float(params.get("threshold_pct", 20.0))
        critical_at = float(params.get("critical_pct", 8.0))
        if batt["plugged"] or batt["pct"] > threshold:
            state["armed"] = True
            return None
        if state.get("armed", True):
            state["armed"] = False
            sev = "critical" if batt["pct"] <= critical_at else None
            return fire(f"Battery at {batt['pct']:.0f}% and unplugged.", sev)
        return None

    if kind in ("process_exit", "process_start"):
        present = _match_process(snap.get("process_names"), str(params.get("name") or ""))
        if present is None:
            return None
        was_present = state.get("present")
        state["present"] = present
        if was_present is None:              # first observation only arms
            return None
        name = str(params.get("name") or "").strip()
        if kind == "process_exit" and was_present and not present:
            return fire(f"Process '{name}' has exited.")
        if kind == "process_start" and not was_present and present:
            return fire(f"Process '{name}' has started.")
        return None

    if kind == "new_download":
        folder = str(params.get("folder") or "") or _downloads_dir()
        try:
            entries = {}
            with os.scandir(folder) as it:
                for entry in it:
                    if not entry.is_file():
                        continue
                    if entry.name.lower().endswith(_PARTIAL_SUFFIXES):
                        continue
                    stat = entry.stat()
                    entries[entry.name] = stat.st_size
        except OSError:
            return None
        known = state.get("files")
        state["files"] = entries
        if known is None:                    # first scan only baselines
            return None
        fresh = [n for n in entries if n not in known]
        # a file only counts once its size is stable across two ticks —
        # otherwise we announce half-written downloads
        pending = state.setdefault("pending", {})
        ready = [n for n in pending if n in entries and entries[n] == pending[n]]
        state["pending"] = {n: entries[n] for n in fresh}
        if ready:
            shown = ", ".join(sorted(ready)[:3])
            return fire(f"New file in {os.path.basename(folder) or folder}: {shown}")
        return None

    return None


class WatcherEngine:
    """Owns the watcher list, the poll thread, and the fatigue guards.

    ``on_event`` is the single output: the escalation-ladder wiring decides
    what a severity looks/sounds like — the engine only decides WHETHER
    something is worth saying. Snapshot fn and clocks are injectable so tests
    never sleep and never touch real hardware."""

    def __init__(self,
                 on_event: Callable[[dict[str, Any]], None] | None = None,
                 path: Path | None = None,
                 poll_seconds: float = DEFAULT_POLL_SECONDS,
                 snapshot_fn: Callable[[], dict[str, Any]] = take_snapshot,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._on_event = on_event
        self._path = path or watchers_path()
        self._poll_seconds = max(1.0, float(poll_seconds))
        self._snapshot_fn = snapshot_fn
        self._clock = clock
        self._wall = wall
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._last_fired: dict[str, float] = {}
        self._recent: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._watchers: list[dict[str, Any]] = self._load()

    # ------------------------------------------------------------- storage
    def _load(self) -> list[dict[str, Any]]:
        data = read_json(self._path, {"version": 1, "watchers": []})
        items = data.get("watchers") if isinstance(data, dict) else None
        out = []
        for item in items or []:
            if isinstance(item, dict) and item.get("kind") in KINDS and item.get("id"):
                out.append(item)
        return out

    def _save(self) -> None:
        write_json(self._path, {"version": 1, "watchers": self._watchers})

    def ensure_defaults(self) -> None:
        """Seed the built-in senses on first run (marked so a user deletion is
        FINAL — removed defaults are never re-seeded on them)."""
        with self._lock:
            data = read_json(self._path, None)
            if data is not None:      # file exists → user state is authoritative
                return
            for kind in ("cpu_load", "disk_low", "battery_low", "memory_low"):
                spec = KINDS[kind]
                self._watchers.append({
                    "id": uuid.uuid4().hex,
                    "kind": kind,
                    "label": kind.replace("_", " "),
                    "params": dict(spec["params"]),
                    "severity": spec["severity"],
                    "cooldown_s": DEFAULT_COOLDOWN_S,
                    "enabled": True,
                    "builtin": True,
                    "created": self._wall(),
                })
            self._save()

    # ------------------------------------------------------------- CRUD
    def add(self, kind: str, params: dict[str, Any] | None = None,
            label: str = "", severity: str = "",
            cooldown_s: float | None = None) -> dict[str, Any]:
        spec = KINDS.get(kind)
        if spec is None:
            raise ValueError(f"unknown watcher kind '{kind}' "
                             f"(valid: {', '.join(sorted(KINDS))})")
        merged = dict(spec["params"])
        for key, value in (params or {}).items():
            if key not in merged:
                raise ValueError(f"unknown param '{key}' for {kind} "
                                 f"(valid: {', '.join(sorted(merged))})")
            merged[key] = value
        if kind in ("process_exit", "process_start") and not str(merged.get("name") or "").strip():
            raise ValueError(f"{kind} needs a process name")
        sev = (severity or spec["severity"]).lower()
        if sev not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
        watcher = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "label": label.strip() or kind.replace("_", " "),
            "params": merged,
            "severity": sev,
            "cooldown_s": float(cooldown_s if cooldown_s is not None else DEFAULT_COOLDOWN_S),
            "enabled": True,
            "builtin": False,
            "created": self._wall(),
        }
        with self._lock:
            self._watchers.append(watcher)
            self._save()
        return dict(watcher)

    def remove(self, watcher_id: str) -> bool:
        with self._lock:
            before = len(self._watchers)
            self._watchers = [w for w in self._watchers if w.get("id") != watcher_id]
            if len(self._watchers) != before:
                self._states.pop(watcher_id, None)
                self._last_fired.pop(watcher_id, None)
                self._save()
                return True
        return False

    def set_enabled(self, watcher_id: str, enabled: bool) -> bool:
        with self._lock:
            for watcher in self._watchers:
                if watcher.get("id") == watcher_id:
                    watcher["enabled"] = bool(enabled)
                    self._save()
                    return True
        return False

    def list(self) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            out = []
            for watcher in self._watchers:
                item = dict(watcher)
                fired = self._last_fired.get(watcher.get("id", ""))
                cooling = (fired is not None
                           and now - fired < float(watcher.get("cooldown_s", DEFAULT_COOLDOWN_S)))
                item["status"] = ("disabled" if not watcher.get("enabled", True)
                                  else "cooldown" if cooling else "armed")
                out.append(item)
            return out

    def recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._recent[-max(1, int(limit)):]]

    # ------------------------------------------------------------- engine
    def tick(self) -> list[dict[str, Any]]:
        """One evaluation pass over all enabled watchers against one shared
        snapshot, inside a hard time budget. Returns the events fired (also
        dispatched to on_event). This is the whole engine — the thread loop
        just calls it on a cadence."""
        now = self._clock()
        deadline = now + TICK_BUDGET_SECONDS
        snap = self._snapshot_fn()
        fired: list[dict[str, Any]] = []
        with self._lock:
            watchers = [dict(w) for w in self._watchers if w.get("enabled", True)]
        for watcher in watchers:
            if self._clock() > deadline:
                break                       # over budget → rest wait for next tick
            wid = watcher.get("id", "")
            last = self._last_fired.get(wid)
            cooldown = float(watcher.get("cooldown_s", DEFAULT_COOLDOWN_S))
            state = self._states.setdefault(wid, {})
            try:
                event = evaluate(watcher, snap, state, now)
            except Exception:
                continue                    # one broken sensor never kills the loop
            if event is None:
                continue
            if last is not None and now - last < cooldown:
                continue                    # cooling down — condition noted, not announced
            self._last_fired[wid] = now
            event["id"] = uuid.uuid4().hex
            event["ts"] = self._wall()
            fired.append(event)
        if fired:
            with self._lock:
                self._recent.extend(fired)
                del self._recent[:-MAX_RECENT_EVENTS]
        if self._on_event is not None:
            for event in fired:
                try:
                    self._on_event(dict(event))
                except Exception:
                    pass                    # a bad listener never kills the engine
        return fired

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="watcher-engine", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        # prime cpu_percent so the first real tick gets a meaningful average
        try:
            import psutil
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        while not self._stop.wait(self._poll_seconds):
            try:
                self.tick()
            except Exception:
                pass                        # awareness must never crash the app


_ENGINE: WatcherEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> WatcherEngine:
    """Process-wide singleton (matches the scheduled-recipes daemon pattern):
    the overlay/backend wires on_event once at startup via attach_listener."""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = WatcherEngine()
        return _ENGINE


def attach_listener(on_event: Callable[[dict[str, Any]], None]) -> None:
    get_engine()._on_event = on_event
