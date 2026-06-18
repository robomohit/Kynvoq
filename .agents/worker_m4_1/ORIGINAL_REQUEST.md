## 2026-06-17T18:48:19-07:00
You are a teamwork_preview_worker agent.
Your working directory is: c:\Users\ACER\Desktop\Ai_computer\Orynn\.agents\worker_m4_1
Your identity is: teamwork_preview_worker
Your mission is to implement unified LLM API timeout & retry resilience (R4 specifications) in app/providers.py.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & Goals:
1. Target file: `app/providers.py`.
2. Standardize retry behavior across all unary provider calls (`_chat_anthropic`, `_chat_openai`, `_chat_openrouter`, `_chat_google`, `_chat_groq`, `_chat_ollama`):
   - Max attempts: 3.
   - Delay: Exponential backoff delay of `2 ** attempt` seconds (except OpenRouter which uses `2 ** (attempt + 1)` for its final fallback model).
   - Retry conditions: Catch and retry for HTTP status codes `402`, `408`, `429`, and `5xx` (500 <= status_code < 600), plus connection/transport errors (`httpx.TransportError`).
   - Log warnings: Log warning messages to client logs (using `_log.warning(...)`) detailing the provider name, status/error, delay, and attempt number when a retry occurs.
   - Ollama: Wrap Ollama unary calls in the standard retry block (it previously lacked retries completely).
   - OpenRouter: Preserve OpenRouter's soft error checking and fallback chain model logic, but ensure it retries on status code `408` and connection errors, and logs warnings for soft errors, HTTP status errors, and connection errors.
3. Align streaming provider calls (`stream_chat` and `_stream_chat_with_tools_single`) to follow the same retry rules:
   - When retrying the same model, catch status codes `402`, `408`, `429`, `5xx`, and connection/timeout errors (`httpx.TransportError`).
   - Log warning messages via `_log.warning` when a streaming attempt fails and is retried.
4. Run verification tests to ensure the changes are correct and do not break existing code:
   `pytest tests/test_providers.py tests/test_provider_hardening.py`
5. Propose your changes in your handoff report and write your `progress.md` and `handoff.md`.
