import os
import difflib

# Read original
orig_path = r"c:\Users\ACER\Desktop\Ai_computer\Orynn\app\providers.py"
with open(orig_path, "r", encoding="utf-8") as f:
    content = f.read()

# Block 1: _chat_ollama
ollama_orig = """    def _chat_ollama(self, system: str, prompt: str, screenshot_b64: Optional[str] = None) -> str:
        if screenshot_b64:
            prompt = f"{prompt}\\n\\n[Note: local Ollama text mode cannot inspect screenshots in this build.]"
        payload = {
            "model": _ollama_name(self.model),
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        resp = self._http_client.post(f"{self._ollama_base_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return str((data.get("message") or {}).get("content") or data.get("response") or "")"""

ollama_repl = """    def _chat_ollama(self, system: str, prompt: str, screenshot_b64: Optional[str] = None) -> str:
        if screenshot_b64:
            prompt = f"{prompt}\\n\\n[Note: local Ollama text mode cannot inspect screenshots in this build.]"
        payload = {
            "model": _ollama_name(self.model),
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        last_err = None
        for attempt in range(3):
            try:
                resp = self._http_client.post(f"{self._ollama_base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return str((data.get("message") or {}).get("content") or data.get("response") or "")
            except httpx.HTTPStatusError as e:
                last_err = e
                status_code = e.response.status_code
                if status_code in (402, 408, 429) or (500 <= status_code < 600):
                    delay = 2 ** attempt
                    _log.warning(
                        "Ollama API HTTP error %d: %s. Retrying in %ds... (Attempt %d/3)",
                        status_code, e, delay, attempt + 1
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.TransportError as e:
                last_err = e
                delay = 2 ** attempt
                _log.warning(
                    "Ollama API connection/timeout error: %s. Retrying in %ds... (Attempt %d/3)",
                    e, delay, attempt + 1
                )
                time.sleep(delay)
                continue
        raise last_err or RuntimeError("All API retries exhausted")"""

# Block 2: _chat_anthropic
anthropic_orig = """            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code in (402, 429) or e.response.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except httpx.TransportError as e:
                # Connection/read-timeout error (e.g. a dead pooled connection or a
                # slow free model). Retry rather than let it hang or crash the task.
                last_err = e
                time.sleep(2 ** attempt)
                continue"""

anthropic_repl = """            except httpx.HTTPStatusError as e:
                last_err = e
                status_code = e.response.status_code
                if status_code in (402, 408, 429) or (500 <= status_code < 600):
                    delay = 2 ** attempt
                    _log.warning(
                        "Anthropic API HTTP error %d: %s. Retrying in %ds... (Attempt %d/3)",
                        status_code, e, delay, attempt + 1
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.TransportError as e:
                # Connection/read-timeout error (e.g. a dead pooled connection or a
                # slow free model). Retry rather than let it hang or crash the task.
                last_err = e
                delay = 2 ** attempt
                _log.warning(
                    "Anthropic API connection/timeout error: %s. Retrying in %ds... (Attempt %d/3)",
                    e, delay, attempt + 1
                )
                time.sleep(delay)
                continue"""

# Block 3: _chat_openai
openai_orig = anthropic_orig # Same as anthropic
openai_repl = """            except httpx.HTTPStatusError as e:
                last_err = e
                status_code = e.response.status_code
                if status_code in (402, 408, 429) or (500 <= status_code < 600):
                    delay = 2 ** attempt
                    _log.warning(
                        "OpenAI API HTTP error %d: %s. Retrying in %ds... (Attempt %d/3)",
                        status_code, e, delay, attempt + 1
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.TransportError as e:
                # Connection/read-timeout error (e.g. a dead pooled connection or a
                # slow free model). Retry rather than let it hang or crash the task.
                last_err = e
                delay = 2 ** attempt
                _log.warning(
                    "OpenAI API connection/timeout error: %s. Retrying in %ds... (Attempt %d/3)",
                    e, delay, attempt + 1
                )
                time.sleep(delay)
                continue"""

# Block 4: _chat_openrouter
openrouter_orig = """                            if attempt < 2:
                                time.sleep(2 ** (attempt + 1))
                                continue
                            raise RuntimeError(f"OpenRouter error: {err_msg}")
                        if "choices" not in resp_json:
                            raise RuntimeError(f"Unexpected OpenRouter response: {str(resp_json)[:200]}")
                        return _extract_chat_message_text(resp_json)
                    except httpx.HTTPStatusError as e:
                        last_err = e
                        if e.response.status_code in (402, 429) or e.response.status_code >= 500:
                            if not is_last_model:
                                break  # fail fast to next model
                            time.sleep(2 ** (attempt + 1))
                            continue
                        break
                    except httpx.TransportError as e:
                        # Connection/timeout error (dead pooled connection, slow free
                        # model, network blip). Fail over to the next model, or back
                        # off and retry on the last — never bubble up as a 5-min hang.
                        last_err = e
                        if not is_last_model:
                            break
                        if attempt < 2:
                            time.sleep(2 ** (attempt + 1))
                            continue
                        break"""

openrouter_repl = """                            if attempt < 2:
                                delay = 2 ** (attempt + 1)
                                _log.warning(
                                    "OpenRouter soft error (%s): %s. Retrying in %ds... (Attempt %d/3)",
                                    current_model, err_msg, delay, attempt + 1
                                )
                                time.sleep(delay)
                                continue
                            raise RuntimeError(f"OpenRouter error: {err_msg}")
                        if "choices" not in resp_json:
                            raise RuntimeError(f"Unexpected OpenRouter response: {str(resp_json)[:200]}")
                        return _extract_chat_message_text(resp_json)
                    except httpx.HTTPStatusError as e:
                        last_err = e
                        status_code = e.response.status_code
                        if status_code in (402, 408, 429) or (500 <= status_code < 600):
                            if not is_last_model:
                                break  # fail fast to next model
                            delay = 2 ** (attempt + 1)
                            _log.warning(
                                "OpenRouter API HTTP error %d (%s): %s. Retrying in %ds... (Attempt %d/3)",
                                status_code, current_model, e, delay, attempt + 1
                            )
                            time.sleep(delay)
                            continue
                        break
                    except httpx.TransportError as e:
                        # Connection/timeout error (dead pooled connection, slow free
                        # model, network blip). Fail over to the next model, or back
                        # off and retry on the last — never bubble up as a 5-min hang.
                        last_err = e
                        if not is_last_model:
                            break
                        if attempt < 2:
                            delay = 2 ** (attempt + 1)
                            _log.warning(
                                "OpenRouter API connection/timeout error (%s): %s. Retrying in %ds... (Attempt %d/3)",
                                current_model, e, delay, attempt + 1
                            )
                            time.sleep(delay)
                            continue
                        break"""

# Block 5: _chat_google
google_orig = anthropic_orig
google_repl = """            except httpx.HTTPStatusError as e:
                last_err = e
                status_code = e.response.status_code
                if status_code in (402, 408, 429) or (500 <= status_code < 600):
                    delay = 2 ** attempt
                    _log.warning(
                        "Google API HTTP error %d: %s. Retrying in %ds... (Attempt %d/3)",
                        status_code, e, delay, attempt + 1
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.TransportError as e:
                # Connection/read-timeout error (e.g. a dead pooled connection or a
                # slow free model). Retry rather than let it hang or crash the task.
                last_err = e
                delay = 2 ** attempt
                _log.warning(
                    "Google API connection/timeout error: %s. Retrying in %ds... (Attempt %d/3)",
                    e, delay, attempt + 1
                )
                time.sleep(delay)
                continue"""

# Block 6: _chat_groq
groq_orig = anthropic_orig
groq_repl = """            except httpx.HTTPStatusError as e:
                last_err = e
                status_code = e.response.status_code
                if status_code in (402, 408, 429) or (500 <= status_code < 600):
                    delay = 2 ** attempt
                    _log.warning(
                        "Groq API HTTP error %d: %s. Retrying in %ds... (Attempt %d/3)",
                        status_code, e, delay, attempt + 1
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.TransportError as e:
                # Connection/read-timeout error (e.g. a dead pooled connection or a
                # slow free model). Retry rather than let it hang or crash the task.
                last_err = e
                delay = 2 ** attempt
                _log.warning(
                    "Groq API connection/timeout error: %s. Retrying in %ds... (Attempt %d/3)",
                    e, delay, attempt + 1
                )
                time.sleep(delay)
                continue"""

# Replace sequentially
new_content = content
assert ollama_orig in new_content, "Ollama block not found"
new_content = new_content.replace(ollama_orig, ollama_repl, 1)

assert anthropic_orig in new_content, "Anthropic/OpenAI/Google/Groq block not found"
# Anthropic is the first occurrence of anthropic_orig after _chat_anthropic
# Let's locate the index of _chat_anthropic
idx_anthropic = new_content.find("def _chat_anthropic")
idx_anth_err = new_content.find(anthropic_orig, idx_anthropic)
new_content = new_content[:idx_anth_err] + anthropic_repl + new_content[idx_anth_err + len(anthropic_orig):]

# OpenAI is the next occurrence after _chat_openai
idx_openai = new_content.find("def _chat_openai")
idx_openai_err = new_content.find(openai_orig, idx_openai)
new_content = new_content[:idx_openai_err] + openai_repl + new_content[idx_openai_err + len(openai_orig):]

# OpenRouter
assert openrouter_orig in new_content, "OpenRouter block not found"
new_content = new_content.replace(openrouter_orig, openrouter_repl, 1)

# Google is the next occurrence after _chat_google
idx_google = new_content.find("def _chat_google")
idx_google_err = new_content.find(google_orig, idx_google)
new_content = new_content[:idx_google_err] + google_repl + new_content[idx_google_err + len(google_orig):]

# Groq is the next occurrence after _chat_groq
idx_groq = new_content.find("def _chat_groq")
idx_groq_err = new_content.find(groq_orig, idx_groq)
new_content = new_content[:idx_groq_err] + groq_repl + new_content[idx_groq_err + len(groq_orig):]

# Write proposed
proposed_path = "proposed_providers.py"
with open(proposed_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("proposed_providers.py generated successfully.")

# Generate patch file
with open(orig_path, "r", encoding="utf-8") as f:
    orig_lines = f.readlines()
with open(proposed_path, "r", encoding="utf-8") as f:
    new_lines = f.readlines()

diff = difflib.unified_diff(
    orig_lines,
    new_lines,
    fromfile="app/providers.py",
    tofile="app/providers.py",
    lineterm=""
)

patch_path = "providers.patch"
with open(patch_path, "w", encoding="utf-8") as f:
    f.write("\n".join(diff) + "\n")

print("providers.patch generated successfully.")

