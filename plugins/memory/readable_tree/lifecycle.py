"""Lifecycle helpers for readable_tree memory notes.

These checks are intentionally deterministic. Promotion to active retrieval is a
side-effectful lifecycle transition, so high-impact notes need provenance and
behavioral rules need correction lineage. Retrieval helpers are also conservative:
conflicting active notes are surfaced as warnings instead of silently treated as
equal truth.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable

from .schemas import MemoryNote, SOURCE_BACKED_QUALITIES

BEHAVIORAL_LINEAGE_TYPES = {"behavior_rule", "regression_case"}
_CONFLICT_TYPES = {"decision", "requirement", "constraint", "behavior_rule"}


def _has_source(note: MemoryNote) -> bool:
    return bool(note.source or note.source_ids or note.source_quality in SOURCE_BACKED_QUALITIES)


def _has_correction_lineage(note: MemoryNote) -> bool:
    if note.type == "correction":
        return True
    markers = {str(value).casefold() for value in [note.source, note.source_quality, *note.source_ids, *note.event_ids, *note.tags]}
    return any("correction" in marker or "behavioral_chain" in marker for marker in markers)


def _csv_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _row_scope(row: dict[str, Any]) -> str:
    parts = [str(row.get("project") or ""), str(row.get("scope") or ""), str(row.get("type") or "")]
    return "/".join(part for part in parts if part)


def can_activate(note: MemoryNote) -> tuple[bool, str]:
    """Return whether a note may enter active retrieval and why.

    Rules are conservative by design:
    - high-impact notes require source/provenance;
    - behavioral derived notes require correction lineage;
    - secret references never enter active retrieval.
    """
    if note.sensitivity == "secret_ref":
        return False, "secret_ref notes cannot be activated"
    if note.high_impact and not _has_source(note):
        return False, "high-impact notes require source/provenance before activation"
    if note.type in BEHAVIORAL_LINEAGE_TYPES and not _has_correction_lineage(note):
        return False, "behavioral notes require correction lineage before activation"
    return True, "ok"


def build_evolution_chain(note_id: str, notes: Iterable[MemoryNote]) -> list[MemoryNote]:
    """Return supersession lineage ending at ``note_id`` where possible."""
    by_id = {note.id: note for note in notes}
    if note_id not in by_id:
        return []

    parents: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    for note in by_id.values():
        for parent_id in note.supersedes:
            if parent_id in by_id:
                parents[note.id].add(parent_id)
                children[parent_id].add(note.id)
        for child_id in note.superseded_by:
            if child_id in by_id:
                parents[child_id].add(note.id)
                children[note.id].add(child_id)

    related: set[str] = set()
    queue: deque[str] = deque([note_id])
    while queue:
        current = queue.popleft()
        if current in related:
            continue
        related.add(current)
        queue.extend(sorted(parents.get(current, set())))
        queue.extend(sorted(children.get(current, set())))

    def depth(item_id: str, seen: set[str] | None = None) -> int:
        seen = seen or set()
        if item_id in seen:
            return 0
        parent_ids = parents.get(item_id, set())
        if not parent_ids:
            return 0
        return 1 + max(depth(parent_id, seen | {item_id}) for parent_id in parent_ids)

    return [by_id[item_id] for item_id in sorted(related, key=lambda item_id: (depth(item_id), by_id[item_id].observed_at, item_id))]


def detect_context_conflicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect active same-scope notes that need warning treatment in retrieval."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("status") or "") != "active":
            continue
        if str(row.get("type") or "") not in _CONFLICT_TYPES:
            continue
        scope = _row_scope(row)
        if scope:
            groups[scope].append(row)

    conflicts: list[dict[str, Any]] = []
    for scope, scoped_rows in sorted(groups.items()):
        if len(scoped_rows) < 2:
            continue
        note_ids = [str(row.get("id") or "") for row in scoped_rows if row.get("id")]
        if len(note_ids) < 2:
            continue
        conflicts.append({
            "type": "possible_conflict",
            "scope": scope,
            "note_ids": note_ids,
            "resolution_hint": "prefer superseding/current notes; treat conflicting active notes as warnings until reviewed",
        })
    return conflicts
