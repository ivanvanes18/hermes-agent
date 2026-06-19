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
