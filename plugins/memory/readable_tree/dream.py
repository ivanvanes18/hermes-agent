"""Safe Dream Cycle review/proposal pass for readable_tree memory.

Dream Cycle v0 is deliberately conservative: it scans reviewable notes,
classifies/routes them, detects obvious duplicates, writes a Markdown proposal
and audit log, but does not silently promote memories or edit constitution files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Any, Iterable

from .extractor import classify_sensitivity
from .schemas import MemoryNote, utc_now_iso

_SENSITIVE_REDACTED = "[SENSITIVE_REDACTED]"
_OPEN_LOOP_RE = re.compile(r"\b(todo|finish later|вернуться|return to|next step|потом|later)\b", re.IGNORECASE)
_HYPOTHESIS_RE = re.compile(r"\b(гипотез|hypothes|might|maybe|possibly|вероятно|похоже|предполож)\b", re.IGNORECASE)
_PROJECT_RE = re.compile(r"\b(project|проект|research|исследован|timeline|meeting|встреч|gbrain|knowledge brain)\b", re.IGNORECASE)
_SKILL_RE = re.compile(r"\b(procedure|workflow|скилл|skill|reuse|повторяем|runbook|playbook)\b", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S.{0,100}$")
_CODE_FRAGMENT_RE = re.compile(r"^`[^`]{1,80}`[;:.,]?$|^[-*]\s*`?\w[\w_-]{1,40}`?[;:.,]?$", re.IGNORECASE)
_GENERIC_FRAGMENT_RE = re.compile(
    r"^(так нельзя\.?|и обязательно:?|вот это реально важно\.?|главное ограничение|важно:?|вердикт:\s*\*{0,2}pass\*{0,2}\.?|оценка:\s*обязательно\.?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DreamProposalItem:
    note_id: str
    note_path: str
    note_type: str
    status: str
    sensitivity: str
    classification: str
    route: str
    action: str
    reason: str
    duplicate_of: str = ""
    excerpt: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "note_id": self.note_id,
            "note_path": self.note_path,
            "note_type": self.note_type,
            "status": self.status,
            "sensitivity": self.sensitivity,
            "classification": self.classification,
            "route": self.route,
            "action": self.action,
            "reason": self.reason,
            "duplicate_of": self.duplicate_of,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class DreamRunResult:
    run_id: str
    proposal_path: str
    audit_path: str
    scanned: int
    proposed: int
    counts: dict[str, int]
    changed_files: list[str]
    items: list[DreamProposalItem]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "proposal_path": self.proposal_path,
            "audit_path": self.audit_path,
            "scanned": self.scanned,
            "proposed": self.proposed,
            "counts": self.counts,
            "changed_files": self.changed_files,
            "items": [item.as_dict() for item in self.items],
        }


def _normalized_body(body: str) -> str:
    return _WHITESPACE_RE.sub(" ", body.casefold()).strip()


def _compact_body(body: str) -> str:
    return _WHITESPACE_RE.sub(" ", body).strip()


def _is_noise_fragment(body: str) -> bool:
    text = _compact_body(body).strip(" -\t")
    if not text:
        return True
    plain = text.strip("*_")
    if len(plain) < 6:
        return True
    if _MARKDOWN_HEADING_RE.match(text):
        return True
    if _CODE_FRAGMENT_RE.match(text):
        return True
    if _GENERIC_FRAGMENT_RE.match(plain):
        return True
    # Very short snippets with no sentence-like context are usually extraction
    # artifacts from assistant summaries rather than durable memory.
    if len(plain) <= 24 and not re.search(r"[.!?。！？]$", plain):
        return True
    return False


def _excerpt(note: MemoryNote, *, include_sensitive: bool = False, max_chars: int = 180) -> str:
    sensitivity = classify_sensitivity(note.body)
    if note.sensitivity in {"sensitive", "secret_ref"} or sensitivity in {"sensitive", "secret_ref"}:
        return _SENSITIVE_REDACTED if not include_sensitive else note.body[:max_chars]
    text = _WHITESPACE_RE.sub(" ", note.body).strip()
    return text[:max_chars]


def _tag_value(tags: str | list[str], prefix: str) -> str:
    values = tags if isinstance(tags, list) else str(tags or "").split()
    for raw in values:
        text = str(raw)
        if text.startswith(prefix):
            return text[len(prefix):]
    return ""


def _behavioral_rows(notes: Iterable[MemoryNote]) -> list[dict[str, Any]]:
    return [
        {
            "id": note.id,
            "type": note.type,
            "status": note.status,
            "tags": note.tags,
            "body": note.body,
        }
        for note in notes
        if note.type in {"correction", "behavior_rule", "regression_case", "outcome_review"}
    ]


def _general_review_sections(notes: Iterable[MemoryNote], items: list[DreamProposalItem], *, include_sensitive: bool = False) -> list[str]:
    note_list = list(notes)
    lines: list[str] = []

    def add_section(title: str, rows: list[str]) -> None:
        lines.extend([f"## {title}", ""])
        lines.extend(rows or ["- none"])
        lines.append("")

    inbox_items = [item for item in items if item.status in {"inbox", "needs_confirmation", "uncertain"}]
    add_section("Inbox routing", [f"- `{item.note_id}` → {item.route} / {item.action}" for item in inbox_items])

    duplicate_items = [item for item in items if item.action == "propose_archive_duplicate"]
    add_section("Dedup candidates", [f"- `{item.note_id}` duplicates `{item.duplicate_of}`" for item in duplicate_items])

    weak_active = [note for note in note_list if note.status == "active" and note.high_impact and not note.has_source]
    add_section("Weak-source active notes", [f"- `{note.id}` — {note.type}: {_excerpt(note, include_sensitive=include_sensitive)}" for note in weak_active])

    supersedes = [note for note in note_list if note.supersedes or note.superseded_by or note.status == "superseded"]
    add_section("Supersedes candidates", [f"- `{note.id}` status={note.status} supersedes={note.supersedes} superseded_by={note.superseded_by}" for note in supersedes])

    open_loops = [note for note in note_list if note.status == "open_loop" or note.type in {"open_loop", "intention", "task"}]
    add_section("Open loops needing confirmation", [f"- `{note.id}` — {_excerpt(note, include_sensitive=include_sensitive)}" for note in open_loops])

    sensitive = [note for note in note_list if note.sensitivity in {"sensitive", "secret_ref"} or classify_sensitivity(note.body) in {"sensitive", "secret_ref"}]
    add_section("Sensitive/secret_ref audit summary", [f"- `{note.id}` sensitivity={note.sensitivity} status={note.status}" for note in sensitive])
    return lines


def _conflict_sections(notes: Iterable[MemoryNote]) -> list[str]:
    lines = ["## Conflicts", "", "No automatic deletion or overwrite. Resolve conflicts explicitly with readable_memory_resolve_conflict or supersession workflow."]
    unresolved = [note for note in notes if note.status == "conflicting"]
    if not unresolved:
        lines.extend(["", "- none"])
        return lines
    for note in unresolved:
        conflict_ids = [str(tag).removeprefix("conflicts-with-") for tag in note.tags if str(tag).startswith("conflicts-with-")]
        lines.extend([
            "",
            f"- candidate: `{note.id}`",
            f"  - path: `{note.path}`",
            f"  - conflicts_with: {', '.join(f'`{value}`' for value in conflict_ids) if conflict_ids else '`unknown`'}",
            f"  - excerpt: {_excerpt(note)}",
        ])
    return lines


def _behavioral_gap_sections(rows: list[dict[str, Any]]) -> list[str]:
    corrections = [row for row in rows if row.get("type") == "correction"]
    rules = [row for row in rows if row.get("type") == "behavior_rule"]
    cases = [row for row in rows if row.get("type") == "regression_case"]
    reviews = [row for row in rows if row.get("type") == "outcome_review"]

    rule_classes = {_tag_value(row.get("tags", ""), "mistake:") for row in rules}
    case_classes = {_tag_value(row.get("tags", ""), "mistake:") for row in cases}

    lines = []
    missing_rules = [row for row in corrections if _tag_value(row.get("tags", ""), "mistake:") not in rule_classes]
    lines.extend(["## Corrections missing behavior rules", ""])
    if missing_rules:
        for row in missing_rules:
            lines.append(f"- `{row.get('id')}` — {str(row.get('body') or '')[:180]}")
    else:
        lines.append("- none")
    lines.extend(["", "## Behavior rules missing regression cases", ""])
    missing_cases = [row for row in rules if _tag_value(row.get("tags", ""), "mistake:") not in case_classes]
    if missing_cases:
        for row in missing_cases:
            lines.append(f"- `{row.get('id')}` — {str(row.get('body') or '')[:180]}")
    else:
        lines.append("- none")
    lines.extend(["", "## Regression cases without outcome reviews", ""])
    reviewed_classes = {_tag_value(row.get("tags", ""), "mistake:") for row in reviews}
    unreviewed_cases = [row for row in cases if _tag_value(row.get("tags", ""), "mistake:") not in reviewed_classes]
    if unreviewed_cases:
        for row in unreviewed_cases:
            lines.append(f"- `{row.get('id')}` — {str(row.get('body') or '')[:180]}")
    else:
        lines.append("- none")
    lines.extend(["", "## Repeated behavior failures", ""])
    repeated = [row for row in reviews if "outcome:repeated" in " ".join(str(tag) for tag in (row.get("tags") or []))]
    if repeated:
        for row in repeated:
            lines.append(f"- `{row.get('id')}` — {str(row.get('body') or '')[:180]}")
    else:
        lines.append("- none")
    return lines


def classify_note_for_dream(note: MemoryNote) -> tuple[str, str, str, str]:
    """Return (classification, route, action, reason) for a note.

    The classification is intentionally low-authority and deterministic. It is
    proposal metadata, not a new source of truth.
    """

    sensitivity = note.sensitivity
    body_sensitivity = classify_sensitivity(note.body)
    if body_sensitivity in {"sensitive", "secret_ref"}:
        sensitivity = body_sensitivity
    body = note.body

    if sensitivity in {"sensitive", "secret_ref"}:
        return (
            "sensitive_candidate",
            "needs_review",
            "keep_review_only",
            "sensitivity preflight blocks default retrieval/promotion",
        )
    if note.status == "conflicting":
        return (
            "conflict",
            "readable_tree",
            "propose_resolve_conflict",
            "candidate contradicts an active same-scope memory and needs explicit resolution",
        )
    if _is_noise_fragment(body):
        return (
            "noise_or_fragment",
            "archive_or_review",
            "propose_archive_noise",
            "looks like a heading/code/generic extraction fragment, not durable memory",
        )
    if _HYPOTHESIS_RE.search(body):
        return (
            "hypothesis",
            "readable_tree",
            "keep_low_authority_review",
            "hypothesis/mental-model notes must not be promoted as facts",
        )
    if note.type == "task" or _OPEN_LOOP_RE.search(body):
        return (
            "open_loop",
            "task_or_project_tracker",
            "keep_review_only",
            "open-loop notes are reminders/candidates, not permission for side effects",
        )
    if note.type == "procedure" or _SKILL_RE.search(body):
        return (
            "procedure",
            "skill_candidate",
            "propose_skill_or_procedure_note",
            "reusable workflow belongs in skill/procedure review",
        )
    if note.type in {"decision", "constraint", "correction", "requirement", "risk", "fact", "measurement", "observation", "current_state"}:
        if note.high_impact and not note.has_source:
            return (
                note.type,
                "readable_tree",
                "needs_source_before_promotion",
                "high-impact memory requires source/provenance",
            )
        if note.status == "inbox" and note.has_source and note.importance not in {"high", "critical"}:
            return (
                note.type,
                "readable_tree",
                "candidate_for_manual_promotion",
                "sourced low-risk atomic note can be reviewed for promotion",
            )
        return (
            note.type,
            "readable_tree",
            "review",
            "operational memory candidate stays in review until explicitly promoted",
        )
    if _PROJECT_RE.search(body):
        return (
            "project_knowledge",
            "knowledge_brain",
            "route_to_brain_review",
            "large project/research knowledge belongs outside operational memory",
        )
    return (
        "noise_or_general",
        "archive_or_review",
        "review",
        "no safe automatic promotion rule matched",
    )


def build_dream_proposal(
    *,
    notes: Iterable[MemoryNote],
    proposal_dir: Path,
    audit_path: Path,
    limit: int = 50,
    include_sensitive: bool = False,
    run_id: str | None = None,
) -> DreamRunResult:
    """Create a Dream Cycle v0 proposal Markdown and JSONL audit record."""

    run_id = run_id or f"dream-{utc_now_iso().replace(':', '').replace('-', '')}"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    reviewable = [n for n in notes if n.status in {"inbox", "needs_confirmation", "conflicting", "uncertain"}]
    reviewable.sort(key=lambda n: n.observed_at, reverse=True)
    reviewable = reviewable[: max(1, int(limit))]

    active_by_body: dict[str, MemoryNote] = {}
    for note in notes:
        if note.status not in {"active", "uncertain", "needs_confirmation"}:
            continue
        key = _normalized_body(note.body)
        if key and key not in active_by_body:
            active_by_body[key] = note

    items: list[DreamProposalItem] = []
    counts: dict[str, int] = {}
    for note in reviewable:
        classification, route, action, reason = classify_note_for_dream(note)
        key = _normalized_body(note.body)
        duplicate = active_by_body.get(key)
        duplicate_of = ""
        if duplicate and duplicate.id != note.id:
            action = "propose_archive_duplicate"
            reason = f"same normalized body as existing {duplicate.status} note"
            duplicate_of = duplicate.id
        sensitivity = classify_sensitivity(note.body)
        if sensitivity in {"sensitive", "secret_ref"} and sensitivity != note.sensitivity:
            reason = f"body classified as {sensitivity}; {reason}"
        item = DreamProposalItem(
            note_id=note.id,
            note_path=note.path,
            note_type=note.type,
            status=note.status,
            sensitivity=sensitivity if sensitivity in {"sensitive", "secret_ref"} else note.sensitivity,
            classification=classification,
            route=route,
            action=action,
            reason=reason,
            duplicate_of=duplicate_of,
            excerpt=_excerpt(note, include_sensitive=include_sensitive),
        )
        items.append(item)
        counts[item.action] = counts.get(item.action, 0) + 1
        counts[f"route:{item.route}"] = counts.get(f"route:{item.route}", 0) + 1
        counts[f"classification:{item.classification}"] = counts.get(f"classification:{item.classification}", 0) + 1

    generated_at = utc_now_iso()
    proposal_path = proposal_dir / f"{generated_at[:10]}-{run_id}.md"
    lines = [
        "---",
        f"type: dream_cycle_proposal",
        f"run_id: {run_id}",
        f"generated_at: {generated_at}",
        f"scanned: {len(reviewable)}",
        f"proposed: {len(items)}",
        "---",
        "",
        "# Dream Cycle v0 proposal",
        "",
        "Safe review/proposal pass. This file is evidence for human/agent review, not an autonomous memory mutation.",
        "",
        "## Guardrails",
        "",
        "- Does not edit constitution files (`SOUL.md`, `USER.md`, `MEMORY.md`, `AGENTS.md`).",
        "- Does not silently promote inbox notes into stable truth.",
        "- Treats hypotheses/open loops as low-authority review items.",
        "- Redacts sensitive excerpts unless explicitly requested.",
        "",
        "## Counts",
        "",
    ]
    if counts:
        for key in sorted(counts):
            lines.append(f"- {key}: {counts[key]}")
    else:
        lines.append("- no reviewable items found")
    lines.extend(["", "## Proposed actions", ""])
    for idx, item in enumerate(items, 1):
        lines.extend([
            f"### {idx}. {item.action}: `{item.note_id}`",
            "",
            f"- path: `{item.note_path}`",
            f"- type: `{item.note_type}`",
            f"- status: `{item.status}`",
            f"- sensitivity: `{item.sensitivity}`",
            f"- classification: `{item.classification}`",
            f"- route: `{item.route}`",
            f"- reason: {item.reason}",
        ])
        if item.duplicate_of:
            lines.append(f"- duplicate_of: `{item.duplicate_of}`")
        lines.extend([f"- excerpt: {item.excerpt}", ""])
    lines.extend(["", *_general_review_sections(notes, items, include_sensitive=include_sensitive), *_conflict_sections(notes), "", *_behavioral_gap_sections(_behavioral_rows(notes)), ""])
    proposal_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    audit = {
        "run_id": run_id,
        "generated_at": generated_at,
        "proposal_path": str(proposal_path),
        "scanned": len(reviewable),
        "proposed": len(items),
        "counts": counts,
        "changed_files": [str(proposal_path), str(audit_path)],
        "items": [item.as_dict() for item in items],
    }
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(audit, ensure_ascii=False, sort_keys=True) + "\n")

    return DreamRunResult(
        run_id=run_id,
        proposal_path=str(proposal_path),
        audit_path=str(audit_path),
        scanned=len(reviewable),
        proposed=len(items),
        counts=counts,
        changed_files=[str(proposal_path), str(audit_path)],
        items=items,
    )
