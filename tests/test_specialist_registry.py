"""WS2/WS8: specialist registry and exclusion groups."""
from app.specialists.loader import function_declarations_from_registry, load_specialist_registry
from app.specialists.registry import EXCLUSION_GROUPS, builtin_specialists


def test_registry_loads_builtin_specialists():
    specs = load_specialist_registry()
    names = {s.name for s in specs}
    assert {"launch", "uia_act", "vision_peek", "desktop_job"}.issubset(names)


def test_exclusion_groups_cover_desktop_tools():
    desktop = EXCLUSION_GROUPS["desktop"]
    assert "desktop_control" in desktop
    assert "start_desktop_task" in desktop
    assert "launch_app" in desktop


def test_declarations_include_launch_app():
    class T:
        class FunctionDeclaration:
            def __init__(self, **kw):
                self.name = kw.get("name")

    decls = function_declarations_from_registry(T)
    names = [getattr(d, "name", "") for d in decls]
    assert "launch_app" in names
    assert "look_at_screen" in names


def test_specialist_live_tool_mapping():
    by_tool = {s.live_tool_name: s for s in builtin_specialists()}
    assert by_tool["desktop_control"].name == "uia_act"
    assert by_tool["look_at_screen"].readonly is True
