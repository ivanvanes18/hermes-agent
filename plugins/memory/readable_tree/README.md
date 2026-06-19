# readable_tree memory provider

`readable_tree` is a local-first Hermes memory provider.

Principle:

```text
Capture broadly.
Extract generously.
Promote carefully.
Retrieve narrowly.
```

## Storage

The provider stores source-of-truth Markdown under the active profile:

```text
$HERMES_HOME/readable_memory/
  tree/
    inbox/
    facts/
    decisions/
    projects/
    corrections/
    constraints/
    procedures/
    reviews/
      dream-cycle/
    archive/
  raw/turns.jsonl
  index.sqlite
  manifest.json
  retrieval.log.jsonl
  dream.log.jsonl
  promotion.log.jsonl
```

Markdown memory notes are authoritative. `index.sqlite`, `manifest.json`, and JSONL logs are rebuildable/audit artifacts.

## Activation

Set in the active Hermes profile:

```yaml
memory:
  provider: readable_tree
```

## Tools

- `readable_memory_status`
- `readable_memory_retrieve`
- `readable_memory_write`
- `readable_memory_flush_turns`
- `readable_memory_dream_cycle`
- `readable_memory_apply_proposal`

Default retrieval excludes `sensitive` and `secret_ref` notes.

## Dream Cycle v0

`readable_memory_dream_cycle` runs a deterministic review/proposal pass over reviewable notes (`inbox`, `needs_confirmation`, `conflicting`, `uncertain`). It writes:

- proposal Markdown under `tree/reviews/dream-cycle/`;
- audit JSONL entries to `dream.log.jsonl`;
- a short changelog entry.

It deliberately does **not** silently promote memories, edit constitution files (`SOUL.md`, `USER.md`, `MEMORY.md`, `AGENTS.md`), or treat hypotheses/open loops as instructions. Sensitive excerpts are redacted by default.

## Promotion Workflow

`readable_memory_apply_proposal` is the separate Phase 3.2 apply layer for Dream Cycle reports.

Defaults and guardrails:

- `dry_run=true` by default, so calls preview the mutation plan first;
- mutating calls require either explicit `note_ids` or `apply_all=true`;
- only deterministic safe actions are applied automatically: `candidate_for_manual_promotion`, `propose_archive_duplicate`, and `propose_archive_noise`;
- review-only actions stay skipped for human judgement;
- sensitive / `secret_ref` notes are skipped unless `include_sensitive=true` is explicitly passed;
- notes are moved between `inbox/`, typed active folders, and `archive/` by status;
- every mutating apply writes `promotion.log.jsonl`, rebuilds the index, and appends `tree/changelog.md`.
