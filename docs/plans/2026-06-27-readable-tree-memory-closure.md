# Readable Tree Memory Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes readable_tree memory demonstrably work according to the Human 2.0 concept: broad capture, source-backed notes, narrow project-scoped Context Pack, behavior preflight, safe lifecycle, and end-to-end proof.

**Architecture:** Do not add another process/review layer. Close the memory question by turning the existing readable_tree implementation into a measured runtime with explicit evaluator output, cross-project contamination tests, behavior outcome checks, and fresh-session dogfood. Keep graph/vector optional until source-backed retrieval is proven.

**Tech Stack:** Python 3.11, pytest, Hermes readable_tree MemoryProvider, Markdown notes, SQLite FTS5, JSON/JSONL fixtures.

## Global Constraints

- No external-audit/publication layer unless Ivan explicitly asks for it.
- Every confident claim needs tool evidence: tests, generated report, runtime probe, or source-backed docs.
- Raw transcripts are source evidence, not prompt context.
- Context Pack must stay bounded and source-backed.
- Project routing is a hard safety gate: unknown/ambiguous must not silently fall back to Main.
- Behavior corrections must become behavior rules/regression cases and show preflight/outcome evidence.
- Dream Cycle remains proposal-only until explicit apply/activation.
- Do not mutate live memory notes in bulk without dry-run report and reversible action.

---

## File Structure

- `plugins/memory/readable_tree/eval.py` — deterministic evaluator for Context Pack, routing, contamination, behavior trace, and pack size.
- `tests/fixtures/readable_tree_memory_closure_cases.json` — full Human2 closure fixture matrix: Main, Hermes memory, Smeta/VOR, Projectoriy, Trading, ambiguous branch, behavior correction.
- `tests/plugins/test_readable_tree_memory_closure.py` — acceptance tests for evaluator output and end-to-end provider behavior.
- `docs/plans/2026-06-27-readable-tree-memory-closure.md` — this plan and closure gates.
- Existing files touched only if needed: `plugins/memory/readable_tree/__init__.py`, `context_pack.py`, `routing.py`, `retrieval.py`, `store.py`.

---

### Task 1: Deterministic closure evaluator

**Files:**
- Create: `plugins/memory/readable_tree/eval.py`
- Create: `tests/fixtures/readable_tree_memory_closure_cases.json`
- Create: `tests/plugins/test_readable_tree_memory_closure.py`

**Interfaces:**
- Produces: `run_memory_closure_eval(provider, cases) -> dict`
- Produces per case: `case`, `query`, `expected_branch`, `actual_branch`, `included_ids`, `excluded_ids`, `contamination_failures`, `pack_chars`, `behavior_rule_fired`, `pass`.

- [x] **Step 1: Write this plan**

Run:
```bash
test -f docs/plans/2026-06-27-readable-tree-memory-closure.md
```
Expected: exit code 0.

- [ ] **Step 2: Write failing evaluator test**

Add `tests/plugins/test_readable_tree_memory_closure.py` with a provider seeded by notes for Hermes memory, Smeta/VOR, Projectoriy, Trading, and a behavior correction. Assert:

```python
report = run_memory_closure_eval(provider, cases)
assert report["overall_pass"] is True
assert report["summary"]["contamination_failures"] == 0
assert report["summary"]["cases_passed"] == len(cases)
assert any(case["behavior_rule_fired"] for case in report["cases"])
```

Run:
```bash
python -m pytest tests/plugins/test_readable_tree_memory_closure.py -q -o 'addopts='
```
Expected: FAIL because `plugins.memory.readable_tree.eval` does not exist.

- [ ] **Step 3: Implement evaluator minimally**

Create `plugins/memory/readable_tree/eval.py` that:

1. Calls `provider.prefetch(query, session_id="closure-eval")`.
2. Parses JSON code blocks from behavior preflight + Context Pack.
3. Reads `routing_decision.branch`.
4. Reads `included_items`, `excluded_items`, `source_ids`, `preflight_trace`.
5. Calculates contamination failures from fixture `forbidden_source_ids` and `forbidden_branches`.
6. Returns a deterministic JSON-serializable report.

- [ ] **Step 4: Run evaluator test to pass**

Run:
```bash
python -m pytest tests/plugins/test_readable_tree_memory_closure.py -q -o 'addopts='
```
Expected: PASS.

### Task 2: Cross-project closure matrix

**Files:**
- Modify: `tests/fixtures/readable_tree_memory_closure_cases.json`
- Modify: `tests/plugins/test_readable_tree_memory_closure.py`

**Interfaces:**
- Consumes evaluator from Task 1.
- Produces fixture coverage for Human2 closure scenario.

- [ ] **Step 1: Add fixture cases**

Cases:
1. Hermes memory query includes Hermes memory note and excludes trading/VOR/projectoriy sources.
2. Smeta/VOR query routes to Projectoriy/smeta domain and excludes trading source.
3. Trading query routes to trading and excludes Projectoriy/VOR source.
4. Ambiguous query returns `clarification_required` and does not include cross-project notes.
5. Behavior correction query fires a rule and emits `preflight_trace`.

- [ ] **Step 2: Run targeted tests**

Run:
```bash
python -m pytest tests/plugins/test_readable_tree_memory_closure.py tests/plugins/test_readable_tree_context_pack_contract.py -q -o 'addopts='
```
Expected: PASS.

### Task 3: Fresh runtime dogfood through MemoryManager

**Files:**
- Modify: `tests/plugins/test_readable_tree_memory_closure.py`

**Interfaces:**
- Proves the provider works through the live MemoryManager tool path, not only direct store classes.

- [ ] **Step 1: Add MemoryManager smoke test**

Use `load_memory_provider("readable_tree")`, initialize with temp `hermes_home`, add to `MemoryManager`, and call:

```python
mgr.handle_tool_call("readable_memory_status", {})
mgr.handle_tool_call("readable_memory_record_correction", {...})
mgr.handle_tool_call("readable_memory_behavior_preflight", {"query": ...})
```

Assert tool schemas exist and behavior preflight returns `preflight_trace`.

- [ ] **Step 2: Run smoke test**

Run:
```bash
python -m pytest tests/plugins/test_readable_tree_memory_closure.py::test_memory_closure_runtime_tool_path -q -o 'addopts='
```
Expected: PASS.

### Task 4: Broader verification and commit

**Files:**
- All intentional Task 1–3 files.

- [ ] **Step 1: Run broader readable_tree tests**

Run:
```bash
python -m pytest tests/plugins/test_readable_tree_context_pack_contract.py \
  tests/plugins/test_readable_tree_retrieval.py \
  tests/plugins/test_readable_tree_behavioral.py \
  tests/plugins/test_readable_tree_memory.py \
  tests/plugins/test_readable_tree_lifecycle.py \
  tests/plugins/test_readable_tree_metrics.py \
  tests/plugins/test_readable_tree_memory_closure.py \
  -q -o 'addopts='
```
Expected: PASS.

- [ ] **Step 2: Syntax and diff checks**

Run:
```bash
python -m py_compile plugins/memory/readable_tree/eval.py
git diff --check
```
Expected: exit code 0.

- [ ] **Step 3: Commit and push**

Run:
```bash
git add docs/plans/2026-06-27-readable-tree-memory-closure.md \
  plugins/memory/readable_tree/eval.py \
  tests/fixtures/readable_tree_memory_closure_cases.json \
  tests/plugins/test_readable_tree_memory_closure.py
git commit -m "test: add readable tree memory closure eval"
git push origin ivan/prod
```

### Task 5: Next closure gates after evaluator

Do these only after Task 1–4 pass:

1. [x] Outcome review closure: `review_behavior_outcome` now records `rule_used_in_answer`, links related active regression cases, and closes them in the regression report through `case:<id>` tags.
2. [x] Provenance closure: high-risk active `behavior_rule` / `regression_case` / high-importance decision-like notes missing `event_ids` are detected first in dry-run, and selected-only `readable_memory_apply_backfill` can mark/link them without bulk mutation.
3. [ ] Dream Cycle closure: prove proposal/apply separation with seeded inbox/duplicate/stale notes and no silent promotion.
4. [ ] Fresh-session closure: restart/fresh Hermes session dogfood and compare Context Pack output.

The memory architecture is considered closed only when these gates have tool-backed evidence, not when the docs say it is closed.
