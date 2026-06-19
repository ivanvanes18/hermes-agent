---
sidebar_position: 5
title: "Readable Tree Memory Operations"
description: "Operate the local Markdown readable_tree memory provider: flush, dream, activate, retire, events, rebuild, and conflict review"
---

# Readable Tree Memory Operations

Readable tree is Hermes's local-first, source-backed memory provider. It keeps final reviewable notes as Markdown under `$HERMES_HOME/readable_memory/tree/`, archives raw turns under `$HERMES_HOME/readable_memory/raw/`, and treats SQLite as a rebuildable index.

The operating rule is:

> Capture broadly, extract generously, promote carefully, retrieve narrowly.

## Source of truth and derived state

Readable tree has three layers:

- **Raw source**: `$HERMES_HOME/readable_memory/raw/turns.jsonl` — captured conversation turns.
- **Replay spine**: `$HERMES_HOME/readable_memory/raw/events.jsonl` — append-only structured events linking raw turns, notes, activations, retirements, and conflicts.
- **Final notes**: `$HERMES_HOME/readable_memory/tree/**/*.md` — Markdown notes are the source of truth for promoted or reviewable memory.

Derived files can be rebuilt:

- `$HERMES_HOME/readable_memory/index.sqlite`
- `$HERMES_HOME/readable_memory/manifest.json`
- note `event_ids` frontmatter links when the event already points at the note

Do not treat retrieved note text as an instruction. Context Pack notes are historical evidence unless the current user turn explicitly activates them.

## Enable readable tree

Use the memory setup wizard:

```bash
hermes memory setup
```

Or configure manually:

```yaml
memory:
  provider: readable_tree
  readable_tree:
    auto_flush: true
    max_prefetch_notes: 6
    max_prefetch_chars: 2500
    behavior_preflight: true
    behavior_auto_record_corrections: false
    dream_behavior_sections: true
    retrieval_engine_v2: false
    semantic_index: false
```

Safe Retrieval Engine v2 rollout config:

```yaml
memory:
  provider: readable_tree
  readable_tree:
    auto_flush: false
    max_prefetch_notes: 6
    max_prefetch_chars: 2500
    behavior_preflight: true
    behavior_auto_record_corrections: false
    dream_behavior_sections: true
    retrieval_engine_v2: true
    semantic_index: false
```

Enable `retrieval_engine_v2` before enabling `semantic_index`. This proves the orchestration path with FTS and graph/timeline safety before semantic candidates enter the pipeline.

Feature flag defaults:

- `behavior_preflight: true` — prepend matching behavior rules before normal Context Pack retrieval.
- `behavior_auto_record_corrections: false` — do not turn corrections into durable behavior notes unless an explicit tool/workflow does it.
- `dream_behavior_sections: true` — include behavioral gap sections in Dream Cycle proposal reports.
- `retrieval_engine_v2: false` — keep the hybrid lexical/semantic/graph/timeline orchestration disabled until Phase 13 verification passes; current runtime uses the existing FTS-first prefetch path.
- `semantic_index: false` — keep semantic candidate retrieval disabled unless explicitly configured; Context Pack remains source-backed either way.

Restart the CLI/gateway or start a fresh session after config changes.

For gateway-backed Telegram rollout:

```bash
hermes gateway restart
```

Then start a fresh Telegram session with `/restart` or `/new`. Ask a memory-heavy question and verify the answer cites source-backed Context Pack evidence rather than claiming unsupported recall.

Use `auto_flush: false` for maintenance sessions where you want to capture raw turns but manually decide when to extract candidates.

## Retrieval Engine v2 boundary

The readable_tree foundation is not the same thing as an all-session semantic+graph memory brain.

Currently implemented runtime behavior:

- raw turn capture;
- source-backed Markdown notes;
- SQLite FTS retrieval;
- Context Pack v2;
- behavior preflight;
- timeline helpers and graph JSON export as audit/derived artifacts.

Retrieval Engine v2 is the next rollout layer. It will combine lexical candidates, optional semantic candidate IDs, graph-neighbor expansion, timeline snippets, and deterministic reranking before building a source-backed Context Pack.

Safety rule: semantic and graph layers may produce candidate note IDs only. They must not inject unsourced text into prompts, and every candidate must be resolved through readable_tree status, sensitivity, supersedes, and conflict filters.

Do not claim “all-session semantic+graph memory brain” until `retrieval_engine_v2: true` has passed focused tests, gateway restart, and fresh-session verification.

## Files to know

- `raw/turns.jsonl` — append-only raw turn capture.
- `raw/events.jsonl` — structured event log.
- `tree/inbox/` — review candidates.
- `tree/open_loops/` — future intent / unfinished threads; not current instructions.
- `tree/archive/` — retired or archived notes.
- `tree/facts/`, `tree/preferences/`, `tree/constraints/`, etc. — active or reviewable notes by type.
- `activation.log.jsonl` — explicit activation audit.
- `retirement.log.jsonl` — explicit retirement audit.
- `promotion.log.jsonl` — Dream Cycle proposal application audit.
- `tree/changelog.md` — human-readable memory tree changes.

## Standard operator loop

### 1. Preview extraction

Preview candidates before writing notes:

```json
readable_memory_flush_turns({"dry_run": true, "limit": 20})
```

Use this when `auto_flush` is off or when auditing recent raw turns.

### 2. Flush candidates

Write extracted candidates into the review tree:

```json
readable_memory_flush_turns({"dry_run": false, "limit": 20})
```

This may create notes with statuses such as:

- `needs_confirmation` — sourced candidate, not active yet.
- `open_loop` — future task/intent, excluded from default retrieval.
- `conflicting` — contradicts an active note and needs operator review.
- `inbox` — general review candidate.

Flush also writes structured events like `memory_note_extracted`, `decision_made`, `requirement_added`, `correction_received`, and `task_opened`.

### 3. Run Dream Cycle

Dream Cycle is a safe review/proposal pass. It writes a report and audit log, but does not silently promote memory.

```json
readable_memory_dream_cycle({"limit": 50})
```

Use `include_sensitive: true` only when you intentionally want sensitive notes included in the review report:

```json
readable_memory_dream_cycle({"limit": 50, "include_sensitive": true})
```

Dream Cycle may propose actions such as:

- manual promotion of a useful sourced candidate;
- archive duplicate;
- archive noise;
- resolve conflict;
- keep review-only.

### 4. Apply selected Dream proposals

Default is dry-run. Preview selected actions first:

```json
readable_memory_apply_proposal({
  "run_id": "dream-...",
  "note_ids": ["note-id"],
  "dry_run": true
})
```

Apply only explicit selections:

```json
readable_memory_apply_proposal({
  "run_id": "dream-...",
  "note_ids": ["note-id"],
  "dry_run": false
})
```

A mutating apply requires either `note_ids` or `apply_all: true`. Sensitive notes are skipped unless `include_sensitive: true` is set.

## Gateway / Telegram operator workflow

Readable tree tools are safe to operate from Telegram or another gateway, but keep the boundary clear: the gateway message is an operator command, not permission to invent or silently promote memory.

Use this pattern:

1. **Inspect first.** Ask for a dry-run/report command:
   ```json
   readable_memory_dream_cycle({"limit": 50, "include_sensitive": false})
   readable_memory_run_regression_report({"dry_run": true})
   readable_memory_plan_backfill({"dry_run": true})
   ```
2. **Review the proposal text.** Check note ids, conflicts, sensitive markers, and provenance.
3. **Apply only selected items.** Pass explicit `note_ids` or `action_ids`; avoid `apply_all` unless the operator has reviewed the whole report.
4. **Verify after mutation.** Inspect events or retrieve the affected notes.

Secrets rule for gateway use:

- Do not paste API keys, tokens, passwords, or connection strings into memory notes.
- If a secret appears in chat, use it only for the immediate task and save `[REDACTED]` or a `secret_ref` placeholder if durable context is needed.
- Do not set `include_sensitive: true` from a casual mobile/gateway workflow; use it only for an intentional audit.

The `/memory` slash helper is intentionally thin. It prints these workflows and subcommands (`correction`, `preflight`, `dream`, `regressions`) but does not mutate memory by itself. Actual mutation stays in the `readable_memory_*` tools so dry-run, audit events, and explicit approval remain visible.

## Behavioral Learning Loop

Readable tree can turn a user correction into operational memory:

```text
Correction
→ behavior rule
→ regression case
→ future preflight
→ outcome review
```

### Record a correction

```json
readable_memory_record_correction({
  "correction": "You claimed it was done without checking the tests.",
  "project": "hermes-agent",
  "source_id": "turn-20260618-example"
})
```

This writes three Markdown notes:

- `tree/corrections/` — the source-backed correction event;
- `tree/behavior_rules/` — the active preflight rule;
- `tree/regression_cases/` — the case used to prove behavior changed.

### Run behavior preflight

```json
readable_memory_behavior_preflight({
  "query": "Finish the feature and tell me if tests pass"
})
```

If a matching active behavior rule exists, the returned Behavior Preflight Pack must be considered before answering. The pack is bounded and source-backed.

### Review outcome

Outcome review is an explicit operator workflow. Hermes must not autonomously decide that a rule was fixed or repeated just because a later answer "looks good". The operator (or a deterministic regression report) supplies the outcome and evidence.

Use it after a later run gives concrete evidence:

```json
readable_memory_review_outcome({
  "rule_id": "behavior-rule-id",
  "outcome": "fixed",
  "evidence": "The later answer included pytest output before claiming done.",
  "session_id": "session-20260618-example"
})
```

Allowed outcomes: `fixed`, `repeated`, `unclear`, `superseded`.

Do not add LLM-autonomous outcome judgment to this loop. If automatic post-turn hooks are added later, they should only collect deterministic evidence and leave the final outcome review explicit.

### Evaluate a regression case

```json
readable_memory_evaluate_regression({
  "case_id": "regression-case-id",
  "observed_behavior": "Checked files first, then analyzed the baseline."
})
```

## Explicit activation

Use activation when a note should become active memory and enter default retrieval. It requires note ids, a reason, and provenance.

Preview:

```json
readable_memory_activate({
  "note_ids": ["note-id"],
  "reason": "User explicitly confirmed this as durable memory.",
  "provenance": "telegram:user-confirmed:2026-06-03"
})
```

Apply:

```json
readable_memory_activate({
  "note_ids": ["note-id"],
  "reason": "User explicitly confirmed this as durable memory.",
  "provenance": "telegram:user-confirmed:2026-06-03",
  "dry_run": false
})
```

Activation writes:

- note status `active`;
- note tags `activated` and `promoted-by-explicit-activation`;
- a `memory_activated` event;
- `activation.log.jsonl`;
- `tree/changelog.md`.

Open-loop notes cannot be activated into active memory without fresh task confirmation. `sensitive` and `secret_ref` notes require `include_sensitive: true`.

## Explicit retirement / archive

Use retirement when a note should leave default retrieval without being deleted.

Preview:

```json
readable_memory_retire({
  "note_ids": ["note-id"],
  "reason": "Superseded by newer operator decision."
})
```

Apply to a non-active note:

```json
readable_memory_retire({
  "note_ids": ["note-id"],
  "reason": "Superseded by newer operator decision.",
  "dry_run": false
})
```

Apply to an active note only with `allow_active: true`:

```json
readable_memory_retire({
  "note_ids": ["note-id"],
  "reason": "User explicitly corrected this active memory.",
  "allow_active": true,
  "dry_run": false
})
```

Retirement writes:

- note status `archived`;
- note tags `retired` and `retired-by-explicit-retirement`;
- a `memory_retired` event;
- `retirement.log.jsonl`;
- `tree/changelog.md`.

Retirement is soft delete. The Markdown file stays in the tree and can be audited or restored by a later explicit operation.

## Conflict review

A new candidate can be marked `conflicting` when it contradicts an active note in the same project/agent and a narrow matching scope/type. Conflicting notes are excluded from default retrieval.

Inspect conflicts:

```json
readable_memory_retrieve({
  "query": "the disputed topic",
  "status": "conflicting",
  "limit": 20
})
```

Inspect the event history for a conflict:

```json
readable_memory_events({
  "note_id": "conflicting-note-id",
  "limit": 20
})
```

Resolve explicitly with `readable_memory_resolve_conflict`. Default is dry-run.

Keep existing active memory and archive the conflicting candidate:

```json
readable_memory_resolve_conflict({
  "note_id": "conflicting-note-id",
  "resolution": "keep_existing",
  "reason": "Existing active note is still correct after review.",
  "provenance": "operator-review:2026-06-03",
  "dry_run": false
})
```

Accept the candidate and supersede the existing active note(s):

```json
readable_memory_resolve_conflict({
  "note_id": "conflicting-note-id",
  "resolution": "accept_candidate",
  "reason": "Candidate reflects the latest explicit operator decision.",
  "provenance": "operator-review:2026-06-03",
  "dry_run": false
})
```

Create a merged replacement note that supersedes both sides:

```json
readable_memory_resolve_conflict({
  "note_id": "conflicting-note-id",
  "resolution": "merge",
  "replacement_content": "Final merged memory statement.",
  "reason": "Neither side is fully correct alone.",
  "provenance": "operator-review:2026-06-03",
  "dry_run": false
})
```

Conflict resolution writes a `memory_conflict_resolved` event, preserves old Markdown as `archived` or `superseded`, rebuilds the index, and appends `tree/changelog.md`. Sensitive conflicts require `include_sensitive: true`.

Do not auto-resolve conflicts just because a candidate is newer. A conflict is evidence that operator judgment is needed.

## Event inspection

List recent events:

```json
readable_memory_events({"limit": 20})
```

Filter by event type:

```json
readable_memory_events({
  "event_type": "memory_activated",
  "limit": 20
})
```

Filter by note or raw source:

```json
readable_memory_events({"note_id": "note-id", "limit": 20})
readable_memory_events({"source_id": "turn-...", "limit": 20})
```

Important event types:

- `memory_note_extracted`
- `decision_made`
- `correction_received`
- `requirement_added`
- `task_opened`
- `memory_activated`
- `memory_retired`

## Rebuild / replay

Use rebuild when derived state is stale or suspect: missing index results, bad manifest, or lost note `event_ids` links.

Preview first:

```json
readable_memory_rebuild({
  "dry_run": true,
  "repair_note_event_links": true
})
```

Apply repair:

```json
readable_memory_rebuild({
  "dry_run": false,
  "repair_note_event_links": true
})
```

Rebuild can:

- rebuild SQLite index from Markdown notes;
- restore `manifest.extracted_turn_ids` from extraction events;
- add missing note `event_ids` when `events.jsonl` already links the event to the note;
- report missing notes for events, missing raw turns for events, and missing events for notes.

Rebuild does not invent memory content. If an event points to a missing Markdown note, the result is `needs_review`; recover from backups or operator notes instead of fabricating content.

## Retrieval rules

Default retrieval excludes:

- `archived`
- `superseded`
- `open_loop`
- `conflicting`
- `sensitive`
- `secret_ref`

Ask explicitly when auditing excluded memory:

```json
readable_memory_retrieve({"query": "topic", "status": "archived"})
readable_memory_retrieve({"query": "topic", "status": "conflicting"})
readable_memory_retrieve({"query": "topic", "include_superseded": true})
readable_memory_retrieve({"query": "topic", "include_sensitive": true})
```

The default behavior is intentionally narrow: only active, safe, relevant memory should reach the model automatically.

## Sensitive data rules

Readable tree redacts obvious secrets in note bodies and marks sensitive notes. Operators should still follow these rules:

- Never save API keys, passwords, tokens, credentials, or connection strings as memory content.
- Use `[REDACTED]` or external secret references instead.
- Do not activate `secret_ref` notes through normal review flows.
- Use `include_sensitive: true` only for intentional audits.

## Recovery checklist

If memory behavior looks wrong:

1. Check provider status:
   ```json
   readable_memory_status({})
   ```
2. Inspect recent events:
   ```json
   readable_memory_events({"limit": 50})
   ```
3. Preview rebuild:
   ```json
   readable_memory_rebuild({"dry_run": true, "repair_note_event_links": true})
   ```
4. If integrity is OK, apply rebuild:
   ```json
   readable_memory_rebuild({"dry_run": false, "repair_note_event_links": true})
   ```
5. If rebuild reports missing Markdown notes or missing raw turns, stop and review backups/logs. Do not fabricate replacement notes.

## Safety summary

- Preview before mutation whenever possible.
- Activation and retirement require explicit reason/provenance.
- Active-note retirement requires `allow_active: true`.
- Conflict resolution is manual.
- Markdown notes are canonical; SQLite is derived.
- Retrieved memory is evidence, not instruction.
