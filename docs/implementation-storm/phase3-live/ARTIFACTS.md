# Phase 3 Live Test Artifacts

**Session run:** 2026-06-22 ~20:17–20:18 UTC  
**Env:** `ORYNN_LABEL_LOG=1`, backend port 8000

---

## Bundled paths (this folder)

| Artifact | Path | Description |
|----------|------|-------------|
| Gate results JSON | `docs/implementation-storm/phase3-live/gate_results.json` | Per-scenario tools, replies, pass flags |
| Gate runner script | `docs/implementation-storm/phase3-live/run_phase3_gates.py` | Reproducible sequential harness |
| Label log slice | `docs/implementation-storm/phase3-live/artifacts/textbox_labels_session_slice.jsonl` | Last 80 lines incl. Phase 3 session (lines 70–80 are live run) |
| Calculator task | `docs/implementation-storm/phase3-live/artifacts/clicky-c1427765ef.json` | E04 backend — `Display showed 391.` |
| Notepad task | `docs/implementation-storm/phase3-live/artifacts/clicky-4a9dc02a07.json` | Complex task — typed hello world |
| Debug NDJSON (historical) | `docs/implementation-storm/phase3-live/artifacts/debug-eec63b.log` | Copy of `Ai_computer/debug-eec63b.log` — pre-Phase-3 forensics |

---

## Source log paths (not copied — use for Phase 4 mining)

| Artifact | Path | Notes |
|----------|------|-------|
| Full label log | `C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\textbox_labels.jsonl` | **Phase 3 slice starts ~ts 1782159423** (`Opening spotify`) |
| Desktop live log | `C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\run_desktop_live.log` | Backend/overlay startup |
| Prior QA matrix | `C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\live_qa_matrix_summary.json` | Pre-Phase-3 routing baseline |
| Prior e2e drive | `C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\live_e2e_drive_summary.json` | Pre-Phase-3 leak scan |

---

## Phase 3 session label highlights

From `textbox_labels_session_slice.jsonl` (Phase 3 only, `live: false` offscreen harness):

```
Opening spotify
Started: Open Calculator and calculate 17 times 23.
Busy: Open Calculator and calculate 17 times 23.
Opening notepad
Started: open Notepad and type hello world
Busy: open Notepad and type hello world
Searching: who won the last Super Bowl
Sources: topendsports.com, en.wikipedia.org, msn.com
Searching: who won Super Bowl LX
Sources: en.wikipedia.org, espn.com, cbc.ca
```

**No** `Failed: Server restarted` in Phase 3 slice.

**Historical leaks** (same file, earlier timestamps ~1782151129–1782151132): `Failed: Server restarted or task was abandoned.` — pre-Phase-2-fix session; compare for regression proof.

---

## Task JSON created this session

| Task ID | Goal | Status | Reason |
|---------|------|--------|--------|
| `clicky-c1427765ef` | Calculator 17×23 | done | Display showed 391. |
| `clicky-4a9dc02a07` | Notepad hello world | done | Typed "hello world" into Notepad |

---

## Debug NDJSON

- **Location:** `C:\Users\ACER\Desktop\Ai_computer\Ai_computer\debug-eec63b.log`
- **Bundled copy:** `artifacts/debug-eec63b.log`
- **Phase 3 note:** No new NDJSON written during offscreen gate run (instrumentation tied to full overlay Live session). Phase 4 should slice pre/post Phase 3 timestamps.

---

## Tail commands (PowerShell)

```powershell
# Phase 3 label slice
Get-Content C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\textbox_labels.jsonl -Tail 30

# Watch live (full overlay session)
Get-Content -Wait C:\Users\ACER\Desktop\Ai_computer\Orynn\logs\textbox_labels.jsonl
```

---

## Re-run gate harness

```powershell
cd C:\Users\ACER\Desktop\Ai_computer\Orynn
$env:ORYNN_LABEL_LOG = "1"
python docs/implementation-storm/phase3-live/run_phase3_gates.py
```
