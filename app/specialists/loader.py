"""Load specialist registry and generate Gemini Live declarations (WS2)."""
from __future__ import annotations

from typing import Any

from .registry import SpecialistSpec, builtin_specialists


def load_specialist_registry() -> list[SpecialistSpec]:
    return list(builtin_specialists())


def function_declarations_from_registry(types: Any) -> list[Any]:
    """Generate Live function declarations from registry (delegates to gemini_live)."""
    from app.widget.gemini_live import _function_declarations

    return _function_declarations(types)
