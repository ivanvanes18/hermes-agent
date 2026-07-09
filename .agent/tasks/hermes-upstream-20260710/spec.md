# Task Spec: hermes-upstream-20260710

## Metadata
- Task ID: hermes-upstream-20260710
- Repo root: /Users/aiasistans/hermes-agent-update-check
- Starting branch: update/upstream-2026-07-05-check @ 83fb2383b
- Work branch: update/upstream-2026-07-10-merge
- Backup branch: backup/pre-upstream-merge-20260710-003337
- Upstream target: upstream/main @ 111544d54 after fetch on 2026-07-10

## Guidance sources
- Repo `AGENTS.md` development guide.
- `hermes-agent` skill and live CLI/git output.
- User instruction: “сделаем аккуратно… размеренно по шагам”.

## Original task statement
Аккуратно подтянуть upstream/main Nous Hermes в локальную ветку Ивана, сохранив локальные кастомы: ограниченный model picker, /learn, readable_tree memory, media/GGE attachments, web plugins visibility. Не переключать рабочий gateway без отдельного подтверждения. Проверить targeted tests и smoke.

## Acceptance criteria
- AC1: Work happens on an isolated update branch with a backup branch from the pre-merge local state; no direct mutation of `ivan/prod` or running gateway activation.
- AC2: The branch incorporates current `upstream/main` changes, or if blocked, the blocker is captured with exact conflict/status evidence.
- AC3: Ivan-specific model picker curation remains present after merge and does not get overwritten by upstream model catalog/picker changes.
- AC4: Local `/learn` behavior remains present or is deliberately reconciled with upstream skill/learn changes without silently dropping it.
- AC5: Local readable_tree memory provider/tooling is preserved or explicitly isolated from upstream removals; no memory data is deleted.
- AC6: Local gateway/media/GGE attachment behavior and configured web plugin visibility are preserved or their conflicts are documented with a minimal fix plan.
- AC7: Version metadata and update state are coherent: local code reports the expected upstream release/version or explicitly records remaining local version divergence.
- AC8: Targeted verification runs cover at least: model picker, skills/learn or skill discovery, readable_tree if present, gateway/media attachment surface, and a Hermes CLI smoke (`hermes --version` or import-level smoke). Any skipped check must have a concrete reason.
- AC9: Evidence artifacts under `.agent/tasks/hermes-upstream-20260710/` are updated with commands, exit codes, and final status before claiming completion.

## Constraints
- Do not run `hermes gateway restart`, `/restart`, or switch the live production Hermes/gateway without separate explicit confirmation from Ivan.
- Do not use `git reset --hard`, destructive cleanup, or discard local commits without explicit confirmation.
- Preserve local authored commits and contributor attribution where possible.
- Prefer smallest conflict resolutions that keep upstream intent and Ivan-specific local behavior.
- Treat old readable_tree code as locally important even if upstream removed it.
- Do not commit unrelated generated or environment noise unless it is part of the proof-loop artifacts or intentionally needed.

## Non-goals
- No PyPI/package installation into the live Hermes runtime during this pass.
- No production gateway activation.
- No redesign of Hermes architecture beyond merge conflict resolution.
- No publishing/pushing unless Ivan asks after local verification.

## Verification plan
- Pre-merge baseline: `git status --short --branch`, `git rev-list --left-right --count HEAD...upstream/main`.
- Merge evidence: `git merge upstream/main` output and conflict list if any.
- Static checks: inspect conflict resolutions around model picker, `/learn`, readable_tree, gateway media/GGE, web plugins.
- Targeted tests after merge: choose existing tests by file discovery, e.g. `test_codex_models`, `test_model_picker`, `test_skill_commands`, `test_skills_tool_discovery_cache`, readable_tree tests if retained, gateway media/telegram/GGE tests if present.
- CLI smoke: local venv `hermes --version`; Python import/version check.
- Hygiene: `git diff --check`, `git status --short --branch`, update evidence/verdict.
