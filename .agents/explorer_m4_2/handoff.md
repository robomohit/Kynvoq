# Handoff Report: Milestone 4 - Unified LLM API Timeout & Retry Resilience

## 1. Observation
- Duplicated retry loops in synchronous chat methods `_chat_anthropic`, `_chat_openai`, `_chat_google`, and `_chat_groq` in `app/providers.py` (lines 1277–1637) catch `httpx.HTTPStatusError` and `httpx.TransportError` but only retry for `(402, 429) or e.response.status_code >= 500`. They do not catch/retry `408`, nor do they log warnings to client logs. For example, `_chat_google` line 1581:
  ```python
  except httpx.HTTPStatusError as e:
      last_err = e
      if e.response.status_code in (402, 429) or e.response.status_code >= 500:
          time.sleep(2 ** attempt)
          continue
      raise
  ```
- `_chat_openrouter` on lines 1372–1462 handles error logs with print statements (e.g. line 1417: `print(f"OPENROUTER SOFT ERROR ({current_model}): {err_msg}")`) and ignores status code `408`.
- Streaming endpoints `stream_chat` (lines 1698–1849) and `_stream_chat_with_tools_single` (lines 1921–2146) only retry on `(402, 429)` and completely fail to retry connection errors (`httpx.TransportError`) or `5xx`/`408` status codes. Line 1812:
  ```python
  if resp.status_code in (402, 429) and _attempt < len(_retry_delays):
      continue  # retry same model
  ```
  And line 1839:
  ```python
  except httpx.HTTPStatusError as e:
      last_err = e
      if e.response.status_code in (402, 429) and _attempt < len(_retry_delays):
          continue
      if e.response.status_code in (402, 429):
          break  # move to next model fallback
      raise
  ```
- Running the existing test suite:
  `pytest tests/test_providers.py tests/test_provider_hardening.py`
  Result: `26 passed in 7.99s`.

---

## 2. Logic Chain
1. Standardizing retry behavior across all provider calls requires unified status code filtering and exponential backoff.
2. Status code `408` (Request Timeout) must be added alongside `429`, `5xx`, and connection errors (`httpx.TransportError`).
3. Introducing a centralized helper `_is_retryable_error` ensures checking logic is 100% consistent.
4. Implementing a synchronous retry helper `_execute_with_retry` simplifies code maintenance and ensures warnings are logged to `_log` (client logs) consistently.
5. In async streaming methods, refactoring the `_attempt` loops to check `_is_retryable_error` and call `_log.warning` prevents unexpected streaming crashes due to transient server/network failures.

---

## 3. Caveats
- Direct streaming errors occurring *during* token chunk output (after initial headers are received) are much more complex to retry as partial output has already been sent to downstream consumers. The proposed strategy retries connection/timeout/rate errors occurring at the request/initiation phase of the stream, which matches the current implementation structure.

---

## 4. Conclusion
We recommend introducing a unified `_is_retryable_error` helper and `_execute_with_retry` wrapper in `PlannerProvider` to standardize retry behavior, backoffs, status codes (`429`, `408`, `5xx`), and connection errors with warnings logged via `_log.warning`.

---

## 5. Verification Method
- **Verification Commands**: Run `pytest tests/test_providers.py tests/test_provider_hardening.py` to verify no regressions in current functionality.
- **Verification of hardener**: After implementing the proposed changes, run the new unit tests mocking 408/500/TransportErrors.
