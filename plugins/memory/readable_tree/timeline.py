"""Timeline helpers for readable_tree event provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def build_timeline(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a deterministic note/event timeline from raw event records."""
    rows: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        note_ids = [str(value) for value in (event.get("note_ids") or []) if str(value).strip()]
        rows.append(
            {
                "event_id": event_id,
                "timestamp": str(event.get("timestamp") or ""),
                "type": str(event.get("type") or ""),
                "note_ids": note_ids,
                "source_ids": [str(value) for value in (event.get("source_ids") or []) if str(value).strip()],
                "summary": _event_summary(event),
            }
        )
    return sorted(rows, key=lambda row: (row.get("timestamp") or "", row.get("event_id") or ""))


def load_timeline(events_path: str | Path) -> list[dict[str, Any]]:
    """Load events.jsonl and build a timeline."""
    path = Path(events_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(data)
    return build_timeline(events)


def summarize_timeline_for_notes(timeline: Iterable[dict[str, Any]], note_ids: Iterable[str], *, limit: int = 5) -> list[dict[str, Any]]:
    """Return bounded timeline snippets for selected note IDs."""
    wanted = {str(note_id) for note_id in note_ids if str(note_id).strip()}
    snippets: list[dict[str, Any]] = []
    for row in timeline:
        row_note_ids = [str(value) for value in (row.get("note_ids") or [])]
        matched = [note_id for note_id in row_note_ids if note_id in wanted]
        if not matched:
            continue
        snippets.append(
            {
                "event_id": row.get("event_id"),
                "timestamp": row.get("timestamp"),
                "type": row.get("type"),
                "note_ids": matched,
                "summary": row.get("summary"),
            }
        )
    return snippets[-max(1, int(limit or 5)):]


def export_memory_graph(notes: Iterable[Any], timeline: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Export note/event/source relationships as plain JSON edges.

    This is an interchange artifact, not a graph database dependency.
    """
    edges: list[dict[str, str]] = []
    nodes: dict[str, dict[str, str]] = {}

    for row in timeline:
        event_id = str(row.get("event_id") or "")
        if not event_id:
            continue
        nodes[f"event:{event_id}"] = {"kind": "event", "id": event_id, "type": str(row.get("type") or "")}
        for source_id in row.get("source_ids") or []:
            source_id = str(source_id)
            nodes[f"source:{source_id}"] = {"kind": "source", "id": source_id}
            edges.append({"from": f"source:{source_id}", "to": f"event:{event_id}", "type": "source_to_event"})
        for note_id in row.get("note_ids") or []:
            note_id = str(note_id)
            nodes.setdefault(f"note:{note_id}", {"kind": "note", "id": note_id})
            edges.append({"from": f"event:{event_id}", "to": f"note:{note_id}", "type": "event_to_note"})

    notes_by_id = {str(getattr(note, "id", "") or ""): note for note in notes}
    behavior_rules = [note for note in notes_by_id.values() if getattr(note, "type", "") == "behavior_rule"]
    regression_cases = [note for note in notes_by_id.values() if getattr(note, "type", "") == "regression_case"]
    outcome_reviews = [note for note in notes_by_id.values() if getattr(note, "type", "") == "outcome_review"]

    for note_id, note in notes_by_id.items():
        if not note_id:
            continue
        nodes.setdefault(f"note:{note_id}", {"kind": "note", "id": note_id, "type": str(getattr(note, "type", "") or "")})
        for event_id in getattr(note, "event_ids", []) or []:
            event_id = str(event_id)
            nodes.setdefault(f"event:{event_id}", {"kind": "event", "id": event_id})
            edges.append({"from": f"event:{event_id}", "to": f"note:{note_id}", "type": "event_to_note"})
        for superseded_id in getattr(note, "supersedes", []) or []:
            superseded_id = str(superseded_id)
            nodes.setdefault(f"note:{superseded_id}", {"kind": "note", "id": superseded_id})
            edges.append({"from": f"note:{note_id}", "to": f"note:{superseded_id}", "type": "note_supersedes"})

    for rule in behavior_rules:
        rule_id = str(getattr(rule, "id", "") or "")
        if not rule_id:
            continue
        for case in regression_cases:
            if _note_links_to(case, rule_id):
                edges.append({"from": f"note:{rule_id}", "to": f"note:{case.id}", "type": "behavior_rule_to_regression_case"})
        for review in outcome_reviews:
            if _note_links_to(review, rule_id):
                edges.append({"from": f"note:{rule_id}", "to": f"note:{review.id}", "type": "behavior_rule_to_outcome_review"})

    deduped_edges = [dict(edge) for edge in {tuple(sorted(edge.items())) for edge in edges}]
    deduped_edges.sort(key=lambda edge: (edge["type"], edge["from"], edge["to"]))
    return {"nodes": [nodes[key] for key in sorted(nodes)], "edges": deduped_edges}


def _note_links_to(note: Any, target_id: str) -> bool:
    body = str(getattr(note, "body", "") or "")
    source_ids = [str(value) for value in (getattr(note, "source_ids", []) or [])]
    tags = [str(value) for value in (getattr(note, "tags", []) or [])]
    return target_id in body or target_id in source_ids or f"rule:{target_id}" in tags


def _event_summary(event: dict[str, Any]) -> str:
    raw_payload = event.get("payload")
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    action = str(payload.get("action") or payload.get("proposed_action") or payload.get("reason") or "").strip()
    event_type = str(event.get("type") or "event")
    if action:
        return f"{event_type}: {action}"[:200]
    original_type = str(payload.get("original_type") or "").strip()
    if original_type:
        return f"{event_type}: {original_type}"[:200]
    return event_type[:200]
