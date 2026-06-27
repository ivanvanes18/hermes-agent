from agent.memory_manager import MemoryManager
from plugins.memory.readable_tree import ReadableTreeMemoryProvider
from plugins.memory.readable_tree.backfill import apply_backfill_actions, plan_backfill
from plugins.memory.readable_tree.schemas import MemoryNote
from plugins.memory.readable_tree.store import ReadableMemoryStore


def test_apply_backfill_actions_is_selected_only_audited_and_non_destructive(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    first = MemoryNote(
        body="Ivan corrected: run tests before done.",
        type="correction",
        agent="reyna",
        status="active",
        tags=["correction"],
        source="session",
        source_quality="manual",
    )
    second = MemoryNote(
        body="Ivan corrected: load skill first.",
        type="correction",
        agent="reyna",
        status="active",
        tags=["correction"],
        source="session",
        source_quality="manual",
    )
    store.write_note(first)
    store.write_note(second)
    plan = plan_backfill(store, limit=20)
    selected_action = next(action for action in plan["proposed_actions"] if action["note_id"] == first.id)
    before = {note.id: (note.status, note.body, tuple(note.tags), tuple(note.event_ids)) for note in store.list_notes()}

    preview = apply_backfill_actions(store, [selected_action["action_id"]], dry_run=True)
    after_preview = {note.id: (note.status, note.body, tuple(note.tags), tuple(note.event_ids)) for note in store.list_notes()}
    applied = apply_backfill_actions(store, [selected_action["action_id"]], dry_run=False)
    notes = {note.id: note for note in store.list_notes()}
    events = [event for event in store.iter_events() if event.get("payload", {}).get("original_type") == "backfill_action_applied"]

    assert preview["dry_run"] is True
    assert preview["changed_files"] == []
    assert before == after_preview
    assert [item["note_id"] for item in applied["applied"]] == [first.id]
    assert "backfill:derive_behavior_chain" in notes[first.id].tags
    assert "backfill:derive_behavior_chain" not in notes[second.id].tags
    assert notes[first.id].body == first.body
    assert notes[first.id].event_ids
    assert events and events[-1]["note_ids"] == [first.id]
    assert applied["changed_files"]


def test_apply_backfill_actions_unknown_action_is_skipped(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")

    result = apply_backfill_actions(store, ["missing:note"], dry_run=False)

    assert result["applied"] == []
    assert result["skipped"][0]["action_id"] == "missing:note"


def test_plan_backfill_detects_legacy_corrections_weak_provenance_and_missing_event_ids_without_mutation(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    legacy_correction = MemoryNote(
        body="Ivan corrected: do not claim done without tests.",
        type="correction",
        agent="reyna",
        status="active",
        tags=["correction"],
        source="session",
        source_quality="manual",
    )
    weak_provenance = MemoryNote(
        body="Active fact with weak source quality.",
        type="fact",
        agent="reyna",
        status="active",
        source="legacy-import",
        source_quality="weak",
        event_ids=["evt-existing"],
    )
    missing_events = MemoryNote(
        body="Active fact with source but no event links.",
        type="fact",
        agent="reyna",
        status="active",
        source="session",
        source_quality="manual",
        event_ids=[],
    )
    archived = MemoryNote(
        body="Archived weak note should be ignored by default.",
        type="fact",
        agent="reyna",
        status="archived",
        source="legacy-import",
        source_quality="weak",
    )
    for note in [legacy_correction, weak_provenance, missing_events, archived]:
        store.write_note(note)
    before = {note.id: (note.status, tuple(note.tags), tuple(note.event_ids)) for note in store.list_notes()}

    report = plan_backfill(store, limit=20)
    after = {note.id: (note.status, tuple(note.tags), tuple(note.event_ids)) for note in store.list_notes()}

    assert report["dry_run"] is True
    assert report["changed_files"] == []
    assert before == after
    assert [item["note_id"] for item in report["legacy_corrections"]] == [legacy_correction.id]
    assert [item["note_id"] for item in report["weak_provenance"]] == [weak_provenance.id]
    assert set(item["note_id"] for item in report["missing_event_ids"]) == {legacy_correction.id, missing_events.id, archived.id}
    assert report["high_risk_missing_event_ids"] == []

    active_only_ids = {action["note_id"] for action in report["proposed_actions"]}
    assert legacy_correction.id in active_only_ids
    assert weak_provenance.id in active_only_ids
    assert missing_events.id in active_only_ids


def test_plan_backfill_include_archived_adds_archived_weak_provenance(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    archived = MemoryNote(
        body="Archived weak note.",
        type="fact",
        agent="reyna",
        status="archived",
        source="legacy-import",
        source_quality="weak",
    )
    store.write_note(archived)

    default_report = plan_backfill(store, limit=20)
    include_report = plan_backfill(store, limit=20, include_archived=True)

    assert default_report["weak_provenance"] == []
    assert [item["note_id"] for item in include_report["weak_provenance"]] == [archived.id]


def test_plan_backfill_prioritizes_high_risk_active_notes_missing_event_ids(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    rule = MemoryNote(
        body="Before claiming done, run verification.",
        type="behavior_rule",
        agent="reyna",
        status="active",
        tags=["behavioral-memory", "mistake:false_completion"],
        source="correction",
        source_ids=["turn-correction"],
        source_quality="manual",
        event_ids=[],
    )
    decision = MemoryNote(
        body="Memory architecture must use bounded Context Packs.",
        type="decision",
        agent="reyna",
        status="active",
        importance="high",
        source="session",
        source_ids=["turn-decision"],
        source_quality="manual",
        event_ids=[],
    )
    low = MemoryNote(
        body="Low-impact fact without event ids.",
        type="fact",
        agent="reyna",
        status="active",
        importance="low",
        source="session",
        source_quality="manual",
        event_ids=[],
    )
    for note in [low, decision, rule]:
        store.write_note(note)

    report = plan_backfill(store, limit=20)

    high_risk_ids = [item["note_id"] for item in report["high_risk_missing_event_ids"]]
    proposed = report["proposed_actions"]
    assert set(high_risk_ids) == {decision.id, rule.id}
    assert {item["note_id"] for item in proposed[:2]} == set(high_risk_ids)
    assert all(item["proposed_action"] == "mark_high_risk_legacy_or_link_existing_events" for item in proposed[:2])


def test_backfill_tool_path_exposes_plan_and_selected_apply(tmp_path):
    provider = ReadableTreeMemoryProvider({"agent": "reyna"})
    provider.initialize("backfill-tool", hermes_home=str(tmp_path), agent_identity="reyna")
    assert provider._store is not None
    rule = MemoryNote(
        body="Before claiming done, run verification.",
        type="behavior_rule",
        agent="reyna",
        status="active",
        tags=["behavioral-memory", "mistake:false_completion"],
        source="correction",
        source_ids=["turn-correction"],
        source_quality="manual",
        event_ids=[],
    )
    provider._store.write_note(rule)
    mgr = MemoryManager()
    mgr.add_provider(provider)

    plan = __import__("json").loads(mgr.handle_tool_call("readable_memory_plan_backfill", {"limit": 20}))
    action_id = plan["high_risk_missing_event_ids"][0]["action_id"]
    preview = __import__("json").loads(mgr.handle_tool_call("readable_memory_apply_backfill", {
        "action_ids": [action_id],
        "dry_run": True,
    }))
    applied = __import__("json").loads(mgr.handle_tool_call("readable_memory_apply_backfill", {
        "action_ids": [action_id],
        "dry_run": False,
    }))
    notes = {note.id: note for note in provider._store.list_notes()}

    assert mgr.has_tool("readable_memory_apply_backfill")
    assert preview["dry_run"] is True
    assert preview["changed_files"] == []
    assert applied["applied"][0]["note_id"] == rule.id
    assert "backfill:mark_high_risk_legacy_or_link_existing_events" in notes[rule.id].tags
    assert notes[rule.id].event_ids