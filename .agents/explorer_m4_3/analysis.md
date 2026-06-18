# Analysis: Milestone 4 - Unified LLM API Timeout & Retry Resilience

## 1. Summary of Findings

We analyzed `app/providers.py` to evaluate the current retry and timeout mechanisms across all LLM providers. Here is a summary of our findings:

### Current Implementation Gaps & Inconsistencies

1. **Lack of Standardized Retry Logic**:
   - Most unary chat methods (`_chat_anthropic`, `_chat_openai`, `_chat_google`, and `_chat_groq`) have duplicated retry loops with inline exception handling blocks.
   - `_chat_ollama` has no retry or error-handling logic at all. If the local Ollama service is temporarily unavailable or overloaded, it raises an uncaught exception.
   - `_chat_openrouter` has a customized fallback chain loop that handles model switching, but its retry logic on the final model uses a different sleep calculation (`2 ** (attempt + 1)`) compared to the others (`2 ** attempt`).

2. **Inconsistent Retry Triggers**:
   - The unary calls currently retry on status codes `402`, `429`, and `5xx`, plus `httpx.TransportError` (connection errors/timeouts).
   - The status code **`408` (Request Timeout)** is **not** handled in the unary calls, despite being a common transient network failure.
   - The streaming calls (`stream_chat` and `_stream_chat_with_tools_single`) only retry on `402` and `429`. They completely fail to retry on `5xx`, `408`, or connection/timeout errors (`httpx.TransportError`).

3. **No Warning Logging to Client Logs**:
   - Failed attempts in unary and streaming methods are silently retried (using `time.sleep`) without logging warnings to the client logs. While some methods print logs (`print`), standard logging using `_log.warning` is absent during retries.

---

## 2. Recommended Refactoring Strategy

We recommend refactoring `app/providers.py` to centralize and standardize the retry behavior using a helper method `_execute_with_retry` for all unary calls, and aligning the asynchronous streaming methods to follow the same rules.

### A. Centralized Retry Helper (`_execute_with_retry`)

Add the following helper method to `PlannerProvider` to handle retry logic, exponential backoff, and logging warnings:

```python
    def _execute_with_retry(
        self,
        provider_name: str,
        request_fn: Callable[[], httpx.Response],
        max_attempts: int = 3,
        check_response_fn: Optional[Callable[[httpx.Response], None]] = None
    ) -> httpx.Response:
        """Execute request_fn with standardized exponential backoff retries.
        
        Retries on:
          - HTTP status codes: 408, 429, 5xx (and 402 for compatibility)
          - Connection/transport errors (httpx.TransportError)
          - Soft errors (via check_response_fn raising RuntimeError)
        Logs warnings to client logs on retryable failures.
        """
        last_err = None
        for attempt in range(max_attempts):
            try:
                resp = request_fn()
                resp.raise_for_status()
                if check_response_fn:
                    check_response_fn(resp)
                return resp
            except httpx.HTTPStatusError as e:
                last_err = e
                status_code = e.response.status_code
                if status_code in (402, 408, 429) or status_code >= 500:
                    delay = 2 ** attempt
                    _log.warning(
                        "Provider call to %s failed with status %d (attempt %d/%d). Retrying in %ds...",
                        provider_name, status_code, attempt + 1, max_attempts, delay
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.TransportError as e:
                last_err = e
                delay = 2 ** attempt
                _log.warning(
                    "Provider call to %s failed with connection error: %s (attempt %d/%d). Retrying in %ds...",
                    provider_name, str(e), attempt + 1, max_attempts, delay
                )
                time.sleep(delay)
                continue
            except RuntimeError as e:
                last_err = e
                # Check if this RuntimeError from check_response_fn is retryable
                if "rate" in str(e).lower() or "busy" in str(e).lower() or "429" in str(e) or "408" in str(e):
                    delay = 2 ** attempt
                    _log.warning(
                        "Provider call to %s failed with retryable soft error: %s (attempt %d/%d). Retrying in %ds...",
                        provider_name, str(e), attempt + 1, max_attempts, delay
                    )
                    time.sleep(delay)
                    continue
                raise
        raise last_err or RuntimeError(f"All retries for {provider_name} exhausted")
```

### B. Refactoring Unary Methods

Refactor all unary chat methods to delegate their network calls to the helper:

#### 1. Anthropic (`_chat_anthropic`)
```python
        def make_call():
            return self._http_client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "interleaved-thinking-2025-05-14"
                },
                json=payload,
            )

        resp = self._execute_with_retry("Anthropic", make_call)
```

#### 2. OpenAI (`_chat_openai`)
```python
        def make_call():
            return self._http_client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._openai_key}"},
                json=payload,
            )

        resp = self._execute_with_retry("OpenAI", make_call)
```

#### 3. Google (`_chat_google`)
```python
        def make_call():
            return self._http_client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self._google_key}",
                json=payload,
            )

        resp = self._execute_with_retry("Google", make_call)
```

#### 4. Groq (`_chat_groq`)
```python
        def make_call():
            return self._http_client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._groq_key}"},
                json=payload,
            )

        resp = self._execute_with_retry("Groq", make_call)
```

#### 5. Ollama (`_chat_ollama`)
```python
        def make_call():
            return self._http_client.post(f"{self._ollama_base_url}/api/chat", json=payload)
        
        resp = self._execute_with_retry("Ollama", make_call)
```

#### 6. OpenRouter (`_chat_openrouter`)
Integrate OpenRouter's soft error checking and fallback chain with `_execute_with_retry` as follows:
```python
                is_last_model = (current_model == models_to_try[-1])
                max_attempts = 3 if is_last_model else 1

                def make_call():
                    return self._http_client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self._openrouter_key}"},
                        json=payload,
                    )

                def check_openrouter_resp(resp: httpx.Response):
                    resp_json = resp.json()
                    if "error" in resp_json:
                        err_msg = resp_json["error"].get("message", str(resp_json["error"]))
                        print(f"OPENROUTER SOFT ERROR ({current_model}): {err_msg}")
                        raise RuntimeError(f"OpenRouter error: {err_msg}")
                    if "choices" not in resp_json:
                        raise RuntimeError(f"Unexpected OpenRouter response: choices missing")

                try:
                    resp = self._execute_with_retry(
                        f"OpenRouter ({current_model})",
                        make_call,
                        max_attempts=max_attempts,
                        check_response_fn=check_openrouter_resp
                    )
                    return _extract_chat_message_text(resp.json())
                except (httpx.HTTPStatusError, httpx.TransportError, RuntimeError) as e:
                    last_err = e
                    if not is_last_model:
                        break  # fail fast to next model
                    break  # last model failed all retries
```

---

## 3. Streaming Calls Recommendation

To align streaming calls (`stream_chat` and `_stream_chat_with_tools_single`) with the standardized retry behavior:
1. Standardize retry delays to exponential backoff `[2, 4, 8]` seconds when `len(models_to_try) == 1`.
2. Catch status codes `(402, 408, 429)` and `>= 500` as retryable.
3. Catch connection errors (`httpx.TransportError`) and retry.
4. Log warning messages to client logs via `_log.warning` when a streaming attempt fails and is retried.

---

## 4. Verification Plan

New unit tests should be added to `tests/test_provider_hardening.py` to verify:
1. **Retry triggers**: Mock responses with status codes `408`, `429`, and `503` (representing `5xx`), and connection errors to verify they trigger retries.
2. **Exponential backoff**: Verify that sleep time doubles on subsequent retries (e.g. 1s then 2s).
3. **Warning Logging**: Use standard `unittest.mock.patch` or pytest `caplog` fixture to assert `_log.warning` is called with appropriate message details during retries.
