# Scope: Milestone 1 - Gemini Live Robustness (R1)

## Architecture
- Target: `app/widget/gemini_live.py`
- Problem: The connection loop retries only up to 5 times (exponential backoff capped at 10s) before terminating session.
- Solution: Retries indefinitely (or for a long period like 10-15 minutes) when connection drops, backoff capped at 15-30s. Connection loop only terminates if `self._stop.is_set()`. Clear audio/input queues on successful reconnection.

## Verification
- Unit/integration tests simulating connection dropouts and checking reconnection and queue clearing.
