# Scope: Milestone 4 - Unified LLM API Timeout & Retry Resilience (R4)

## Architecture
- Target: `app/providers.py`
- Problem: API calls to Groq/OpenRouter lack resilient retry handlers (only Google chat has it).
- Solution: Standardize retry behavior across all provider calls (`_chat_groq`, `_chat_openrouter`, etc.) with exponential backoff retries for status codes `429`, `408`, `5xx`, and connection errors. Log warning messages to client logs.

## Verification
- Unit/integration tests mocking provider client responses to trigger retry logic.
