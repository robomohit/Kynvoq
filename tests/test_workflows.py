"""Orynn workflow memory: save/run-able multi-step procedures, triggers, relevance,
forget, and the validation that keeps a stored workflow runnable."""
import importlib


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ORYNN_WORKSPACE", str(tmp_path))
    import app.workflows as w
    importlib.reload(w)
    return w


_STEPS = [
    {"action": "open", "app": "Chrome"},
    {"action": "click", "target": "New tab", "app": "Chrome"},
    {"action": "type", "text": "hello", "app": "Chrome"},
]


def test_add_and_get(tmp_path, monkeypatch):
    w = _fresh(tmp_path, monkeypatch)
    saved = w.add_workflow("Morning Setup", description="open my stuff",
                           triggers=["morning", "start my day"], steps=_STEPS)
    assert saved and saved["name"] == "morning-setup"
    got = w.get("morning setup")            # loose title match
    assert got and len(got["steps"]) == 3
    assert w.get("morning-setup")["title"] == "Morning Setup"


def test_empty_or_stepless_workflow_rejected(tmp_path, monkeypatch):
    w = _fresh(tmp_path, monkeypatch)
    assert w.add_workflow("", steps=_STEPS) is None          # no name
    assert w.add_workflow("Bad", steps=[]) is None           # no steps
    assert w.add_workflow("Bad", steps=[{"action": "fly"}]) is None  # only junk steps


def test_clean_steps_drops_unknown_actions(tmp_path, monkeypatch):
    w = _fresh(tmp_path, monkeypatch)
    saved = w.add_workflow("Mix", steps=[
        {"action": "click", "target": "OK"},
        {"action": "teleport", "target": "X"},   # unknown -> dropped
        "not a dict",                              # junk -> dropped
        {"action": "wait", "seconds": 99},         # clamped to <=10
    ])
    actions = [s["action"] for s in saved["steps"]]
    assert actions == ["click", "wait"]
    assert saved["steps"][1]["seconds"] == 10.0


def test_relevant_matches_trigger(tmp_path, monkeypatch):
    w = _fresh(tmp_path, monkeypatch)
    w.add_workflow("Post Anime Edit", triggers=["post my edit", "upload"], steps=_STEPS)
    w.add_workflow("Pay Rent", triggers=["rent"], steps=_STEPS)
    hits = w.relevant("can you post my edit")
    assert hits and hits[0]["name"] == "post-anime-edit"


def test_dedupe_overwrites(tmp_path, monkeypatch):
    w = _fresh(tmp_path, monkeypatch)
    w.add_workflow("Setup", steps=_STEPS[:1])
    w.add_workflow("Setup", steps=_STEPS)        # same name -> overwrite, not dup
    same = [x for x in w.all_workflows() if x["name"] == "setup"]
    assert len(same) == 1 and len(same[0]["steps"]) == 3


def test_forget(tmp_path, monkeypatch):
    w = _fresh(tmp_path, monkeypatch)
    w.add_workflow("Morning Setup", steps=_STEPS)
    assert w.forget_workflow("morning") == 1
    assert w.all_workflows() == []


def test_prompt_block_lists_workflows(tmp_path, monkeypatch):
    w = _fresh(tmp_path, monkeypatch)
    assert w.as_prompt_block() == ""             # nothing saved -> no block
    w.add_workflow("Morning Setup", description="open my apps", steps=_STEPS)
    block = w.as_prompt_block()
    assert "run_workflow" in block and "Morning Setup" in block
