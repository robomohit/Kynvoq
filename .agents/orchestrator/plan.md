# Plan — Orynn E2E Reliability Project

## Objectives
Improve end-to-end reliability of Orynn across four core areas:
1. Gemini Live connection robustness and autoreconnect logic.
2. Resilient UIA click & type verification and self-healing.
3. Resilient overlay task and cursor state tracking.
4. Unified LLM API timeout & retry resilience.

## Execution Strategy
Using the Dual-Track Project Pattern:
1. **E2E Testing Track**: Spawn a sub-orchestrator to build the opaque-box 4-tier E2E test suite based on user requirements. This track will generate `TEST_READY.md` containing the test command and feature inventory.
2. **Implementation Track**:
   - Spawn sub-orchestrators for milestones 1, 2, 3, and 4 in parallel.
   - Each sub-orchestrator runs its own Explorer -> Worker -> Reviewer -> Challenger -> Auditor cycle.
   - Ensure the workers do not cheat, and run checks with the Forensic Auditor.
3. **Integration and Final Verification (Milestone 5)**:
   - Poll for `TEST_READY.md`.
   - Run E2E test suite (Tiers 1-4) sequentially.
   - Perform Tier 5 adversarial testing using challengers to discover untested paths, generate test cases, and fix remaining gaps.
   - Run final integrity audit.

## Milestones and Verification
1. **E2E Testing Track**: Verification via checks on generated test cases (Tiers 1-4) matching the required minimum count based on features.
2. **Milestone 1 (R1)**: Gemini Live connection robustness. Verification via mock/simulated connection dropouts.
3. **Milestone 2 (R2)**: Resilient UIA Click/Type. Verification via mock app windows or slow loading apps.
4. **Milestone 3 (R3)**: Resilient Overlay State. Verification via simulated server crashes and disconnects.
5. **Milestone 4 (R4)**: Unified LLM Retry. Verification via rate-limit/connection-failure injection.
6. **Milestone 5 (Final)**: Verification via passing 100% of E2E tests and achieving full coverage validation through Challenger and Auditor checks.
