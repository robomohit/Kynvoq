# Scope: E2E Testing Track

## Architecture
- The E2E Testing Track creates a requirement-driven, opaque-box test suite for Orynn.
- Target features:
  1. Gemini Live connection robustness and autoreconnect (R1).
  2. Resilient UIA click & verification self-healing (R2 click).
  3. Resilient UIA type & elements resolution self-healing (R2 type/find).
  4. Resilient textbox overlay task/cursor state tracking (R3).
  5. Unified LLM API timeout & retry resilience (R4).
- Tests must execute independently of active external APIs and Windows UI by mocking/simulating these layers.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Test Infra & Mocks | Implement test mocks (WebSockets, HTTP client, UIA/OCR) and write TEST_INFRA.md | None | IN_PROGRESS |
| 2 | Tier 1 & 2 Tests | Implement Feature Coverage & Boundary/Corner cases (50 tests) | M1 | PLANNED |
| 3 | Tier 3 & 4 Tests | Implement Cross-Feature & Real-World Application scenarios (15+ tests) and runner | M2 | PLANNED |
| 4 | Verification & Handoff | Verify execution against codebase and publish TEST_READY.md | M3 | PLANNED |

## Interface Contracts
- Tests reside in `tests/e2e/` or equivalent files under `tests/` and are run via `pytest`.
- Mocks simulate:
  - Gemini Live session events & reconnects (via client.aio.live.connect mock or mock WS).
  - LLM timeouts and fallback provider responses (via httpx client transport / respx mocks).
  - Windows UI automation and OCR (via monkeypatched windll, pyautogui, and uiautomation).
