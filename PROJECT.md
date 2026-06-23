# Project: Orynn E2E Reliability

## Architecture
- Orynn is a voice-controlled desktop AI agent.
- Main entry points are `run_desktop.py`, `app/main.py`.
- Modules involved:
  - `app/widget/gemini_live.py`: Manages the Gemini Live WebSockets connection and audio loop.
  - `app/tools.py` & `app/widget/desktop_features.py`: Underpinning UI automation click, type, and resolution logic via UIA.
  - `app/widget/textbox_overlay.py`: Overlay state and user interaction status tracking.
  - `app/providers.py`: Integrations with external LLM providers (Google, Groq, OpenRouter).

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | E2E Testing Track | Define feature inventory and write 4-tier E2E tests | None | IN_PROGRESS (Conv ID: d88c5011-cfb6-42db-a286-918a3bb5d7be) |
| 2 | Milestone 1 (R1) | Gemini Live Connection Robustness & Autoreconnect | None | IN_PROGRESS (Conv ID: 7ab40ff8-ef12-4da1-adc5-d9b4b35c336d) |
| 3 | Milestone 2 (R2) | Resilient UIA Click/Type Verification & Self-Healing | None | IN_PROGRESS (Conv ID: ba8e9013-346b-4a43-afa1-626722f8b5b3) |
| 4 | Milestone 3 (R3) | Resilient Overlay State Tracking | None | IN_PROGRESS (Conv ID: dff33f09-db2a-4e96-b95c-dd73e5878c7b) |
| 5 | Milestone 4 (R4) | Unified LLM API Timeout & Retry Resilience | None | IN_PROGRESS (Conv ID: 9f87b0d2-a91a-4422-9c23-727f736fabb4) |
| 6 | Milestone 5 (Final) | Integrate, pass 100% of E2E tests, and perform adversarial hardening | M1, M2, M3, M4, E2E | PLANNED |

## Interface Contracts
- No new module boundaries are introduced.
- Standard signatures of existing APIs (`gemini_live.py`, `tools.py`, `textbox_overlay.py`, `providers.py`) must be preserved to maintain backward compatibility and avoid integration regressions.

## Code Layout
- `app/`: Source code directory.
- `tests/`: Project tests directory.
- `.agents/`: Subagent metadata directory.
