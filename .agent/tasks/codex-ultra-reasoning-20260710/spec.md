# Task Spec: codex-ultra-reasoning-20260710

## Metadata
- Task ID: codex-ultra-reasoning-20260710
- Created: 2026-07-10
- Repo root: `/Users/aiasistans/hermes-agent-ultra-patch`
- Base commit: `51e7ee389e0266930311ac127d6602235f8a43f9`
- Base branch: `update/upstream-2026-07-10-merge`
- Feature branch: `feature/codex-ultra-reasoning`

## Goal
Add a minimal, reversible Hermes compatibility bridge for the Codex `max` and `ultra` reasoning modes used by GPT-5.6 Sol/Terra.

## Protocol facts verified during implementation
1. The authenticated Codex model catalog exposes `low`, `medium`, `high`, `xhigh`, `max`, and `ultra` for `gpt-5.6-sol`; Ultra is described as maximum reasoning with automatic task delegation.
2. Passing `reasoning.effort = ultra` directly to the ChatGPT Codex Responses API returns HTTP 400.
3. OpenAI Codex `0.144.0` accepts `model_reasoning_effort = ultra` and completes a live request.
4. Current `openai/codex` source implements Ultra client-side: `Ultra -> Max` on the wire plus proactive multi-agent behavior in the client runtime.

## Acceptance criteria
1. Shared reasoning parser accepts `max` and `ultra`; unknown values are still rejected.
2. Classic CLI, Telegram/gateway session/global command, TUI gateway, and command registry accept and display `max`/`ultra`.
3. All gateway locale guidance advertises `max` and `ultra`.
4. Main and auxiliary Codex transports map configured `ultra` to wire `max`; `max` remains `max`.
5. When `reasoning_effort=ultra`, the active provider is `openai-codex`, and `delegate_task` is loaded, the effective request-time system prompt enables proactive Hermes delegation guidance. The persisted cacheable prompt remains unchanged, and non-Codex fallbacks do not receive the guidance.
6. Live Codex checks prove:
   - catalog advertises Ultra;
   - direct `ultra` wire value is rejected (expected protocol evidence);
   - direct `max` request succeeds;
   - native Codex CLI `0.144.0` Ultra request succeeds.
7. The patch does not switch the global reasoning default or restart the gateway until tests and review pass.
8. A durable upstream guard exists:
   - source comments mark this as a temporary compatibility bridge;
   - weekly Hermes upstream watcher reports when upstream has native parser + command + transport/orchestration support;
   - when native upstream support appears, upstream implementation wins and local-only bridge code is removed/reconciled.
9. Relevant tests pass; `git diff --check` and Python compile checks are clean.
10. Final activation preserves the live gateway and Telegram path; rollback remains available from the pre-merge branch/commit.

## Scope
- `hermes_constants.py`
- reasoning command surfaces and locales
- Codex main/auxiliary transports
- request-time Ultra guidance and provider-fallback reconciliation
- focused tests and user docs
- `~/.hermes/scripts/hermes_fork_update_watch.py` guard (same active profile)

## Explicit non-goals
- Do not add a fake `gpt-5.6-sol-ultra` model alias.
- Do not send `ultra` directly to the Responses API.
- Do not claim Hermes background delegation is byte-for-byte identical to Codex's internal multi-agent runtime.
- Do not make Ultra the global default.
- Do not merge unrelated upstream commits.
- Do not create a PR unless requested.
