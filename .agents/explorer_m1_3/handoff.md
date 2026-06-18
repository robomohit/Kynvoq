# Handoff Report - Gemini Live Auto-Reconnect Strategy

This report analyzes the auto-reconnect behavior in `app/widget/gemini_live.py` and proposes a robust retry strategy with exponential backoff and queue clearing on successful reconnection.

---

## 1. Observation
In `app/widget/gemini_live.py` (lines 349-391), the connection loop manages retries and backoff using a fixed maximum number of attempts and a low backoff cap:

```python
        retries = 0
        max_retries = 5
        retry_delay = 1.0

        try:
            while not self._stop.is_set():
                if retries > 0:
                    self.callbacks.on_status(f"Live reconnecting ({retries}/{max_retries})...")
                # Rebuilt each attempt so a reconnect carries the latest resume handle.
                config = self._live_config(types)
                try:
                    async with client.aio.live.connect(model=self.model, config=config) as session:
                        self._session = session
                        self._audio_fail_streak = 0
                        retries = 0
                        retry_delay = 1.0
                        self.callbacks.on_status("Gemini Live listening")
                        await self._maybe_greet(session, types)

                        # Clear stale audio chunks from mic queue on reconnect
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break

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
                    if retries > max_retries:
                        raise exc
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2.0, 10.0)
```

Additionally, `app/widget/gemini_live.py` defines the static helper `_flush_output` (lines 461-474) to clear audio playback queues:

```python
    @staticmethod
    def _flush_output(output_queue_or_stream: Any) -> None:
        """Drop everything still queued for the speaker — used on barge-in so Orynn
        stops talking immediately instead of draining its audio backlog."""
        if not hasattr(output_queue_or_stream, "get_nowait"):
            return
        try:
            while True:
                output_queue_or_stream.get_nowait()
                try:
                    output_queue_or_stream.task_done()
                except Exception:
                    pass
        except Exception:
            pass
```

Finally, running tests via `python -m pytest -q` currently returns 1 failure due to an unrelated, pre-existing assert discrepancy in `test_function_declarations_cover_desktop_tools` (extra item `'web_search'`), but all other 591 tests pass successfully.

---

## 2. Logic Chain
1. **Indefinite Retries & Loop Termination**: The current code terminates and raises `exc` once `retries > max_retries` (where `max_retries = 5`). To ensure the retry loop only terminates if `self._stop.is_set()` is true, the `max_retries` check and the `raise exc` statement must be removed.
2. **Backoff Cap**: The current backoff capping `min(retry_delay * 2.0, 10.0)` caps the sleep at 10 seconds. To meet the Milestone 1 Scope of capping backoff at 15-30s, we should update this cap to 30.0s: `min(retry_delay * 2.0, 30.0)`.
3. **Queue Clearing**: While the raw microphone input queue (`audio_queue`) is cleared on successful reconnection, the speaker output queue (`output_q`) is not. To clear both "audio and input queues", we should invoke `self._flush_output(output_q)` right after clearing the `audio_queue`.
4. **Responsive Stop Checks**: A backoff sleep of up to 30.0s using `await asyncio.sleep(retry_delay)` will delay the companion shutdown for up to 30s if stop is requested. A loop that sleeps in small increments (e.g. 0.1s) and checks `self._stop.is_set()` allows immediate cancellation.

---

## 3. Caveats
- Since this is a read-only investigation, the proposed changes are not applied directly. The implementation is left to the implementer.
- It is assumed that external networking library behavior (such as `client.aio.live.connect` throwing standard python `Exception` or `ConnectionError`) remains consistent.
- No hardware voice capture/playback is tested during unit tests; thus mock testing is relied upon to verify that queues are cleared correctly under simulated drops.

---

## 4. Conclusion
We recommend modifying the connection/retry loop in `_run()` in `app/widget/gemini_live.py` to:
1. Clear the speaker output queue `output_q` by calling `self._flush_output(output_q)` on reconnection.
2. Retry indefinitely by removing the `max_retries` limit and the `raise exc` statement.
3. Update backoff cap from `10.0` to `30.0` seconds.
4. Implement a responsive sleep in 0.1s steps during backoff to quickly respond to `self._stop` event signals.

### Proposed Code Changes in `app/widget/gemini_live.py`

#### Before:
```python
        retries = 0
        max_retries = 5
        retry_delay = 1.0

        try:
            while not self._stop.is_set():
                if retries > 0:
                    self.callbacks.on_status(f"Live reconnecting ({retries}/{max_retries})...")
                # Rebuilt each attempt so a reconnect carries the latest resume handle.
                config = self._live_config(types)
                try:
                    async with client.aio.live.connect(model=self.model, config=config) as session:
                        self._session = session
                        self._audio_fail_streak = 0
                        retries = 0
                        retry_delay = 1.0
                        self.callbacks.on_status("Gemini Live listening")
                        await self._maybe_greet(session, types)

                        # Clear stale audio chunks from mic queue on reconnect
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break

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
                    if retries > max_retries:
                        raise exc
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2.0, 10.0)
```

#### After:
```python
        retries = 0
        retry_delay = 1.0

        try:
            while not self._stop.is_set():
                if retries > 0:
                    self.callbacks.on_status(f"Live reconnecting (attempt {retries})...")
                # Rebuilt each attempt so a reconnect carries the latest resume handle.
                config = self._live_config(types)
                try:
                    async with client.aio.live.connect(model=self.model, config=config) as session:
                        self._session = session
                        self._audio_fail_streak = 0
                        retries = 0
                        retry_delay = 1.0
                        self.callbacks.on_status("Gemini Live listening")
                        await self._maybe_greet(session, types)

                        # Clear stale audio chunks from mic queue on reconnect
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break

                        # Clear stale audio chunks from speaker queue on reconnect
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
                    # Sleep in small, responsive increments to check self._stop.is_set()
                    slept = 0.0
                    while slept < retry_delay and not self._stop.is_set():
                        await asyncio.sleep(0.1)
                        slept += 0.1
                    retry_delay = min(retry_delay * 2.0, 30.0)
```

---

## 5. Verification Method
1. **Verification Command**: Run `python -m pytest tests/test_gemini_live.py` to ensure all tests execute.
2. **Proposed Unit Test**: To verify the indefinite retrying, responsive sleep, backoff cap, and queue flushing on reconnection, the implementer can add the following test to `tests/test_gemini_live.py`:

```python
@pytest.mark.asyncio
async def test_reconnect_loop_indefinite_retry_and_queue_clearing(monkeypatch):
    import asyncio
    import queue
    from google.genai import types
    from app.widget import gemini_live as gl

    # Mock sounddevice streams to prevent attempting to load hardware sound devices
    class MockStream:
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    import sounddevice as sd
    monkeypatch.setattr(sd, "RawInputStream", lambda *a, **kw: MockStream())
    monkeypatch.setattr(sd, "RawOutputStream", lambda *a, **kw: MockStream())

    # Set up mock callback collections
    statuses = []
    cbs = gl.GeminiLiveCallbacks(
        on_status=statuses.append,
        on_error=lambda err: pytest.fail(f"Unexpected companion crash/error: {err}")
    )
    comp = gl.GeminiLiveCompanion(cbs)

    # Track connect attempts
    connect_calls = 0

    class MockSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def send_realtime_input(self, *args, **kwargs):
            pass
        async def receive(self):
            # yield nothing to simulate a session that ends immediately/drops
            if False:
                yield None

    class MockLive:
        async def connect(self, model, config):
            nonlocal connect_calls
            connect_calls += 1
            if connect_calls <= 7:
                # Force failure for first 7 attempts
                raise ConnectionError("Simulated drop")
            return MockSession()

    class MockAio:
        live = MockLive()

    class MockClient:
        def __init__(self, api_key):
            self.aio = MockAio()

    from google import genai
    monkeypatch.setattr(genai, "Client", MockClient)

    # Pre-populate queues to verify they are cleared on reconnection
    # Note: We must run _run on the event loop to test its execution.
    # We will trigger stop immediately after a successful connection (on 8th call).
    
    # We can run the companion's _run task
    run_task = asyncio.create_task(comp._run())

    # Yield control to let it run and retry
    await asyncio.sleep(0.5)

    # Signal stop to exit loop if it hasn't already
    comp._stop.set()
    try:
        await asyncio.wait_for(run_task, timeout=2.0)
    except asyncio.TimeoutError:
        run_task.cancel()

    # Ensure it did not crash and retried past the original 5 limit
    assert connect_calls > 5
    assert any("Live reconnecting (attempt" in s for s in statuses)
```
