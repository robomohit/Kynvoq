# Handoff Report

## 1. Observation

- **Target File**: `app/providers.py`
- **Current Retry Patterns**:
  - `_chat_anthropic` (lines 1315-1327):
    ```python
                except httpx.HTTPStatusError as e:
                    last_err = e
                    if e.response.status_code in (402, 429) or e.response.status_code >= 500:
                        time.sleep(2 ** attempt)
                        continue
                    raise
                except httpx.TransportError as e:
                    last_err = e
                    time.sleep(2 ** attempt)
                    continue
    ```
  - Similar loops are duplicated in `_chat_openai` (lines 1358-1370), `_chat_google` (lines 1581-1593), and `_chat_groq` (lines 1624-1636).
  - `_chat_openrouter` (lines 1428-1447) uses a different backoff formula: `time.sleep(2 ** (attempt + 1))`.
  - `_chat_ollama` (lines 1261-1276) completely lacks any retry block.
  - Streaming methods `stream_chat` (lines 1805-1845) and `_stream_chat_with_tools_single` (lines 2024-2132) check only `resp.status_code in (402, 429)`. They do not retry on connection errors or other status codes such as `408` or `5xx`.
  - None of the methods log warnings to module-level logger `_log` (defined at line 17: `_log = logging.getLogger(__name__)`).
- **Tests Execution**: Running `pytest tests/test_providers.py tests/test_provider_hardening.py` succeeded with 26 passed tests:
  ```
  ============================= 26 passed in 7.02s ==============================
  ```

---

## 2. Logic Chain

1. **Observation of Code Duplication**: Duplication of retry loops across unary calls makes it prone to divergent behavior (e.g. `_chat_openrouter` using `2 ** (attempt + 1)` and others using `2 ** attempt`, and `_chat_ollama` having no retries). Consolidation into a single helper method will ensure consistency.
2. **Missing Status Codes and Connection Errors**: Status code `408` is not caught in unary calls, and `408`, `5xx`, and connection errors are not retried in streaming calls. Updating the triggers to include `408`, `429`, `5xx`, and connection errors is necessary to satisfy the resilience requirements.
3. **Lack of Client Logging**: None of the current retry blocks call `_log.warning`. Introducing logging of warnings with backoff duration, retry attempt, and status/error details inside the centralized helper will provide visibility into transient failures.
4. **Conclusion Support**: Standardizing retry behavior via a new helper method `_execute_with_retry` and refactoring unary calls to delegate to it, while aligning streaming calls to catch the same conditions, provides a complete, robust, and clean solution.

---

## 3. Caveats

- **Ollama Local Behavior**: Ollama is local, so rate limiting (429/408) is rare, but connection errors (e.g., if the service is not started) are caught and retried by the proposed helper.
- **OpenRouter Fallback Chain**: Refactoring OpenRouter requires special care to preserve its fallback chain behavior (e.g. failing fast on non-final models but retrying on the final model) and handling of soft errors in the response JSON. The proposed implementation strategy details how to address this.

---

## 4. Conclusion

The recommended fix strategy is to:
1. Implement a unified synchronous helper method `_execute_with_retry` on `PlannerProvider` that implements exponential backoff (`2 ** attempt`), catches status codes `408`, `429`, `5xx` (and `402`), catches connection/transport errors, and logs warnings via `_log.warning`.
2. Refactor `_chat_anthropic`, `_chat_openai`, `_chat_google`, `_chat_groq`, `_chat_ollama`, and the final model in `_chat_openrouter` to use the helper.
3. Update streaming calls (`stream_chat` and `_stream_chat_with_tools_single`) to catch the same retryable conditions (`408`, `429`, `5xx`, connection errors), log warning logs, and use backoff delays.

---

## 5. Verification Method

- **Tests to Execute**: Run `pytest tests/test_providers.py tests/test_provider_hardening.py` to confirm no regressions to existing provider features.
- **New Tests**: Create tests inside `tests/test_provider_hardening.py` that:
  - Inject HTTP responses with status codes `408`, `429`, and `503`, and raise `httpx.ConnectError` to verify retry attempts, exponential backoff timing, and warning log messages in client logs.
