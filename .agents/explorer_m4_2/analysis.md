# Analysis: Milestone 4 - Unified LLM API Timeout & Retry Resilience

## Executive Summary
This report analyzes the existing LLM provider call architecture in `app/providers.py` and proposes a standardized, resilient retry mechanism with exponential backoff for status codes `429`, `408`, `5xx`, and connection/timeout errors.

---

## 1. Current State Assessment
We inspected the provider implementations in `app/providers.py` and identified the following gaps/inconsistencies:

### A. Non-Streaming HTTP Requests
The synchronous LLM chat functions (`_chat_anthropic`, `_chat_openai`, `_chat_google`, and `_chat_groq`) use a duplicated, hardcoded 3-attempt retry loop:
- **Retryable HTTP Status Codes**: Currently hardcoded to check for `(402, 429) or e.response.status_code >= 500`.
- **Missing Status Codes**: `408` (Request Timeout) is NOT checked/handled.
- **Logging**: Failed attempts do not log warning messages to client logs (they fail silently during intermediate retries, only raising on the final attempt).
- **Duplication**: The entire `try-except` block structure is repeated across all four functions.

### B. OpenRouter Chat (`_chat_openrouter`)
OpenRouter implements a custom model fallback chain and attempts retries (up to 3 times on the last model, 1 time on earlier models).
- **Soft Errors**: Handles OpenRouter-specific `"error"` keys in the JSON response, but prints them to stdout using `print()` instead of logging them properly via `_log.warning()`.
- **Missing Status Codes**: `408` is not explicitly checked as a retryable status code.
- **Inconsistent Backoff**: Uses `2 ** (attempt + 1)` instead of a standardized backoff formula.

### C. Async Streaming calls (`stream_chat` and `_stream_chat_with_tools_single`)
The streaming calls have their own nested connection and retry loops:
- **HTTP status codes**: Only retry on `(402, 429)`. They completely ignore `5xx`, `408`, and connection errors (`httpx.TransportError`).
- **Connection Failure**: A connection/read-timeout error bubbles up immediately and crashes the stream, bypassing model fallbacks.
- **Inconsistent delays**: Delays are hardcoded as `[5, 15, 30]` rather than using a standard exponential formula.

---

## 2. Proposed Architecture & Standardized Retry Strategy
We recommend introducing a unified helper function `_is_retryable_error()` and wrapping HTTP calls in a standardized retry loop using `_execute_with_retry()`.

### A. Identifying Retryable Errors
```python
def _is_retryable_error(self, exc: Exception) -> tuple[bool, str]:
    """Check if the given exception or status code should trigger a retry."""
    import httpx
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (402, 408, 429) or (500 <= status < 600):
            return True, f"HTTP status {status}"
    elif isinstance(exc, httpx.TransportError):
        return True, "connection error"
    elif isinstance(exc, RuntimeError):
        err_str = str(exc).lower()
        if any(k in err_str for k in ("rate", "429", "402", "quota", "limit", "busy", "timeout", "408")):
            return True, "provider runtime error"
    return False, ""
```

### B. Standardized Synchronous Retry Helper
```python
def _execute_with_retry(
    self,
    func: Callable[[], Any],
    max_attempts: int = 3,
    model_name: Optional[str] = None
) -> Any:
    """Execute a provider call with exponential backoff retries and logging."""
    import time
    last_err = None
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            last_err = e
            is_retryable, err_type = self._is_retryable_error(e)
            if is_retryable and attempt < max_attempts - 1:
                backoff = 2 ** attempt
                _log.warning(
                    "Provider call%s failed due to %s. Retrying in %ds (attempt %d/%d)... Error: %s",
                    f" for {model_name}" if model_name else "",
                    err_type,
                    backoff,
                    attempt + 1,
                    max_attempts,
                    str(e)
                )
                time.sleep(backoff)
                continue
            raise
    raise last_err or RuntimeError("All API retries exhausted")
```

---

## 3. Integration Plan & Code Diffs

### A. Non-Streaming Providers
Replace the duplicate retry loops in `_chat_anthropic`, `_chat_openai`, `_chat_google`, and `_chat_groq` with `_execute_with_retry`.
Example for `_chat_groq`:
```python
# Before
        last_err = None
        for attempt in range(3):
            try:
                with _build_llm_http_client() as client:
                    resp = client.post(...)
                    resp.raise_for_status()
                    return _extract_chat_message_text(resp.json())
            except httpx.HTTPStatusError as e: ...
            except httpx.TransportError as e: ...

# After
        def _call():
            with _build_llm_http_client() as client:
                resp = client.post(...)
                resp.raise_for_status()
                return _extract_chat_message_text(resp.json())

        return self._execute_with_retry(_call, max_attempts=3, model_name=self.model)
```

### B. OpenRouter Fallback Logic
Update the inner attempt loop in `_chat_openrouter` to use `_execute_with_retry` inside the outer `models_to_try` fallback loop:
```python
            for current_model in models_to_try:
                # ... setup payload ...
                is_last_model = (current_model == models_to_try[-1])
                max_attempts = 3 if is_last_model else 1
                
                def _call():
                    resp = self._http_client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self._openrouter_key}"},
                        json=payload,
                    )
                    if resp.status_code != 200:
                        _log.warning("OPENROUTER ERROR (%s): %s", current_model, resp.text)
                    resp.raise_for_status()
                    resp_json = resp.json()
                    if "error" in resp_json:
                        err_msg = resp_json["error"].get("message", str(resp_json["error"]))
                        _log.warning("OPENROUTER SOFT ERROR (%s): %s", current_model, err_msg)
                        raise RuntimeError(f"OpenRouter error: {err_msg}")
                    if "choices" not in resp_json:
                        raise RuntimeError(f"Unexpected OpenRouter response: {str(resp_json)[:200]}")
                    return _extract_chat_message_text(resp_json)

                try:
                    return self._execute_with_retry(_call, max_attempts=max_attempts, model_name=current_model)
                except Exception as e:
                    last_err = e
                    # Continue to next model fallback if not last
                    continue
```

### C. Async Streaming
Refactor the retry logic in `stream_chat` and `_stream_chat_with_tools_single` to check `_is_retryable_error()` and log warning messages when an attempt fails.

---

## 4. Verification & Testing Strategy
1. **Mocking**: Write a new test module or extend `tests/test_provider_hardening.py` to:
   - Verify `_chat_groq`, `_chat_openrouter`, and others retry on `408`, `429`, `503`, and `httpx.ConnectTimeout`.
   - Verify warnings are printed to loggers during backoffs.
2. **Execution**: Run `pytest tests/test_providers.py tests/test_provider_hardening.py` to confirm all existing tests pass and no regression occurs.
