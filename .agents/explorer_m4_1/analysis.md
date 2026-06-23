# Milestone 4 - Unified LLM API Timeout & Retry Resilience Analysis

## Executive Summary
This report analyzes `app/providers.py` to identify vulnerabilities and gaps in current provider call retries, and recommends a unified strategy to standardize retry behavior and error handling. We have successfully implemented a code diff in `providers.patch` and verified it through a custom test suite (`test_proposed_providers.py`).

---

## 1. Direct Observations of Current Implementation
Our read-only analysis of `app/providers.py` reveals the following findings:
- **Lack of Logging**: None of the direct provider functions (`_chat_anthropic`, `_chat_openai`, `_chat_google`, `_chat_groq`, `_chat_openrouter`) log warnings to client logs when rate limits/timeouts occur. They silently perform retry sleeps or log using `print()`.
- **Incomplete Retry Conditions**: The standard retry conditions inside the 3-attempt loop of direct providers look like:
  ```python
  if e.response.status_code in (402, 429) or e.response.status_code >= 500:
  ```
  This is missing a check for **`408` (Request Timeout)**, which is in the `4xx` range and should be retried.
- **Ollama Provider Lacks Retry Handling**: The `_chat_ollama` provider has no retry loop or exception handling whatsoever. If local Ollama is briefly offline, slow, or restarting, the task fails immediately.
- **Inconsistent Backoff Multiplier**: `_chat_openrouter` uses a backoff of `2 ** (attempt + 1)` (i.e., 2s, 4s, 8s) whereas `_chat_openai`, `_chat_anthropic`, `_chat_google`, and `_chat_groq` use `2 ** attempt` (i.e., 1s, 2s, 4s).

---

## 2. Recommended Strategy
To resolve these issues, we recommend standardizing the retry and warning logic using the following architecture:
1. **Standardize Retry Status Codes**: All direct provider calls must retry on `httpx.HTTPStatusError` if the status code is `402`, `408`, `429`, or falls within the server error range `500 <= status_code < 600`.
2. **Log Warnings to Client Logs**: Integrate `_log.warning(...)` calls whenever an HTTP status error or a `httpx.TransportError` occurs, describing the failure, the current attempt, and the duration of the backoff delay.
3. **Bring Ollama into Compliance**: Add the standard 3-attempt retry loop to `_chat_ollama`.
4. **Preserve OpenRouter Custom Logic**: Keep OpenRouter's slightly larger backoff of `2 ** (attempt + 1)` and its multi-model fallback chain structure, but align its retry status checks and add warning logging for both HTTP status errors, connection errors, and OpenRouter soft errors.

---

## 3. Recommended Code Changes (Unified Patch)
We generated a unified patch file, `providers.patch` in our agent directory, which implements these changes precisely.

### Key Snippets from the Proposed Implementation:
- **Ollama Retry Wrapper:**
  ```python
  last_err = None
  for attempt in range(3):
      try:
          resp = self._http_client.post(f"{self._ollama_base_url}/api/chat", json=payload)
          resp.raise_for_status()
          ...
      except httpx.HTTPStatusError as e:
          last_err = e
          status_code = e.response.status_code
          if status_code in (402, 408, 429) or (500 <= status_code < 600):
              delay = 2 ** attempt
              _log.warning("Ollama API HTTP error %d: %s. Retrying in %ds... (Attempt %d/3)", status_code, e, delay, attempt + 1)
              time.sleep(delay)
              continue
          raise
      except httpx.TransportError as e:
          last_err = e
          delay = 2 ** attempt
          _log.warning("Ollama API connection/timeout error: %s. Retrying in %ds... (Attempt %d/3)", e, delay, attempt + 1)
          time.sleep(delay)
          continue
  ```

- **Groq/OpenAI/Anthropic/Google Retry Warning Update:**
  ```python
  except httpx.HTTPStatusError as e:
      last_err = e
      status_code = e.response.status_code
      if status_code in (402, 408, 429) or (500 <= status_code < 600):
          delay = 2 ** attempt
          _log.warning("Groq API HTTP error %d: %s. Retrying in %ds... (Attempt %d/3)", status_code, e, delay, attempt + 1)
          time.sleep(delay)
          continue
      raise
  ```

---

## 4. Verification and Testing
To guarantee correctness without modifying the repository's source code files, we:
1. Created `test_proposed_providers.py` in our agent folder which loads the patched `proposed_providers.py` under the `app.providers` package path.
2. Verified that all 5 tests passed successfully, confirming:
   - `408 Request Timeout` is correctly caught, retried with exponential backoff, and logged to `caplog` as a warning.
   - `503 Service Unavailable` is correctly caught, retried, and logged as a warning.
   - `httpx.ConnectError` (TransportError) is correctly caught, retried, and logged as a warning.
   - Non-retryable status codes (like `400 Bad Request`) fail immediately without retrying.
   - `_chat_ollama` successfully retries on retryable errors.
