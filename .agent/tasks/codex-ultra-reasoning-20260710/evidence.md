# Evidence: codex-ultra-reasoning-20260710

## Verdict

**Implementation and protocol verification: PASS.** Live gateway activation is intentionally pending until the reviewed feature commit is merged into the runtime worktree.

## What changed

- Added `ultra` to the shared reasoning parser; `max` remains supported.
- Exposed `max` and `ultra` through classic CLI, command registry, Telegram/gateway session/global command, TUI gateway, and all locale guidance.
- Matched native Codex Ultra semantics:
  - configured Hermes effort: `ultra`;
  - Codex Responses API wire effort: `max`;
  - proactive Hermes delegation guidance is appended at request time only for
    `openai-codex` when `delegate_task` is loaded;
  - the persisted cacheable prompt remains unchanged and provider fallback
    removes/omits Codex-only guidance.
- Updated user docs.
- Extended the existing weekly Hermes upstream watcher so native upstream parser + command + transport support triggers an explicit “adopt upstream / remove compatibility patch” alert.

## Protocol evidence

| Check | Result | Artifact |
|---|---|---|
| Authenticated Sol catalog | `low, medium, high, xhigh, max, ultra`; Ultra description = automatic task delegation | `raw/live-catalog.txt` |
| Direct API with wire `ultra` | Expected HTTP 400; proves Ultra is not a direct Responses wire value | `raw/live-ultra-smoke.txt` |
| OpenAI Codex source | `Ultra -> Max` request mapping + `MultiAgentMode::Proactive` | `raw/openai-codex-native-semantics.txt` |
| Native Codex CLI 0.144.0 Ultra | `ULTRA_OK`, exit 0 | `raw/codex-0144-ultra-smoke.jsonl` |
| Direct API with wire `max` | `MAX_OK`, completed | `raw/live-max-wire-smoke.txt` |
| Patched Hermes configured `ultra` | wire `max`, response `ULTRA_COMPAT_OK`, completed | `raw/live-hermes-ultra-compat-smoke.txt` |
| Local integration | parser=`ultra`, wire=`max`, Ultra delegation guidance present | `raw/local-integration-smoke.txt` |

## Automated verification

- RED test run captured the missing parser/command behavior: `raw/red-tests.txt`.
- Focused GREEN run: `11 passed` (`raw/green-tests.txt`).
- First changed-surface suite: `326 passed` (`raw/test-unit.txt`).
- Final targeted+broad suite: **`1060 passed in 57.00s`** (`raw/test-targeted-broad.txt`).
- `git diff --check`: PASS.
- Python `compileall`: PASS.
- Ruff: **All checks passed** (`raw/static-checks.txt`).
- Added-line security scan: no hardcoded-secret, unsafe-exec, or SQL-interpolation hits.

## Review resolution

- Independent Codex review first found that `ultra -> max` and delegation
  guidance were too broadly scoped. Both were restricted to Codex and covered
  by non-Codex regression tests.
- A second review found stale persisted-prompt/fallback risk. Guidance was moved
  from the stable prompt to the effective request-time prompt and failover tests
  were added.
- The final auxiliary finding (the shared Responses adapter is also used by xAI
  OAuth) was fixed with an explicit backend flag and xAI regression test.
- A final external re-review attempt was blocked by Codex usage quota; fresh
  local verification after all fixes passed 1060 tests, Ruff, compileall, live
  Codex smoke, and `git diff --check`.

## Upstream precedence guard

- Current `upstream/main` native Ultra detection: `False`.
- Synthetic upstream-native detection: PASS.
- Guard artifact: `raw/upstream-guard-smoke.txt`.
- Active cron job: `Weekly Hermes fork update watcher` (`15 10 * * 1`).
- Backup of pre-change watcher: `~/.hermes/backups/hermes_fork_update_watch.pre-ultra-20260710.py`.

## Safety

- Work performed in isolated worktree `/Users/aiasistans/hermes-agent-ultra-patch` on `feature/codex-ultra-reasoning`.
- Base/runtime branch and running gateway were not modified during implementation/testing.
- Global `agent.reasoning_effort` was not changed; Ultra is not enabled by default.
- No credentials were printed or stored in proof artifacts.

## Remaining activation step

After independent review and commit/push:
1. merge the feature commit into the live runtime branch/worktree;
2. rerun targeted sanity checks there;
3. restart externally (the gateway self-restart guard forbids restart from inside its own process);
4. verify PID/runtime path/version and Telegram smoke.
