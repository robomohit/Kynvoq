# Explorer Synthesis - Milestone 1

## Consensus
All three Explorer subagents analyzed `app/widget/gemini_live.py` and reached full consensus on the auto-reconnect strategy:
1. **Indefinite Retries**: Remove the limit `max_retries = 5` and the `raise exc` block inside the main connection try-except block. The loop must retry indefinitely, terminating only when `self._stop.is_set()` evaluates to `True`.
2. **Capped Exponential Backoff**: Capping the backoff delay should be increased from 10.0s to 30.0s, using a constant like `GEMINI_LIVE_MAX_RETRY_DELAY = 30.0`.
3. **Queue Clearing**: Upon a successful connection/reconnection, both the input microphone queue (`audio_queue`) and the output speaker queue (`output_q`) must be cleared/flushed to prevent playing stale audio. Draining of `output_q` can be done via the existing static helper `self._flush_output(output_q)`.
4. **Responsive Sleep**: To ensure the thread shuts down immediately when the user stops Gemini Live, replace the atomic `await asyncio.sleep(retry_delay)` with a responsive sleep loop that checks `self._stop.is_set()` at short intervals (e.g., 0.1s or 0.2s).

## Resolved Conflicts
None. All analysis and recommended snippets align perfectly.

## Dissenting Views
None.

## Gaps
- Running the existing unit test suite shows a pre-existing failing test: `test_function_declarations_cover_desktop_tools` in `tests/test_gemini_live.py`. This is caused by an extra `'web_search'` in the function declarations that is not expected by the test. While not part of our milestone, the Worker should probably update this test to keep the test suite green, or we will have to ignore it if it's out of scope. But fixing it is trivial and improves overall test suite reliability.

## Proposed Code Layout Changes
```python
# At module level:
GEMINI_LIVE_MAX_RETRY_DELAY = 30.0

# In GeminiLiveCompanion._run() retry logic:
        retries = 0
        retry_delay = 1.0

        try:
            while not self._stop.is_set():
                if retries > 0:
                    self.callbacks.on_status(f"Live reconnecting (attempt {retries})...")
                config = self._live_config(types)
                try:
                    async with client.aio.live.connect(model=self.model, config=config) as session:
                        self._session = session
                        self._audio_fail_streak = 0
                        retries = 0
                        retry_delay = 1.0
                        self.callbacks.on_status("Gemini Live listening")
                        await self._maybe_greet(session, types)

                        # Clear stale audio chunks from mic (input) queue on reconnect
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break

                        # Clear stale audio chunks from speaker (output) queue on reconnect
                        self._flush_output(output_q)

                        sender = asyncio.create_task(self._send_audio(session, audio_queue, types))
                        try:
                            await self._receive_loop(session, output_q, types)
                        finally:
                            sender.cancel()
                            try:
                                await sender
                            except asyncio.CancelledError:
                                pass
                except Exception as exc:
                    if self._stop.is_set():
                        break
                    retries += 1
                    
                    # Responsive sleep loop
                    slept = 0.0
                    while slept < retry_delay and not self._stop.is_set():
                        await asyncio.sleep(0.1)
                        slept += 0.1
                    retry_delay = min(retry_delay * 2.0, GEMINI_LIVE_MAX_RETRY_DELAY)
```
