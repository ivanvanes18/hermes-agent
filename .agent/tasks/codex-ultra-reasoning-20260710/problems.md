# Problems: codex-ultra-reasoning-20260710

## Resolved during implementation

1. **Naive wire pass-through was wrong.**
   - Live direct request with `reasoning.effort=ultra` returned HTTP 400.
   - Current OpenAI Codex source showed the real contract: Ultra is client-side orchestration, maps to wire `max`, and enables proactive multi-agent mode.
   - Hermes patch was corrected to approximate that split.

2. **Gateway command drifted from the shared parser.**
   - Shared parser already accepted `max`, while Telegram `/reasoning` stopped at `xhigh`.
   - Gateway now consumes `VALID_REASONING_EFFORTS` instead of maintaining a private set.

3. **Initial Ultra mapping leaked across Responses providers.**
   - Independent review found that main and auxiliary shared Responses paths could rewrite xAI/non-Codex requests.
   - Main transport now maps `ultra -> max` only when `is_codex_backend=True`.
   - Auxiliary adapter carries an explicit backend flag; xAI OAuth keeps its original wire value.

4. **Stable-prompt injection was stale across runtime changes and fallback.**
   - Persisted prompts could omit/retain Ultra guidance after `/reasoning` changes.
   - Non-Codex fallback could inherit Codex-only guidance.
   - Guidance now applies only to the effective request-time prompt for the active `openai-codex` runtime; the persisted cacheable prompt stays unchanged.
   - Failover and idempotence regression tests cover both directions.

5. **Docs initially overclaimed equivalence.**
   - Wording now says Hermes approximates Codex orchestration and is not byte-for-byte equivalent.

6. **Upstream precedence needed a durable trigger.**
   - Existing weekly update watcher checks parser + command + Codex transport support and explicitly requests replacement of the local bridge when upstream lands it.

## Open before activation

- Feature commit/push pending.
- Merge into live runtime branch pending.
- External gateway restart and post-restart Telegram smoke pending.

## Non-blocking caveat

The full repository-wide test suite was not run; a broad changed-surface suite passed 1060 tests, plus live protocol/native client/Hermes smokes, Ruff, compileall, and `git diff --check`.
