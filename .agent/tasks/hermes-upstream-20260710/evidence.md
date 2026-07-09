# Evidence: hermes-upstream-20260710

## Summary
- Work branch: `update/upstream-2026-07-10-merge`
- Backup branch: `backup/pre-upstream-merge-20260710-003337`
- Merge commit: `a47a1f4b2` (`upstream/main` merged)
- Conflict follow-up pending commit: test expectations/evidence for Ivan-local picker curation.

## Acceptance criteria evidence

### AC1 — isolated branch + backup, no live gateway activation
PASS.
- `raw/status-after-merge-attempt.txt` and git log show work on `update/upstream-2026-07-10-merge`.
- Backup branch created: `backup/pre-upstream-merge-20260710-003337` at pre-merge local commit `83fb2383b`.
- No `hermes gateway restart`, `/restart`, or production branch switch was run.

### AC2 — upstream/main incorporated
PASS.
- `git merge --no-edit upstream/main` was run; initial conflicts captured in `raw/merge.txt`.
- Conflicts resolved in:
  - `hermes_cli/codex_models.py`
  - `hermes_cli/models.py`
  - `tests/test_tui_gateway_server.py`
  - `website/static/api/model-catalog.json`
- Merge commit created: `a47a1f4b2`.

### AC3 — Ivan-specific model picker curation preserved
PASS.
- Direct probe output:
  - Codex defaults are only `gpt-5.6-*`, `gpt-5.6-*-pro`, and `gpt-5.5`.
  - `gpt-5.3-codex-spark` is filtered out unless explicitly allowlisted.
  - OpenRouter fallback remains only `minimax/minimax-m3`.
  - Provider allowlist remains `openai-codex`, `openrouter`.
- Targeted tests: `tests/hermes_cli/test_codex_models.py`, `tests/hermes_cli/test_codex_cli_model_picker.py`, `tests/hermes_cli/test_model_picker_curation.py` pass.

### AC4 — `/learn` behavior preserved
PASS.
- Targeted tests passed:
  - `tests/tui_gateway/test_protocol.py::test_command_dispatch_learn_sends_built_prompt`
  - `tests/tui_gateway/test_protocol.py::test_pending_input_commands_includes_learn`

### AC5 — readable_tree preserved, no memory data deletion
PASS.
- Files still present under `plugins/memory/readable_tree/`, `tools/readable_memory_*`, tests and docs.
- Targeted tests passed:
  - `tests/plugins/test_readable_tree_memory.py`
  - `tests/plugins/test_readable_tree_retrieval.py`
- This pass only touched repo code; it did not delete or mutate `~/.hermes/readable_memory` data.

### AC6 — media/GGE/web plugin surfaces preserved or checked
PASS for checked surfaces.
- Telegram video attachment test passed: `tests/gateway/test_telegram_video_attachment.py`.
- Media caption split test passed: `tests/tools/test_media_caption_split.py`.
- Web tools config test passed: `tests/tools/test_web_tools_config.py`.
- Plugin files remain present under `plugins/web/*` and Telegram adapter still contains document/video/media cache handling.

### AC7 — version/update state coherent
PASS with recorded caveat.
- Source version smoke reports `Hermes Agent v0.18.2 (2026.7.7.2)`.
- `hermes_cli.__version__` reports `0.18.2` / `2026.7.7.2`.
- Caveat: installed Python distribution metadata still reports `hermes-agent 0.18.0` because this branch was not reinstalled into the venv/package metadata. This is expected before live install/sync and must be handled during activation.

### AC8 — targeted verification
PASS.
- `raw/test-unit.txt`: `206 passed in 19.89s`.
- `raw/lint.txt`: `git diff --check` + `py_compile` exited 0.
- `raw/smoke.txt`: Hermes CLI source smoke exited 0.

### AC9 — proof artifacts updated
PASS.
- Raw outputs updated under `.agent/tasks/hermes-upstream-20260710/raw/`.
- This evidence file and `evidence.json`/`verdict.json` updated.

## Commands run

```bash
git merge --no-edit upstream/main
python -m py_compile hermes_cli/codex_models.py hermes_cli/models.py tests/test_tui_gateway_server.py
python -m json.tool website/static/api/model-catalog.json
python -m pytest tests/hermes_cli/test_codex_models.py tests/hermes_cli/test_codex_cli_model_picker.py tests/hermes_cli/test_model_picker_curation.py tests/hermes_cli/test_gpt56_registration.py tests/tui_gateway/test_protocol.py::test_command_dispatch_learn_sends_built_prompt tests/tui_gateway/test_protocol.py::test_pending_input_commands_includes_learn tests/plugins/test_readable_tree_memory.py tests/plugins/test_readable_tree_retrieval.py tests/gateway/test_telegram_video_attachment.py tests/tools/test_media_caption_split.py tests/tools/test_web_tools_config.py -q -o 'addopts='
git diff --check
hermes --version
python -c "import importlib.metadata as md; from hermes_cli import __version__, __release_date__; print(__version__, __release_date__, md.version('hermes-agent'))"
```

## Post-install/sync activation-prep evidence

PASS. The local checkout venv/package metadata was synced without restarting the live gateway.

Commands and outputs:

```bash
uv pip install -e .
# Installed hermes-agent==0.18.2 (from file:///Users/aiasistans/hermes-agent-update-check)

hermes --version
# Hermes Agent v0.18.2 (2026.7.7.2) · upstream caf4dcc7 · local 29156c63 (+1862 carried commits)

python importlib.metadata smoke
# source_version= 0.18.2 2026.7.7.2
# dist_version= 0.18.2

python -m pytest <post-install targeted subset> -q -o 'addopts='
# 98 passed in 3.00s
```

Raw artifacts:
- `raw/install-sync.txt`
- `raw/post-install-smoke.txt`
- `raw/post-install-tests.txt`

Live gateway was not restarted or switched.

## Production-targeted test and restart attempt evidence

Pre-restart production-targeted pytest rerun passed:

```bash
python -m pytest <prod-targeted suite> -q -o 'addopts='
# 417 passed in 107.61s (0:01:47)
```

The first broad run had one order/flaky readable_tree assertion failure; the exact single test passed in isolation immediately after, and the full same prod-targeted suite passed on rerun. Raw outputs:
- `raw/prod-targeted-tests.txt`
- `raw/prod-targeted-tests-rerun.txt`

Gateway service definition already points at this checkout/venv:
- Program: `/Users/aiasistans/hermes-agent-update-check/.venv/bin/python -m hermes_cli.main gateway run --replace`
- Branch: `update/upstream-2026-07-10-merge`

Restart attempt from inside the serving Telegram gateway was intentionally blocked by Hermes guardrail:

```text
Blocked: cannot restart or stop the gateway from inside the gateway process.
Run `hermes gateway restart` from a separate shell outside the running gateway.
```

Current launchd gateway PID before external restart: `16750`, started `Fri Jul 10 00:14:24 2026`.
