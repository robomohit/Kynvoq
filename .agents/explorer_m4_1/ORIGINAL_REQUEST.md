## 2026-06-17T18:45:56-07:00
You are a teamwork_preview_explorer agent.
Your working directory is: c:\Users\ACER\Desktop\Ai_computer\Orynn\.agents\explorer_m4_1
Your identity is: teamwork_preview_explorer
Your mission is to analyze app/providers.py and recommend a fix strategy for Milestone 4 (Unified LLM API Timeout & Retry Resilience).

Goal:
Standardize retry behavior across all provider calls (`_chat_groq`, `_chat_openrouter`, etc.) with exponential backoff retries for status codes `429`, `408`, `5xx`, and connection errors. Log warning messages to client logs.

Scope context:
- Project file: c:\Users\ACER\Desktop\Ai_computer\Orynn\PROJECT.md
- Scope file: c:\Users\ACER\Desktop\Ai_computer\Orynn\.agents\sub_orch_m4\SCOPE.md

Please write your findings and recommended strategy to `analysis.md` inside your working directory. Then write your handoff.md and send a message back to the sub-orchestrator conversation ID 9f87b0d2-a91a-4422-9c23-727f736fabb4 with a summary and the file path.
