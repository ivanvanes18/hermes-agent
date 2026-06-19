"""Schemas for the readable_tree memory provider.

Markdown files are the source of truth.  SQLite is only a rebuildable index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import re

import yaml

STATUSES = {
    "inbox",
    "active",
    "open_loop",
    "uncertain",
    "needs_confirmation",
    "superseded",
    "archived",
    "conflicting",
    "needs_review",
}
SENSITIVITIES = {"public", "internal", "sensitive", "secret_ref"}
HIGH_IMPACT_IMPORTANCE = {"high", "critical"}
HIGH_IMPACT_TYPES = {
    "behavior_rule",
    "decision",
    "constraint",
    "correction",
    "requirement",
    "regression_case",
    "risk",
    "measurement",
    "observation",
    "current_state",
}
BEHAVIORAL_TYPES = {
    "correction",
    "behavior_rule",
    "regression_case",
    "outcome_review",
}
MISTAKE_CLASSES = {
    "wrong_task_layer",
    "wrong_agent_routing",
    "acted_when_should_ask",
    "asked_when_should_act",
    "failed_to_use_skill",
    "claimed_without_check",
    "memory_miswrite",
    "memory_miss",
    "scope_creep",
    "wrong_output_contract",
    "style_regression",
    "unknown",
}
SOURCE_BACKED_QUALITIES = {"confirmed", "direct", "file", "manual", "session", "tool"}
EVENT_SCHEMA_VERSION = 1
MEMORY_EVENT_TYPES = {
    "raw_turn_captured",
    "session_summary_created",
    "memory_candidate_extracted",
    "memory_note_promoted",
    "memory_note_activated",
    "memory_note_retired",
    "memory_note_superseded",
    "conflict_detected",
    "conflict_resolved",
    "correction_received",
    "behavioral_chain_created",
    "behavior_rule_created",
    "regression_case_created",
    "behavior_outcome_reviewed",
    "dream_cycle_proposed",
    "dream_cycle_action_applied",
    "memory_event",
}
# Backward-compatible alias for code written during the first event-spine slice.
EVENT_TYPES = MEMORY_EVENT_TYPES

_FRONTMATTER_RE = re.compile(r"^---\n(?P<yaml>.*?)\n---\n(?P<body>.*)$", re.DOTALL)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str, *, fallback: str = "memory") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or fallback


def make_note_id(body: str, observed_at: str | None = None) -> str:
    seed = f"{observed_at or utc_now_iso()}\n{body}".encode("utf-8", "replace")
    return hashlib.sha1(seed).hexdigest()[:12]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(value)]


@dataclass
class MemoryNote:
    """A single readable memory note with YAML frontmatter."""

    body: str
    type: str = "fact"
    agent: str = "default"
    scope: str = "general"
    status: str = "inbox"
    observed_at: str = field(default_factory=utc_now_iso)
    confidence: str = "uncertain"
    importance: str = "medium"
    sensitivity: str = "internal"
    tags: list[str] = field(default_factory=list)
    id: str = ""
    project: str = ""
    source: str = ""
    source_ids: list[str] = field(default_factory=list)
    source_quality: str = ""
    event_ids: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    pinned: bool = False
    pin_scope: str = ""
    path: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_note_id(self.body, self.observed_at)
        self.tags = _as_list(self.tags)
        self.source_ids = _as_list(self.source_ids)
        self.event_ids = _as_list(self.event_ids)
        self.supersedes = _as_list(self.supersedes)
        self.superseded_by = _as_list(self.superseded_by)
        self.pinned = bool(self.pinned)
        if self.status not in STATUSES:
            self.status = "inbox"
        if self.sensitivity not in SENSITIVITIES:
            self.sensitivity = "internal"
        self.apply_guardrails()

    @property
    def has_source(self) -> bool:
        return bool(self.source or self.source_ids or self.source_quality in SOURCE_BACKED_QUALITIES)

    @property
    def high_impact(self) -> bool:
        return self.importance in HIGH_IMPACT_IMPORTANCE or self.type in HIGH_IMPACT_TYPES

    def apply_guardrails(self) -> None:
        """Only sourced memories can enter active retrieval by default."""
        if not self.has_source and self.status == "active":
            self.status = "needs_confirmation"
            if "needs-source" not in self.tags:
                self.tags.append("needs-source")

    def to_frontmatter(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "agent": self.agent,
            "scope": self.scope,
            "status": self.status,
            "observed_at": self.observed_at,
            "confidence": self.confidence,
            "importance": self.importance,
            "sensitivity": self.sensitivity,
            "tags": self.tags,
        }
        if self.project:
            data["project"] = self.project
        if self.source:
            data["source"] = self.source
        if self.source_ids:
            data["source_ids"] = self.source_ids
        if self.source_quality:
            data["source_quality"] = self.source_quality
        if self.event_ids:
            data["event_ids"] = self.event_ids
        if self.supersedes:
            data["supersedes"] = self.supersedes
        if self.superseded_by:
            data["superseded_by"] = self.superseded_by
        if self.pinned:
            data["pinned"] = True
        if self.pin_scope:
            data["pin_scope"] = self.pin_scope
        return data

    def to_markdown(self) -> str:
        frontmatter = yaml.safe_dump(
            self.to_frontmatter(),
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = self.body.strip() + "\n"
        return f"---\n{frontmatter}\n---\n\n{body}"

    @classmethod
    def from_markdown(cls, text: str, *, path: str = "") -> "MemoryNote":
        match = _FRONTMATTER_RE.match(text.strip() + "\n")
        if not match:
            raise ValueError("Memory note is missing YAML frontmatter")
        data = yaml.safe_load(match.group("yaml")) or {}
        body = match.group("body").strip()
        note = cls(
            id=str(data.get("id") or ""),
            type=str(data.get("type") or "fact"),
            agent=str(data.get("agent") or "default"),
            scope=str(data.get("scope") or "general"),
            status=str(data.get("status") or "inbox"),
            observed_at=str(data.get("observed_at") or utc_now_iso()),
            confidence=str(data.get("confidence") or "uncertain"),
            importance=str(data.get("importance") or "medium"),
            sensitivity=str(data.get("sensitivity") or "internal"),
            tags=_as_list(data.get("tags")),
            project=str(data.get("project") or ""),
            source=str(data.get("source") or ""),
            source_ids=_as_list(data.get("source_ids")),
            source_quality=str(data.get("source_quality") or ""),
            event_ids=_as_list(data.get("event_ids")),
            supersedes=_as_list(data.get("supersedes")),
            superseded_by=_as_list(data.get("superseded_by")),
            pinned=bool(data.get("pinned") or False),
            pin_scope=str(data.get("pin_scope") or ""),
            body=body,
            path=path,
        )
        return note

    @classmethod
    def from_file(cls, path: Path) -> "MemoryNote":
        return cls.from_markdown(path.read_text(encoding="utf-8"), path=str(path))
