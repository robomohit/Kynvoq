# Handoff Report: Milestone 1 - Gemini Live Auto-Reconnect Strategy

## 1. Observation
In `app/widget/gemini_live.py`, the Gemini Live companion connection loop handles connection attempts, retries, and backoff as follows (lines 349-391):

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

Additionally, `GeminiLiveCompanion` contains a static helper method to flush the speaker playback queue on barge-in (lines 461-475):

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

## 2. Logic Chain

1. **Retrying Indefinitely**:
   - *Observation*: The condition `if retries > max_retries: raise exc` causes the connection loop to propagate the connection exception and terminate the session after 5 failed attempts.
   - *Reasoning*: Removing this check ensures that the connection loop will not terminate on exceptions, but will instead retry indefinitely. The loop will only terminate if `self._stop.is_set()` evaluates to `True`.

2. **Capping Exponential Backoff at 15-30s**:
   - *Observation*: Currently, `retry_delay = min(retry_delay * 2.0, 10.0)` caps the backoff delay at `10.0` seconds.
   - *Reasoning*: To increase the cap to a value within the 15-30s range, we can introduce a constant (e.g., `GEMINI_LIVE_MAX_RETRY_DELAY = 30.0`) and update the cap to use this value.

3. **Responsive / Interruptible Sleep**:
   - *Observation*: When a connection fails, `await asyncio.sleep(retry_delay)` is called. If the delay grows up to 30.0s, calling `.stop()` (which sets `self._stop`) will not immediately stop the thread; it will remain blocked in `asyncio.sleep` until the sleep timer expires.
   - *Reasoning*: To make the retry loop instantly responsive to stop requests, the single long sleep should be replaced by a loop that sleeps in short increments (e.g., 0.1s) and continuously checks `self._stop.is_set()`.

4. **Clearing Audio and Input Queues**:
   - *Observation*: On a successful reconnection, only the microphone queue (`audio_queue`) is cleared. The speaker playback queue (`output_q`) is left unchanged. If the connection dropped mid-response, stale audio bytes remain in `output_q`, causing them to be played over the speaker when reconnected.
   - *Reasoning*: Both the microphone queue (`audio_queue`) and speaker queue (`output_q`) should be cleared upon a successful connection. We can flush `output_q` by invoking the existing `self._flush_output(output_q)` method.

## 3. Caveats
- **Persistent Resource Usage**: Retrying indefinitely when there is a persistent network outage (e.g., no internet for hours) will keep the thread active and continuously attempting connections every 30 seconds. This is the desired behavior for a robust companion, but it will print logs and consume minor CPU resources until stopped by the user.
- **Session Expiration**: Although the API client attempts conversation resumption using `self._resume_handle`, the Gemini Live API backend may expire the resumption handle after a certain duration of disconnection (typically a few minutes). If expired, the API will reject the resumption handle and open a fresh conversation. The client handles this gracefully, but the conversation history since the start of that session might be lost.

## 4. Conclusion
We recommend modifying the connection retry logic in `app/widget/gemini_live.py` as follows:

### Proposed Constants (around line 33)
```python
# Backoff settings for auto-reconnect
GEMINI_LIVE_INITIAL_RETRY_DELAY = 1.0
GEMINI_LIVE_MAX_RETRY_DELAY = 30.0
```

### Proposed Changes in `_run` (before -> after)

**Before:**
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

**After:**
```python
        retries = 0
        retry_delay = GEMINI_LIVE_INITIAL_RETRY_DELAY

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
                        retry_delay = GEMINI_LIVE_INITIAL_RETRY_DELAY
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
                    
                    # Sleep in small, interruptible increments to keep the thread responsive to stops
                    sleep_steps = int(retry_delay * 10)
                    for _ in range(sleep_steps):
                        if self._stop.is_set():
                            break
                        await asyncio.sleep(0.1)
                    
                    retry_delay = min(retry_delay * 2.0, GEMINI_LIVE_MAX_RETRY_DELAY)
```

## 5. Verification Method

### 1. Execution of Current Tests
To ensure existing functionality is not broken, execute the test suite:
```powershell
pytest tests/test_gemini_live.py
```

### 2. New Test Cases for Verification
We recommend adding the following test cases in `tests/test_gemini_live.py` to verify the new auto-reconnect behavior:

```python
def test_live_auto_reconnect_indefinitely_and_clears_queues(monkeypatch):
    """Verify that GeminiLiveCompanion retries connecting indefinitely on failures,
    caps backoff, and clears both input and output queues upon a successful connection.
    """
    import asyncio
    from google.genai import types
    from app.widget import gemini_live as gl

    connect_attempts = 0
    max_failures_to_simulate = 7

    class FakeSession:
        async def __aenter__(self):
            nonlocal connect_attempts
            connect_attempts += 1
            if connect_attempts <= max_failures_to_simulate:
                raise OSError("Connection failed")
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def send_realtime_input(self, **kwargs):
            pass

        async def receive(self):
            # yield nothing to end the receive loop immediately
            if False:
                yield None

    class FakeClient:
        class aio:
            class live:
                @staticmethod
                def connect(model, config):
                    return FakeSession()

    monkeypatch.setattr(gl, "gemini_api_key", lambda: "fake-key")
    
    statuses = []
    cbs = gl.GeminiLiveCallbacks(
        on_status=statuses.append,
        on_error=lambda err: pytest.fail(f"Should not trigger fatal error: {err}")
    )

    comp = gl.GeminiLiveCompanion(cbs)
    
    # We mock sd.RawInputStream and RawOutputStream to avoid opening audio hardware
    monkeypatch.setattr("sounddevice.RawInputStream", lambda **kw: object())
    monkeypatch.setattr("sounddevice.RawOutputStream", lambda **kw: object())
    
    # Run loop for a short duration using a custom runner or mock run
    # To test the retry loop synchronously, we can mock client.aio.live.connect in a test:
    # ...
```

A complete implementation of the test case could mock the connection method to fail 7 times and verify `connect_attempts` reaches 8, and assert that `output_q` and `audio_queue` are empty.
