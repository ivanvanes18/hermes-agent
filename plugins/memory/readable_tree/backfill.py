"""Safe dry-run backfill planning for readable_tree memory."""

from __future__ import annotations

from typing import Any


def _note_item(note: Any, *, reason: str, action: str) -> dict[str, Any]:
    return {
        "action_id": f"{action}:{getattr(note, 'id', '')}",
        "note_id": str(getattr(note, "id", "") or ""),
        "path": str(getattr(note, "path", "") or ""),
        "type": str(getattr(note, "type", "") or ""),
        "status": str(getattr(note, "status", "") or ""),
        "reason": reason,
        "proposed_action": action,
    }


def _note_ref_tokens(note_id: str) -> set[str]:
    """Return the common textual forms used to point at a note."""
    clean_id = str(note_id or "").strip()
    if not clean_id:
        return set()
    return {clean_id, f"note:{clean_id}"}


def _body_mentions_note(body: str, note_id: str) -> bool:
    tokens = _note_ref_tokens(note_id)
    return bool(tokens and any(token in body for token in tokens))


def _has_behavior_link(note: Any, notes_by_id: dict[str, Any]) -> bool:
    """Return whether a correction is already linked to a behavior chain.

    Behavioral links have existed in several historical shapes:
    - old tags such as ``rule:<id>`` / ``case:<id>`` on the correction;
    - behavior_rule/regression_case notes linking back through body/source_ids;
    - all three notes sharing the same ``behavioral_chain_created`` event_id;
    - operator quality-pass notes linking outward from the correction body or
      correction ``source_ids`` as ``note:<behavior_rule_id>`` and
      ``note:<regression_case_id>``.

    Treat the correction as covered when at least one behavioral artifact is
    linked. Some older chains stored only a behavior_rule link, and backfill
    should avoid duplicating those chains.
    """
    note_id = str(getattr(note, "id", "") or "")
    body = str(getattr(note, "body", "") or "")
    tags = {str(tag) for tag in (getattr(note, "tags", []) or []) if str(tag).strip()}
    note_source_ids = {str(value) for value in (getattr(note, "source_ids", []) or []) if str(value).strip()}
    note_event_ids = {str(value) for value in (getattr(note, "event_ids", []) or []) if str(value).strip()}
    link_tokens = _note_ref_tokens(note_id) | note_source_ids
    link_tokens.discard("")

    linked_types: set[str] = set()

    for tag in tags:
        if tag.startswith("rule:"):
            linked_types.add("behavior_rule")
        if tag.startswith("case:"):
            linked_types.add("regression_case")

    for candidate in notes_by_id.values():
        candidate_type = str(getattr(candidate, "type", "") or "")
        if candidate_type not in {"behavior_rule", "regression_case"}:
            continue
        candidate_id = str(getattr(candidate, "id", "") or "")
        candidate_body = str(getattr(candidate, "body", "") or "")
        candidate_source_ids = {
            str(value) for value in (getattr(candidate, "source_ids", []) or []) if str(value).strip()
        }
        candidate_event_ids = {
            str(value) for value in (getattr(candidate, "event_ids", []) or []) if str(value).strip()
        }

        candidate_links_back = bool(
            (link_tokens and (any(token in candidate_body for token in link_tokens) or (link_tokens & candidate_source_ids)))
            or (note_event_ids and (note_event_ids & candidate_event_ids))
        )
        correction_links_out = bool(
            candidate_id and (_body_mentions_note(body, candidate_id) or (_note_ref_tokens(candidate_id) & note_source_ids))
        )

        if candidate_links_back or correction_links_out:
            linked_types.add(candidate_type)

    return bool(linked_types)


def plan_backfill(store: Any, limit: int = 50, include_archived: bool = False, dry_run: bool = True) -> dict[str, Any]:
    """Plan safe migration/backfill work without mutating notes.

    Detects:
    - legacy correction notes lacking linked behavior_rule/regression_case;
    - active notes with weak/missing provenance;
    - notes missing event_ids.
    """
    notes = list(store.list_notes())
    notes_by_id = {str(getattr(note, "id", "") or ""): note for note in notes}
    considered = [note for note in notes if include_archived or getattr(note, "status", "") != "archived"]
    max_items = max(1, int(limit or 50))

    legacy_corrections: list[dict[str, Any]] = []
    weak_provenance: list[dict[str, Any]] = []
    missing_event_ids: list[dict[str, Any]] = []

    for note in considered:
        note_type = str(getattr(note, "type", "") or "")
        tags = [str(tag) for tag in (getattr(note, "tags", []) or [])]
        body = str(getattr(note, "body", "") or "")
        is_correction = note_type == "correction" or "correction" in tags or "corrected" in body.casefold()
        if is_correction and not _has_behavior_link(note, notes_by_id):
            legacy_corrections.append(
                _note_item(note, reason="legacy correction lacks behavior_rule/regression_case link", action="derive_behavior_chain")
            )

        if str(getattr(note, "status", "") or "") == "active" or include_archived:
            source = str(getattr(note, "source", "") or "")
            source_quality = str(getattr(note, "source_quality", "") or "")
            source_ids = [str(value) for value in (getattr(note, "source_ids", []) or [])]
            if not source or not source_quality or source_quality in {"", "unknown", "weak"}:
                weak_provenance.append(
                    _note_item(note, reason="active note has weak or missing provenance", action="review_provenance")
                )

        if not list(getattr(note, "event_ids", []) or []):
            missing_event_ids.append(
                _note_item(note, reason="note has no event_ids provenance links", action="link_existing_events_or_mark_legacy")
            )

    for note in notes:
        if note in considered:
            continue
        if not list(getattr(note, "event_ids", []) or []):
            missing_event_ids.append(
                _note_item(note, reason="note has no event_ids provenance links", action="link_existing_events_or_mark_legacy")
            )

    legacy_corrections = legacy_corrections[:max_items]
    weak_provenance = weak_provenance[:max_items]
    missing_event_ids = missing_event_ids[:max_items]
    proposed_actions = (legacy_corrections + weak_provenance + missing_event_ids)[:max_items]

    return {
        "dry_run": dry_run,
        "changed_files": [],
        "include_archived": include_archived,
        "scanned": len(considered),
        "legacy_corrections": legacy_corrections,
        "weak_provenance": weak_provenance,
        "missing_event_ids": missing_event_ids,
        "proposed_actions": proposed_actions,
        "count": len(proposed_actions),
    }


def apply_backfill_actions(store: Any, action_ids: list[str], dry_run: bool = True) -> dict[str, Any]:
    """Apply explicitly selected safe backfill markers.

    The backfill applier is deliberately conservative: it does not infer new
    facts, delete notes, or rewrite note bodies. Mutating mode only adds a
    review tag plus an audit event link to selected notes.
    """
    requested = [str(action_id) for action_id in (action_ids or []) if str(action_id).strip()]
    plan = plan_backfill(store, limit=max(50, len(requested) * 2 or 50), include_archived=True, dry_run=True)
    actions_by_id = {str(action.get("action_id") or ""): action for action in plan.get("proposed_actions", [])}
    notes_by_id = {str(getattr(note, "id", "") or ""): note for note in store.list_notes()}

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    changed_files: list[str] = []
    event_ids: list[str] = []

    for action_id in requested:
        action = actions_by_id.get(action_id)
        if not action:
            skipped.append({"action_id": action_id, "reason": "action_not_found"})
            continue

        note_id = str(action.get("note_id") or "")
        note = notes_by_id.get(note_id)
        if not note:
            skipped.append({"action_id": action_id, "reason": "note_not_found"})
            continue

        proposed_action = str(action.get("proposed_action") or "review")
        tag = f"backfill:{proposed_action}"
        before_path = str(getattr(note, "path", "") or "")
        action_event_id = ""

        if not dry_run:
            if tag not in note.tags:
                note.tags.append(tag)
            event = store.append_event(
                "backfill_action_applied",
                note_ids=[note_id],
                source_ids=list(getattr(note, "source_ids", []) or []),
                payload={
                    "action_id": action_id,
                    "proposed_action": proposed_action,
                    "reason": action.get("reason"),
                },
            )
            action_event_id = str(event["id"])
            event_ids.append(action_event_id)
            if action_event_id not in note.event_ids:
                note.event_ids.append(action_event_id)
            new_path = store._rewrite_note(note)
            changed_files.append(str(new_path))
            if before_path and before_path != str(new_path):
                changed_files.append(before_path)

        applied.append(
            {
                "action_id": action_id,
                "note_id": note_id,
                "action": proposed_action,
                "dry_run": dry_run,
                "event_ids": [action_event_id] if action_event_id else [],
            }
        )

    if not dry_run and applied:
        store.rebuild_index()

    return {
        "dry_run": dry_run,
        "applied": applied,
        "skipped": skipped,
        "event_ids": event_ids,
        "changed_files": sorted(set(changed_files)),
        "count": len(applied),
    }
