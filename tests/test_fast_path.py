import pytest

from app.agent import AgentService


class MockLogEmitter:
    def emit(self, task_id, event, data):
        pass


log_emitter = MockLogEmitter()


class ReactiveOnlyProvider:
    model = "tier:uia"

    def __init__(self):
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self.stream_called = False

    @property
    def total_tokens(self):
        return self._total_input_tokens + self._total_output_tokens

    def _call_llm(self, *args, **kwargs):
        raise AssertionError("desktop routing must not make an upfront planning LLM call")

    def plan_hierarchical(self, *args, **kwargs):
        raise AssertionError("desktop routing must not call the hierarchical planner upfront")

    async def stream_chat_with_tools(self, system, messages, tools, screenshot_b64=None):
        self.stream_called = True
        yield {
            "type": "tool_call",
            "id": "finish-call",
            "name": "finish",
            "args": {"reason": "done"},
            "thought": "done",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("complexity", ["atomic", "complex"])
async def test_desktop_tasks_stream_without_upfront_planning(monkeypatch, workspace, complexity):
    service = AgentService(workspace, log_emitter=log_emitter)
    provider = ReactiveOnlyProvider()

    monkeypatch.setattr("app.agent.PlannerProvider", lambda model=None: provider)
    monkeypatch.setattr("app.agent.classify_task_complexity", lambda goal: complexity)
    monkeypatch.setattr("app.agent.is_vision_model", lambda model: False)
    monkeypatch.setattr(service.memory, "search", lambda goal, limit=5: [])
    monkeypatch.setattr(service.memory, "recall_sessions", lambda goal, limit=5: [])

    # NB: a bare "open <app>" now takes the deterministic launch fast-path (no LLM),
    # so use a multi-step desktop goal to exercise the streaming-without-planning path.
    await service.run_task("desktop-reactive", "Type a quick note into Notepad", mode="computer")

    assert provider.stream_called is True


@pytest.mark.asyncio
async def test_open_app_uses_deterministic_fast_path_no_llm(monkeypatch, workspace):
    """A pure 'open <known app>' command must run the deterministic launcher and
    finish WITHOUT ever invoking the LLM planner — that's what makes it ~10x faster
    and immune to the planner mis-reporting 'done' before the window exists."""
    from app.models import ToolResult

    service = AgentService(workspace, log_emitter=log_emitter)
    provider = ReactiveOnlyProvider()
    monkeypatch.setattr("app.agent.PlannerProvider", lambda model=None: provider)
    monkeypatch.setattr(service.memory, "search", lambda goal, limit=5: [])
    monkeypatch.setattr(service.memory, "recall_sessions", lambda goal, limit=5: [])
    monkeypatch.setattr(service, "_finalize", lambda *a, **k: None)

    opened = {}

    def fake_open(self, command, title, timeout=12.0):
        opened["command"], opened["title"] = command, title
        return ToolResult(ok=True, output=f"Window ready: '{title}'")

    monkeypatch.setattr("app.tools.ToolExecutor.open_known_app", fake_open)

    events = []

    async def capture(task_id, event_type, data):
        events.append((event_type, data))

    monkeypatch.setattr(service, "_emit", capture)

    await service.run_task("fastpath-open", "open notepad", mode="computer")

    # The LLM planner was never touched...
    assert provider.stream_called is False
    # ...the deterministic launcher ran for the right app...
    assert opened == {"command": "start notepad", "title": "Notepad"}
    # ...and the task finished successfully.
    done = [d for e, d in events if e == "done"]
    assert done and done[-1]["complete"] is True


@pytest.mark.asyncio
async def test_isolated_desktop_tasks_stream_without_upfront_planning(monkeypatch, workspace):
    service = AgentService(workspace, log_emitter=log_emitter)
    provider = ReactiveOnlyProvider()

    monkeypatch.setattr("app.agent.PlannerProvider", lambda model=None: provider)
    monkeypatch.setattr("app.agent.classify_task_complexity", lambda goal: "atomic")
    monkeypatch.setattr("app.agent.is_vision_model", lambda model: False)
    monkeypatch.setattr("app.agent._get_hwnd_for_title", lambda title: None)
    monkeypatch.setattr(service.memory, "search", lambda goal, limit=5: [])
    monkeypatch.setattr(service.memory, "recall_sessions", lambda goal, limit=5: [])

    await service.run_task(
        "isolated-reactive",
        "Open Notepad",
        mode="computer_isolated",
        isolated_app="Notepad",
    )

    assert provider.stream_called is True
