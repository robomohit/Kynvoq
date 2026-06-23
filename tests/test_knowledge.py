"""Orynn knowledge memory: durable facts (teach + auto-learn), relevance, forget."""
import importlib


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ORYNN_WORKSPACE", str(tmp_path))
    import app.knowledge as k
    importlib.reload(k)
    return k


def test_add_and_relevant(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    k.add_fact("cowork is the button at the top-right of the dashboard", app="Orynn dashboard")
    k.add_fact("my main project is the anime edit channel")
    rel = k.relevant("click the cowork button")
    assert rel and "cowork" in rel[0]["text"].lower()
    assert rel[0]["app"] == "Orynn dashboard"


def test_dedupe_refreshes_not_duplicates(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    k.add_fact("cowork is top-right")
    k.add_fact("cowork is top-right")  # identical -> de-duped
    assert len([f for f in k.all_facts() if f["text"] == "cowork is top-right"]) == 1


def test_forget(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    k.add_fact("cowork is the top-right button")
    k.add_fact("the budget sheet lives in Documents")
    assert k.forget("cowork") == 1
    assert all("cowork" not in f["text"].lower() for f in k.all_facts())


def test_prompt_block_groups_by_owner(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    assert k.as_prompt_block() == ""  # nothing known yet -> no block
    k.add_fact("always confirm before sending", owner="user", category="rule")
    k.add_fact("slack is pinned on the taskbar", owner="assistant", category="location")
    block = k.as_prompt_block()
    assert "ORYNN MEMORY" in block
    assert "What the user has told you" in block and "[rule] always confirm" in block
    assert "What you've learned" in block and "slack is pinned" in block


def test_owner_and_category_stored(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    f = k.add_fact("cowork is top-right", owner="assistant", category="location", app="dashboard")
    assert f["owner"] == "assistant" and f["category"] == "location" and f["app"] == "dashboard"
    # bad owner falls back to "user"
    f2 = k.add_fact("x", owner="bogus")
    assert f2["owner"] == "user"


def test_migrates_legacy_source_field(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    # simulate an old-format file (source instead of owner/category)
    from app.state_store import write_json
    write_json(k.store_path(), [{"id": "old1", "text": "legacy learned fact",
                                 "source": "learned", "created_at": 1.0}])
    facts = k.all_facts()
    assert facts[0]["owner"] == "assistant" and facts[0]["category"] == "fact"


def test_empty_text_ignored(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    assert k.add_fact("   ") is None
    assert k.all_facts() == []


def test_relevant_falls_back_to_recent_without_overlap(tmp_path, monkeypatch):
    k = _fresh(tmp_path, monkeypatch)
    k.add_fact("alpha fact one")
    k.add_fact("beta fact two")
    # query with no keyword overlap still returns recent facts (always some context)
    rel = k.relevant("zzzzz nothing matches")
    assert len(rel) == 2
