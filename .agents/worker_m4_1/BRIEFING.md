# BRIEFING — 2026-06-17T18:48:19-07:00

## Mission
Implement unified LLM API timeout & retry resilience (R4 specifications) in app/providers.py.

## 🔒 My Identity
- Archetype: teamwork_preview_worker
- Roles: implementer, qa, specialist
- Working directory: c:\Users\ACER\Desktop\Ai_computer\Orynn\.agents\worker_m4_1
- Original parent: 9f87b0d2-a91a-4422-9c23-727f736fabb4
- Milestone: LLM Resilience (R4)

## 🔒 Key Constraints
- Target file: `app/providers.py`
- Max attempts: 3
- Delay: Exponential backoff delay of `2 ** attempt` seconds (except OpenRouter fallback model: `2 ** (attempt + 1)`)
- Retry conditions: HTTP status codes `402`, `408`, `429`, and `5xx`, plus connection/transport errors (`httpx.TransportError`)
- Log warnings: `_log.warning(...)` detailing the provider name, status/error, delay, and attempt number when a retry occurs
- Ollama: Wrap unary calls in the standard retry block
- OpenRouter: Preserve soft error checking and fallback chain model logic, but ensure it retries on status code `408` and connection errors, and logs warnings for soft errors, HTTP status errors, and connection errors
- Stream chat: Align streaming provider calls (`stream_chat` and `_stream_chat_with_tools_single`) to follow the same retry rules
- Running tests: `pytest tests/test_providers.py tests/test_provider_hardening.py`

## Current Parent
- Conversation ID: 9f87b0d2-a91a-4422-9c23-727f736fabb4
- Updated: not yet

## Task Summary
- **What to build**: Unified retry and timeout error handling logic for unary and streaming LLM APIs in Orynn.
- **Success criteria**: All tests pass, retry rules are followed exactly as requested, client logging handles all error warnings.
- **Interface contracts**: Unchanged provider signatures but hardened implementations.
- **Code layout**: `app/providers.py`

## Key Decisions Made
- [TBD]

## Change Tracker
- **Files modified**: None
- **Build status**: [TBD]
- **Pending issues**: None

## Quality Status
- **Build/test result**: [TBD]
- **Lint status**: [TBD]
- **Tests added/modified**: None

## Loaded Skills
- None

## Artifact Index
- None
