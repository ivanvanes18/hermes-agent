from pathlib import Path

from plugins.memory.readable_tree.context_pack import build_context_pack
from plugins.memory.readable_tree.lifecycle import build_evolution_chain, can_activate, detect_context_conflicts
from plugins.memory.readable_tree.schemas import MemoryNote
from plugins.memory.readable_tree.timeline import build_timeline, export_memory_graph, summarize_timeline_for_notes

from plugins.memory.readable_tree.store import ReadableMemoryStore


def _context_pack_json(context: str) -> dict:
    import json

    payload = context.split("```json\n", 1)[1].split("\n```", 1)[0]
    return json.loads(payload)


def test_timeline_builds_event_order_and_context_pack_snippets():
    events = [
        {
            "id": "evt-2",
            "timestamp": "2026-01-02T00:00:00Z",
            "type": "memory_note_superseded",
            "note_ids": ["new-note", "old-note"],
            "source_ids": ["turn-2"],
            "payload": {"reason": "newer correction"},
        },
        {
            "id": "evt-1",
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "memory_note_activated",
            "note_ids": ["old-note"],
            "source_ids": ["turn-1"],
            "payload": {"reason": "operator accepted"},
        },
    ]

    timeline = build_timeline(events)
    snippets = summarize_timeline_for_notes(timeline, ["old-note"], limit=5)
    context = build_context_pack(
        "old note",
        [
            {
                "id": "old-note",
                "status": "active",
                "type": "fact",
                "importance": "normal",
                "source_quality": "session",
                "pinned": "0",
                "path": "tree/facts/old-note.md",
                "source_ids": "turn-1",
                "event_ids": "evt-1,evt-2",
                "body": "Historical fact.",
            }
        ],
        max_chars=5000,
        timeline_events=timeline,
    )
    pack = _context_pack_json(context)

    assert [row["event_id"] for row in timeline] == ["evt-1", "evt-2"]
    assert [row["event_id"] for row in snippets] == ["evt-1", "evt-2"]
    assert [row["event_id"] for row in pack["timeline_snippets"]] == ["evt-1", "evt-2"]
    assert pack["timeline_snippets"][0]["summary"] == "memory_note_activated: operator accepted"


def test_export_memory_graph_emits_json_edges_without_external_graph_database():
    old = MemoryNote(
        id="old-note",
        body="Old behavior.",
        type="fact",
        agent="reyna",
        status="superseded",
        event_ids=["evt-1"],
    )
    new = MemoryNote(
        id="new-note",
        body="New behavior.",
        type="fact",
        agent="reyna",
        status="active",
        supersedes=["old-note"],
        event_ids=["evt-2"],
    )
    rule = MemoryNote(id="rule-1", body="Rule.", type="behavior_rule", agent="reyna", status="active")
    case = MemoryNote(
        id="case-1",
        body="Regression for rule-1.",
        type="regression_case",
        agent="reyna",
        status="active",
        source_ids=["rule-1"],
    )
    review = MemoryNote(
        id="review-1",
        body="Outcome review for rule-1.",
        type="outcome_review",
        agent="reyna",
        status="active",
        tags=["rule:rule-1"],
    )
    timeline = build_timeline([
        {"id": "evt-1", "timestamp": "2026-01-01T00:00:00Z", "type": "memory_note_activated", "note_ids": ["old-note"], "source_ids": ["turn-1"], "payload": {}},
        {"id": "evt-2", "timestamp": "2026-01-02T00:00:00Z", "type": "memory_note_superseded", "note_ids": ["new-note"], "source_ids": ["turn-2"], "payload": {}},
    ])

    graph = export_memory_graph([old, new, rule, case, review], timeline)
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    assert ("source:turn-1", "event:evt-1", "source_to_event") in edges
    assert ("event:evt-1", "note:old-note", "event_to_note") in edges
    assert ("note:new-note", "note:old-note", "note_supersedes") in edges
    assert ("note:rule-1", "note:case-1", "behavior_rule_to_regression_case") in edges
    assert ("note:rule-1", "note:review-1", "behavior_rule_to_outcome_review") in edges
    assert all("neo4j" not in str(value).lower() for value in graph.values())


def test_detect_conflicts_pass_finds_unresolved_opposite_polarity_notes(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    active = MemoryNote(
        body="Memory prefetch must be enabled.",
        type="constraint",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        source="test",
        source_quality="file",
    )
    candidate = MemoryNote(
        body="Memory prefetch must be disabled.",
        type="constraint",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="inbox",
        source="test",
        source_quality="file",
    )
    store.write_note(active)
    store.write_note(candidate)

    conflicts = store.detect_conflicts(limit=10)

    assert len(conflicts) == 1
    assert conflicts[0]["candidate_id"] == candidate.id
    assert conflicts[0]["conflict_ids"] == [active.id]
    assert conflicts[0]["status"] == "conflicting"


def test_apply_dream_proposal_is_dry_run_by_default_selected_only_and_writes_action_events(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    selected = MemoryNote(
        body="Selected sourced inbox fact.",
        type="fact",
        agent="reyna",
        status="inbox",
        source="test",
        source_quality="file",
    )
    other = MemoryNote(
        body="Other sourced inbox fact.",
        type="fact",
        agent="reyna",
        status="inbox",
        source="test",
        source_quality="file",
    )
    store.write_note(selected)
    store.write_note(other)
    dream = store.dream_cycle(limit=20)

    preview = store.apply_dream_proposal(proposal_path=dream["proposal_path"], note_ids=[selected.id], dry_run=True)
    after_preview = {note.id: note.status for note in store.list_notes()}
    assert len(preview["applied"]) == 1
    preview_item = preview["applied"][0]
    assert preview_item["note_id"] == selected.id
    assert preview_item["action"] == "candidate_for_manual_promotion"
    assert preview_item["before_status"] == "inbox"
    assert preview_item["after_status"] == "active"
    assert preview_item["before_path"] == selected.path
    assert preview_item["after_path"].endswith(f"fact-{selected.id}.md")
    assert preview_item["dry_run"] is True
    assert preview_item["event_ids"] == []
    assert after_preview[selected.id] == "inbox"
    assert after_preview[other.id] == "inbox"

    applied = store.apply_dream_proposal(proposal_path=dream["proposal_path"], note_ids=[selected.id], dry_run=False)
    notes = {note.id: note for note in store.list_notes()}
    assert notes[selected.id].status == "active"
    assert notes[other.id].status == "inbox"
    assert applied["applied"][0]["event_ids"]
    assert applied["event_ids"] == applied["applied"][0]["event_ids"]
    events = [event for event in store.iter_events() if event.get("type") == "dream_cycle_action_applied"]
    assert len(events) == 1
    assert events[0]["note_ids"] == [selected.id]


def test_apply_dream_proposal_refuses_to_archive_active_notes_without_retirement_flow(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    active = MemoryNote(
        body="Active duplicate should not be retired by proposal apply.",
        type="fact",
        agent="reyna",
        status="active",
        source="test",
        source_quality="file",
    )
    store.write_note(active)
    audit_path = store.dream_log_path
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        '{"run_id":"manual","proposal_path":"manual.md","items":[{"note_id":"' + active.id + '","action":"propose_archive_duplicate","duplicate_of":"other"}]}\n',
        encoding="utf-8",
    )

    result = store.apply_dream_proposal(run_id="manual", note_ids=[active.id], dry_run=False)
    notes = {note.id: note for note in store.list_notes()}

    assert result["applied"] == []
    assert result["skipped"][0]["reason"] == "refusing to archive active note from proposal apply"
    assert notes[active.id].status == "active"


def test_dream_cycle_v1_report_has_all_review_sections_and_does_not_mutate(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    notes = [
        MemoryNote(body="Inbox routing candidate.", type="fact", agent="reyna", status="inbox"),
        MemoryNote(body="Weak active note without source.", type="decision", agent="reyna", status="active", importance="high"),
        MemoryNote(body="Open loop: return to this later.", type="open_loop", agent="reyna", status="open_loop"),
        MemoryNote(body="Sensitive token [REDACTED] audit candidate.", type="fact", agent="reyna", status="inbox", sensitivity="secret_ref"),
    ]
    for note in notes:
        store.write_note(note)
    before = {note.id: (note.status, tuple(note.tags)) for note in store.list_notes()}

    result = store.dream_cycle(limit=20)
    report = Path(result["proposal_path"]).read_text(encoding="utf-8")
    after = {note.id: (note.status, tuple(note.tags)) for note in store.list_notes()}

    required_sections = [
        "## Inbox routing",
        "## Dedup candidates",
        "## Weak-source active notes",
        "## Conflicts",
        "## Supersedes candidates",
        "## Corrections missing behavior rules",
        "## Behavior rules missing regression cases",
        "## Regression cases without outcome reviews",
        "## Repeated behavior failures",
        "## Open loops needing confirmation",
        "## Sensitive/secret_ref audit summary",
    ]
    for section in required_sections:
        assert section in report
    assert before == after
    assert "Safe review/proposal pass" in report


def test_dream_cycle_report_lists_unresolved_conflicts(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    active = MemoryNote(
        body="Runtime memory must be enabled.",
        type="constraint",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        source="test",
        source_quality="file",
    )
    candidate = MemoryNote(
        body="Runtime memory must be disabled.",
        type="constraint",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="inbox",
        source="test",
        source_quality="file",
    )
    store.write_note(active)
    store.write_note(candidate)

    result = store.dream_cycle(limit=10)
    report = Path(result["proposal_path"]).read_text(encoding="utf-8")

    assert "## Conflicts" in report
    assert candidate.id in report
    assert active.id in report
    assert "No automatic deletion or overwrite" in report


def test_supersede_note_writes_event_updates_frontmatter_and_excludes_old_from_default_retrieval(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    old = MemoryNote(
        body="Use old context pack format.",
        type="fact",
        agent="reyna",
        status="active",
        source="test",
        source_quality="file",
    )
    new = MemoryNote(
        body="Use Context Pack v2 format.",
        type="fact",
        agent="reyna",
        status="active",
        source="test",
        source_quality="file",
    )
    store.write_note(old)
    store.write_note(new)

    result = store.supersede_note(
        old.id,
        new.id,
        reason="Context Pack v2 replaced the old format.",
        provenance="test:phase6",
        dry_run=False,
    )

    assert result["applied"][0]["old_status"] == "superseded"
    assert result["applied"][0]["new_status"] == "active"
    assert result["event_ids"]
    notes = {note.id: note for note in store.list_notes()}
    assert notes[old.id].status == "superseded"
    assert notes[old.id].superseded_by == [new.id]
    assert old.id in notes[new.id].supersedes
    assert result["event_ids"][0] in notes[old.id].event_ids
    assert result["event_ids"][0] in notes[new.id].event_ids
    rows = store.index.search("context pack", statuses=["active"], limit=10)
    assert any(row["id"] == new.id for row in rows)
    assert all(row["id"] != old.id for row in rows)


def test_build_evolution_chain_orders_superseded_to_current(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    old = MemoryNote(
        body="Old memory policy: keep everything in always-on MEMORY.",
        type="decision",
        agent="reyna",
        status="superseded",
        source="test",
        source_quality="session",
    )
    store.write_note(old)
    current = MemoryNote(
        body="Current memory policy: capture broadly but retrieve narrowly from readable_tree.",
        type="decision",
        agent="reyna",
        status="active",
        supersedes=[old.id],
        source="test",
        source_quality="session",
    )
    store.write_note(current)

    chain = build_evolution_chain(current.id, store.list_notes())

    assert [note.id for note in chain] == [old.id, current.id]


def test_context_conflicts_are_surfaced_as_warnings_not_equal_truth():
    rows = [
        {
            "id": "old",
            "type": "decision",
            "status": "active",
            "project": "memory",
            "scope": "architecture",
            "body": "Decision: store everything in always-on MEMORY.",
            "superseded_by": "",
            "supersedes": "",
            "source_ids": "turn-old",
            "event_ids": "",
            "sensitivity": "internal",
            "source_quality": "session",
        },
        {
            "id": "new",
            "type": "decision",
            "status": "active",
            "project": "memory",
            "scope": "architecture",
            "body": "Decision: do not store everything in always-on MEMORY; use readable_tree retrieval.",
            "superseded_by": "",
            "supersedes": "old",
            "source_ids": "turn-new",
            "event_ids": "evt-new",
            "sensitivity": "internal",
            "source_quality": "session",
        },
    ]

    conflicts = detect_context_conflicts(rows)
    pack = build_context_pack("memory policy", rows, max_chars=4000)

    assert conflicts == [{
        "type": "possible_conflict",
        "scope": "memory/architecture/decision",
        "note_ids": ["old", "new"],
        "resolution_hint": "prefer superseding/current notes; treat conflicting active notes as warnings until reviewed",
    }]
    assert '"conflicts"' in pack
    assert "possible_conflict" in pack
    assert "evolution_chains" in pack
    assert "old" in pack and "new" in pack

def test_lifecycle_rejects_high_impact_active_note_without_source():
    note = MemoryNote(
        body="High impact active memory needs provenance.",
        type="decision",
        agent="reyna",
        status="active",
        importance="high",
    )

    allowed, reason = can_activate(note)

    assert allowed is False
    assert "source" in reason or "provenance" in reason


def test_lifecycle_rejects_behavior_rule_without_correction_link():
    note = MemoryNote(
        body="Before coding, read the roadmap.",
        type="behavior_rule",
        agent="reyna",
        status="active",
        importance="high",
        source="manual",
        source_ids=["turn-1"],
        source_quality="manual",
    )

    allowed, reason = can_activate(note)

    assert allowed is False
    assert "correction" in reason


def test_lifecycle_allows_low_impact_sourced_fact():
    note = MemoryNote(
        body="Readable tree stores Markdown notes locally.",
        type="fact",
        agent="reyna",
        status="active",
        importance="low",
        source="test",
        source_ids=["turn-1"],
        source_quality="session",
    )

    allowed, reason = can_activate(note)

    assert allowed is True
    assert reason == "ok"


def test_store_activation_uses_lifecycle_gates(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    note = MemoryNote(
        body="Behavior rule cannot activate without correction linkage.",
        type="behavior_rule",
        agent="reyna",
        status="inbox",
        importance="high",
        source="manual",
        source_quality="manual",
        source_ids=["turn-1"],
    )
    store.write_note(note)

    result = store.activate_notes(
        note_ids=[note.id],
        reason="operator approval without correction should still fail",
        provenance="test:lifecycle",
        dry_run=False,
    )

    assert result["applied"] == []
    assert result["skipped"][0]["note_id"] == note.id
    assert "correction" in result["skipped"][0]["reason"]
    assert store.list_notes()[0].status == "inbox"
