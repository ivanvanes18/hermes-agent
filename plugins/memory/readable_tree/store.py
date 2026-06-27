"""Readable Markdown memory tree store."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .behavioral import build_behavioral_chain, classify_mistake
from .dream import build_dream_proposal
from .extractor import EXTRACTOR_VERSION, classify_sensitivity, extract_candidates, redact_sensitive_text
from .index import ReadableMemoryIndex
from .lifecycle import can_activate
from .regression import build_regression_report
from .schemas import EVENT_SCHEMA_VERSION, EVENT_TYPES, MemoryNote, slugify, utc_now_iso
from .session_summary import build_session_summary

TREE_DIRS = [
    "inbox",
    "facts",
    "decisions",
    "projects",
    "open_loops",
    "corrections",
    "behavior_rules",
    "regression_cases",
    "outcome_reviews",
    "constraints",
    "procedures",
    "reviews",
    "archive",
]
TYPE_DIR = {
    "decision": "decisions",
    "constraint": "constraints",
    "correction": "corrections",
    "behavior_rule": "behavior_rules",
    "regression_case": "regression_cases",
    "outcome_review": "outcome_reviews",
    "procedure": "procedures",
    "open_loop": "open_loops",
    "artifact": "facts",
    "intention": "open_loops",
    "task": "projects",
    "measurement": "facts",
    "observation": "facts",
    "current_state": "facts",
    "requirement": "facts",
    "risk": "facts",
    "fact": "facts",
}


class ReadableMemoryStore:
    def __init__(self, hermes_home: str | Path, *, agent: str = "default"):
        self.hermes_home = Path(hermes_home).expanduser()
        self.root = self.hermes_home / "readable_memory"
        self.tree = self.root / "tree"
        self.raw = self.root / "raw"
        self.events_path = self.raw / "events.jsonl"
        self.index = ReadableMemoryIndex(self.root / "index.sqlite")
        self.manifest_path = self.root / "manifest.json"
        self.retrieval_log_path = self.root / "retrieval.log.jsonl"
        self.metrics_log_path = self.root / "metrics.log.jsonl"
        self.dream_log_path = self.root / "dream.log.jsonl"
        self.promotion_log_path = self.root / "promotion.log.jsonl"
        self.activation_log_path = self.root / "activation.log.jsonl"
        self.retirement_log_path = self.root / "retirement.log.jsonl"
        self.agent = agent

    def initialize(self) -> None:
        self.raw.mkdir(parents=True, exist_ok=True)
        self.tree.mkdir(parents=True, exist_ok=True)
        for dirname in TREE_DIRS:
            (self.tree / dirname).mkdir(parents=True, exist_ok=True)
        for name, title in {
            "README.md": "# Readable memory\n\nMarkdown files are the source of truth. SQLite is rebuildable.\n",
            "profile.md": "# Profile\n\nStable profile-level facts promoted by review.\n",
            "current-state.md": "# Current state\n\nActive operational state.\n",
            "timeline.md": "# Timeline\n\nChronological promoted events.\n",
            "changelog.md": "# Changelog\n\nMemory tree changes.\n",
        }.items():
            path = self.tree / name
            if not path.exists():
                path.write_text(title, encoding="utf-8")
        self._write_manifest(self._read_manifest())
        self.index.initialize()

    def _read_manifest(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("extracted_turn_ids", [])
                    data.setdefault("extracted_turns", {})
                    return data
            except Exception:
                pass
        return {"version": 1, "agent": self.agent, "extracted_turn_ids": [], "extracted_turns": {}, "updated_at": utc_now_iso()}

    def _write_manifest(self, data: dict[str, Any]) -> None:
        data["updated_at"] = utc_now_iso()
        data.setdefault("version", 1)
        data.setdefault("agent", self.agent)
        data.setdefault("extracted_turn_ids", [])
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def append_raw_turn(self, user: str, assistant: str, *, session_id: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        timestamp = utc_now_iso()
        record_id = f"turn-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        record = {
            "id": record_id,
            "timestamp": timestamp,
            "session_id": session_id,
            "agent": self.agent,
            "user": user,
            "assistant": assistant,
            "metadata": metadata or {},
        }
        with (self.raw / "turns.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.append_event(
            "raw_turn_captured",
            source_ids=[record_id],
            payload={"raw_turn_id": record_id, "raw_path": "raw/turns.jsonl"},
            session_id=session_id,
        )
        return record

    def iter_raw_turns(self) -> list[dict[str, Any]]:
        path = self.raw / "turns.jsonl"
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except Exception:
                continue
        return records

    def write_session_summary(self, session_id: str) -> dict[str, Any]:
        """Write a deterministic reviewable summary note for one session."""
        self.initialize()
        selected_turns = [
            record for record in self.iter_raw_turns()
            if str(record.get("session_id") or "") == str(session_id or "")
        ]
        if not selected_turns:
            return {"success": False, "session_id": session_id, "error": "no raw turns found for session"}
        note = build_session_summary(selected_turns)
        note.agent = self.agent
        path = self.write_note(note)
        event = self.append_event(
            "session_summary_created",
            source_ids=note.source_ids,
            note_ids=[note.id],
            payload={"session_id": session_id, "note_type": note.type, "note_status": note.status},
            session_id=session_id,
        )
        if event["id"] not in note.event_ids:
            note.event_ids.append(event["id"])
            path = self._rewrite_note(note)
            self.rebuild_index()
        return {
            "success": True,
            "session_id": session_id,
            "note_id": note.id,
            "path": str(path),
            "event_id": event["id"],
            "source_ids": note.source_ids,
        }

    @staticmethod
    def _event_type_for_note(note: MemoryNote) -> str:
        mapping = {
            "correction": "correction_received",
        }
        return mapping.get(note.type, "memory_candidate_extracted")

    def append_event(
        self,
        event_type: str,
        *,
        source_ids: list[str] | None = None,
        note_ids: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Append a structured event to the raw event log.

        Events are the replayable spine between raw turns and derived notes. The
        event log is append-only JSONL; Markdown notes link back through
        `event_ids` frontmatter.
        """
        self.initialize()
        timestamp = utc_now_iso()
        event_id = f"evt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        event_payload = dict(payload or {})
        normalized_type = str(event_type or "memory_event")
        if normalized_type not in EVENT_TYPES:
            event_payload.setdefault("original_type", normalized_type)
            normalized_type = "memory_event"
        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "id": event_id,
            "type": normalized_type,
            "timestamp": timestamp,
            "agent": self.agent,
            "session_id": session_id,
            "source_ids": [str(value) for value in (source_ids or []) if str(value).strip()],
            "note_ids": [str(value) for value in (note_ids or []) if str(value).strip()],
            "payload": event_payload,
        }
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def record_correction(
        self,
        correction_text: str,
        *,
        project: str = "",
        source_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        """Create correction, behavior rule, and regression case notes from a user correction."""
        self.initialize()
        mistake_class = classify_mistake(correction_text)
        notes = build_behavioral_chain(
            correction_text,
            agent=self.agent,
            project=project,
            source_id=source_id,
            session_id=session_id,
        )
        written: list[MemoryNote] = []
        for note in notes:
            self.write_note(note)
            written.append(note)
        event = self.append_event(
            "behavioral_chain_created",
            source_ids=[source_id] if source_id else [],
            note_ids=[note.id for note in written],
            payload={"mistake_class": mistake_class},
            session_id=session_id,
        )
        for note in written:
            if event["id"] not in note.event_ids:
                note.event_ids.append(event["id"])
                self._rewrite_note(note)
        self.rebuild_index()
        self.log_metric(
            "corrections_recorded",
            session_id=session_id,
            metadata={"mistake_class": mistake_class, "note_count": len(written)},
        )
        self.log_behavior_memory_counts(session_id=session_id)
        return {
            "success": True,
            "mistake_class": mistake_class,
            "event_id": event["id"],
            "note_ids": [note.id for note in written],
            "note_types": [note.type for note in written],
            "note_count": len(written),
        }

    def review_behavior_outcome(
        self,
        rule_id: str,
        outcome: str,
        evidence: str,
        *,
        session_id: str = "",
        rule_used_in_answer: bool | None = None,
    ) -> dict[str, Any]:
        """Write an outcome review for a behavior rule and linked regression cases."""
        self.initialize()
        allowed = {"fixed", "repeated", "unclear", "superseded"}
        normalized = outcome if outcome in allowed else "unclear"
        notes = self.list_notes()
        rule = next((candidate for candidate in notes if candidate.id == rule_id and candidate.type == "behavior_rule"), None)
        rule_sources = set(rule.source_ids if rule else [])
        rule_mistakes = {tag for tag in (rule.tags if rule else []) if tag.startswith("mistake:")}
        related_cases = []
        for candidate in notes:
            if candidate.type != "regression_case" or candidate.status != "active":
                continue
            candidate_sources = set(candidate.source_ids or [])
            candidate_mistakes = {tag for tag in candidate.tags if tag.startswith("mistake:")}
            if (rule_sources and candidate_sources & rule_sources) or (rule_mistakes and candidate_mistakes & rule_mistakes):
                related_cases.append(candidate)
        related_case_ids = [case.id for case in related_cases]
        tags = ["behavioral-memory", f"outcome:{normalized}", f"rule:{rule_id}"]
        tags.extend(f"case:{case_id}" for case_id in related_case_ids)
        used_text = "unknown" if rule_used_in_answer is None else str(bool(rule_used_in_answer)).lower()
        related_text = ", ".join(related_case_ids) if related_case_ids else "none"
        note = MemoryNote(
            type="outcome_review",
            agent=self.agent,
            scope="behavioral_learning",
            status="active",
            confidence="reported",
            importance="high" if normalized == "repeated" else "medium",
            sensitivity="internal",
            tags=tags,
            source="outcome_review",
            source_ids=[rule_id],
            source_quality="manual",
            body=(
                f"Outcome review for behavior rule {rule_id}: {normalized}.\n"
                f"rule_used_in_answer: {used_text}\n"
                f"related_regression_cases: {related_text}\n"
                f"Evidence: {evidence}"
            ),
        )
        self.write_note(note)
        event = self.append_event(
            "behavior_outcome_reviewed",
            source_ids=[rule_id],
            note_ids=[note.id, *related_case_ids],
            payload={
                "rule_id": rule_id,
                "outcome": normalized,
                "rule_used_in_answer": rule_used_in_answer,
                "related_case_ids": related_case_ids,
            },
            session_id=session_id,
        )
        note.event_ids.append(event["id"])
        self._rewrite_note(note)
        self.rebuild_index()
        if normalized in {"fixed", "repeated"}:
            self.log_metric(
                f"outcome_{normalized}",
                session_id=session_id,
                metadata={
                    "rule_id": rule_id,
                    "note_id": note.id,
                    "rule_used_in_answer": rule_used_in_answer,
                    "related_case_ids": related_case_ids,
                },
            )
        return {
            "success": True,
            "outcome": normalized,
            "rule_used_in_answer": rule_used_in_answer,
            "related_case_ids": related_case_ids,
            "note_id": note.id,
            "event_id": event["id"],
        }

    def iter_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except Exception:
                continue
        return records

    def log_retrieval(
        self,
        *,
        query: str,
        rows: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
        source: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a compact retrieval trace for dogfood/debugging."""
        self.initialize()
        record = {
            "timestamp": utc_now_iso(),
            "agent": self.agent,
            "session_id": session_id,
            "source": source,
            "query": query,
            "attempts": attempts,
            "result_ids": [str(row.get("id") or "") for row in rows if row.get("id")],
            "result_count": len(rows),
            "metadata": metadata or {},
        }
        with self.retrieval_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_metric(
        self,
        name: str,
        *,
        value: int | float = 1,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append local JSONL rollout metrics; never sends telemetry."""
        self.root.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": utc_now_iso(),
            "agent": self.agent,
            "session_id": session_id,
            "metric": name,
            "value": value,
            "metadata": metadata or {},
        }
        with self.metrics_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def iter_metrics(self) -> list[dict[str, Any]]:
        if not self.metrics_log_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.metrics_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except Exception:
                continue
        return records

    def log_behavior_memory_counts(self, *, session_id: str = "") -> None:
        """Log global active behavioral-memory counts after a mutation."""
        notes = self.list_notes()
        self.log_metric(
            "behavior_rules_active",
            value=len([note for note in notes if note.type == "behavior_rule" and note.status == "active"]),
            session_id=session_id,
        )
        self.log_metric(
            "regression_cases_active",
            value=len([note for note in notes if note.type == "regression_case" and note.status == "active"]),
            session_id=session_id,
        )

    def iter_retrieval_logs(self) -> list[dict[str, Any]]:
        if not self.retrieval_log_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.retrieval_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except Exception:
                continue
        return records

    def note_path_for(self, note: MemoryNote) -> Path:
        if note.status == "inbox":
            directory = "inbox"
        elif note.status in {"archived", "superseded"}:
            directory = "archive"
        else:
            directory = TYPE_DIR.get(note.type, "facts")
        filename = f"{note.observed_at[:10]}-{slugify(note.type)}-{note.id}.md"
        return self.tree / directory / filename

    @staticmethod
    def _conflict_tokens(text: str) -> set[str]:
        stopwords = {
            "the", "and", "for", "this", "that", "with", "must", "should", "always", "never",
            "true", "false", "enabled", "disabled", "enable", "disable", "default", "defaults",
            "be", "is", "are", "to", "by", "on", "off", "not", "no",
            "по", "умолчанию", "должен", "должна", "должно", "обязательно", "нельзя", "никогда",
            "включен", "включена", "включено", "выключен", "выключена", "выключено", "не", "да", "нет",
        }
        tokens = set()
        for raw in re.findall(r"[\wа-яё]+", text.casefold(), flags=re.IGNORECASE):
            token = raw.strip("_-")
            if len(token) < 3 or token in stopwords or token.isdigit():
                continue
            tokens.add(token)
        return tokens

    @staticmethod
    def _conflict_polarity(text: str) -> str:
        normalized = f" {text.casefold()} "
        negative_patterns = [
            r"\b(?:not|never|no|false|disabled|disable|off)\b",
            r"\b(?:нельзя|никогда|нет|выключен\w*|отключен\w*)\b",
            r"\bне\s+(?:должен|должна|должно|надо|нужно|использовать|делать|включать)\b",
        ]
        positive_patterns = [
            r"\b(?:must|should|always|true|enabled|enable|on)\b",
            r"\b(?:обязательно|должен|должна|должно|включен\w*)\b",
        ]
        has_negative = any(re.search(pattern, normalized, re.IGNORECASE) for pattern in negative_patterns)
        has_positive = any(re.search(pattern, normalized, re.IGNORECASE) for pattern in positive_patterns)
        if has_negative and not has_positive:
            return "negative"
        if has_positive and not has_negative:
            return "positive"
        # Explicit value words beat modal words: "must be disabled" is negative,
        # "should be enabled" is positive.
        if re.search(r"\b(?:disabled|disable|off|false|выключен\w*|отключен\w*)\b", normalized, re.IGNORECASE):
            return "negative"
        if re.search(r"\b(?:enabled|enable|on|true|включен\w*)\b", normalized, re.IGNORECASE):
            return "positive"
        return ""

    def detect_conflicts(self, note: MemoryNote | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        """Detect deterministic conflicts.

        With ``note`` provided, checks one review candidate against active
        same-scope notes. With no note, performs a bounded pass over existing
        unresolved review/conflicting notes and returns conflict candidates for
        Dream Cycle / operator review.
        """
        if note is None:
            results: list[dict[str, Any]] = []
            for candidate in self.list_notes():
                if candidate.status not in {"inbox", "needs_confirmation", "uncertain", "conflicting"}:
                    continue
                candidate_conflicts = self.detect_conflicts(candidate, limit=limit)
                if not candidate_conflicts and candidate.status == "conflicting":
                    explicit_ids = self._conflict_ids_from_tags(candidate)
                    candidate_conflicts = [{"note_id": value, "shared_tokens": [], "existing_polarity": "", "candidate_polarity": ""} for value in explicit_ids]
                if not candidate_conflicts:
                    continue
                results.append({
                    "candidate_id": candidate.id,
                    "candidate_path": candidate.path,
                    "status": candidate.status,
                    "conflict_ids": [str(item.get("note_id") or "") for item in candidate_conflicts if item.get("note_id")],
                    "conflicts": candidate_conflicts,
                })
                if len(results) >= max(1, int(limit)):
                    break
            return results
        if note.status not in {"inbox", "needs_confirmation", "uncertain", "conflicting"}:
            return []
        note_polarity = self._conflict_polarity(note.body)
        if not note_polarity:
            return []
        note_tokens = self._conflict_tokens(note.body)
        if len(note_tokens) < 2:
            return []
        conflicts: list[dict[str, Any]] = []
        for existing in self.list_notes():
            if existing.id == note.id or existing.status != "active":
                continue
            if existing.agent != note.agent:
                continue
            if existing.project != note.project:
                continue
            same_specific_scope = existing.scope == note.scope and note.scope != "general"
            same_type = existing.type == note.type
            same_fact_constraint = {existing.type, note.type} <= {"fact", "constraint", "requirement"}
            if not (same_specific_scope or same_type or same_fact_constraint):
                continue
            existing_polarity = self._conflict_polarity(existing.body)
            if not existing_polarity or existing_polarity == note_polarity:
                continue
            existing_tokens = self._conflict_tokens(existing.body)
            shared = sorted(note_tokens & existing_tokens)
            min_subject_tokens = 2 if min(len(note_tokens), len(existing_tokens)) <= 3 else 3
            if len(shared) < min_subject_tokens:
                continue
            overlap = len(shared) / max(1, min(len(note_tokens), len(existing_tokens)))
            if overlap < 0.5:
                continue
            conflicts.append(
                {
                    "note_id": existing.id,
                    "note_path": existing.path,
                    "shared_tokens": shared,
                    "existing_polarity": existing_polarity,
                    "candidate_polarity": note_polarity,
                }
            )
        return conflicts

    def apply_conflict_detection(self, note: MemoryNote) -> list[dict[str, Any]]:
        conflicts = self.detect_conflicts(note)
        if not conflicts:
            return []
        note.status = "conflicting"
        self._add_tags(note, "conflict-detected", "needs-review")
        for conflict in conflicts:
            tag = f"conflicts-with-{conflict['note_id']}"
            if tag not in note.tags:
                note.tags.append(tag)
        return conflicts

    def write_note(self, note: MemoryNote) -> Path:
        self.initialize()
        classified_sensitivity = classify_sensitivity(note.body)
        if classified_sensitivity in {"sensitive", "secret_ref"}:
            note.sensitivity = classified_sensitivity
            note.body = redact_sensitive_text(note.body)
            if "redacted" not in note.tags:
                note.tags.append("redacted")
        self.apply_conflict_detection(note)
        path = self.note_path_for(note)
        if note.type == "observation" and path.exists():
            raise FileExistsError(f"immutable observation already exists: {path}")
        note.path = str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note.to_markdown(), encoding="utf-8")
        if note.supersedes:
            self._mark_superseded(note)
        self.rebuild_index()
        return path

    def _mark_superseded(self, replacement: MemoryNote) -> None:
        """Link old notes to a replacement without deleting historical Markdown."""
        replacement_ids = set(replacement.supersedes)
        for old_note in self.list_notes():
            if old_note.id not in replacement_ids:
                continue
            old_note.status = "superseded"
            if replacement.id not in old_note.superseded_by:
                old_note.superseded_by.append(replacement.id)
            self._rewrite_note(old_note)

    def supersede_note(
        self,
        old_id: str,
        new_id: str,
        *,
        reason: str,
        provenance: str,
        dry_run: bool = True,
        actor: str = "agent",
    ) -> dict[str, Any]:
        """Explicitly mark one note as superseded by another note.

        This preserves both Markdown files, links frontmatter in both
        directions, writes a replayable event, and rebuilds the retrieval index
        so the old note leaves default active retrieval.
        """
        self.initialize()
        old_id = str(old_id).strip()
        new_id = str(new_id).strip()
        if not old_id or not new_id:
            raise ValueError("supersede_note requires old_id and new_id")
        if old_id == new_id:
            raise ValueError("supersede_note requires distinct old_id and new_id")
        if not reason.strip():
            raise ValueError("supersede_note requires reason")
        if not provenance.strip():
            raise ValueError("supersede_note requires provenance")

        notes_by_id = {note.id: note for note in self.list_notes()}
        old_note = notes_by_id.get(old_id)
        new_note = notes_by_id.get(new_id)
        if not old_note:
            raise ValueError(f"old note not found: {old_id}")
        if not new_note:
            raise ValueError(f"new note not found: {new_id}")

        generated_at = utc_now_iso()
        before_old_status = old_note.status
        before_new_status = new_note.status
        event_id = ""
        changed_files: list[str] = []
        if not dry_run:
            old_note.status = "superseded"
            if new_note.id not in old_note.superseded_by:
                old_note.superseded_by.append(new_note.id)
            if old_note.id not in new_note.supersedes:
                new_note.supersedes.append(old_note.id)
            self._add_tags(old_note, "superseded", "superseded-by-explicit-lifecycle")
            self._add_tags(new_note, "superseding-note")
            event = self.append_event(
                "memory_note_superseded",
                note_ids=[old_note.id, new_note.id],
                source_ids=list(new_note.source_ids or old_note.source_ids),
                payload={
                    "old_note_id": old_note.id,
                    "new_note_id": new_note.id,
                    "reason": reason,
                    "provenance": provenance,
                    "before_old_status": before_old_status,
                    "after_old_status": old_note.status,
                    "new_status": new_note.status,
                    "actor": actor,
                },
            )
            event_id = str(event["id"])
            for note in (old_note, new_note):
                if event_id not in note.event_ids:
                    note.event_ids.append(event_id)
                changed_files.append(str(self._rewrite_note(note)))
            self.rebuild_index()
            with self.promotion_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "type": "memory_note_superseded",
                    "event_id": event_id,
                    "generated_at": generated_at,
                    "actor": actor,
                    "old_note_id": old_note.id,
                    "new_note_id": new_note.id,
                    "reason": reason,
                    "provenance": provenance,
                }, ensure_ascii=False, sort_keys=True) + "\n")
            with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n- {generated_at}: superseded memory note {old_note.id} "
                    f"with {new_note.id}. Reason: {reason}\n"
                )
            changed_files.extend([str(self.promotion_log_path), str(self.tree / "changelog.md")])

        return {
            "dry_run": dry_run,
            "actor": actor,
            "reason": reason,
            "provenance": provenance,
            "event_ids": [event_id] if event_id else [],
            "applied": [{
                "old_note_id": old_note.id,
                "new_note_id": new_note.id,
                "old_status": "superseded" if not dry_run else old_note.status,
                "new_status": new_note.status,
                "before_old_status": before_old_status,
                "before_new_status": before_new_status,
            }],
            "changed_files": sorted(set(changed_files)),
            "generated_at": generated_at,
        }

    def list_notes(self) -> list[MemoryNote]:
        self.initialize()
        notes: list[MemoryNote] = []
        for path in self.tree.rglob("*.md"):
            if path.parent == self.tree or path.relative_to(self.tree).parts[:1] == ("reviews",):
                continue
            try:
                notes.append(MemoryNote.from_file(path))
            except Exception:
                continue
        return notes

    def rebuild_index(self) -> None:
        self.index.rebuild(self.list_notes())

    def get_index_rows_by_ids(
        self,
        note_ids: list[str],
        *,
        statuses: list[str] | None = None,
        include_sensitive: bool = False,
        include_superseded: bool = False,
    ) -> list[dict]:
        """Resolve exact note IDs through index safety filters."""
        self.initialize()
        return self.index.rows_by_ids(
            note_ids,
            statuses=statuses,
            include_sensitive=include_sensitive,
            include_superseded=include_superseded,
        )

    def timeline_snippets_for_note_ids(self, note_ids: list[str], *, limit: int = 5) -> list[dict]:
        """Return bounded timeline snippets for selected source-backed notes."""
        from .timeline import load_timeline, summarize_timeline_for_notes

        timeline = load_timeline(self.events_path)
        return summarize_timeline_for_notes(timeline, note_ids, limit=limit)

    def rebuild_from_events(self, *, dry_run: bool = True, repair_note_event_links: bool = False) -> dict[str, Any]:
        """Replay raw structured events to verify and rebuild derived memory state.

        Markdown notes remain the final source of truth. The event log is the
        replayable spine used here to rebuild derived indexes/manifests and to
        audit links between raw turns, events, and notes. Mutating repair is
        explicit and intentionally narrow: it can rebuild the SQLite index,
        restore `manifest.extracted_turn_ids` from extraction events, and add
        missing note->event frontmatter links when the event already points at
        that note.
        """
        self.initialize()
        notes = self.list_notes()
        notes_by_id = {note.id: note for note in notes}
        events = self.iter_events()
        raw_turn_ids = {str(record.get("id") or "") for record in self.iter_raw_turns() if record.get("id")}
        manifest = self._read_manifest()
        existing_extracted = {str(value) for value in (manifest.get("extracted_turn_ids") or []) if str(value).strip()}
        extraction_event_types = {
            "memory_candidate_extracted",
            "correction_received",
        }

        extracted_from_events: set[str] = set()
        event_ids = {str(event.get("id") or "") for event in events if event.get("id")}
        missing_notes: list[dict[str, Any]] = []
        missing_raw_turns: list[dict[str, Any]] = []
        missing_events: list[dict[str, Any]] = []
        repaired_notes: list[str] = []
        event_links_by_note: dict[str, list[str]] = {}

        for event in events:
            event_id = str(event.get("id") or "")
            event_type = str(event.get("type") or "")
            note_ids = [str(value) for value in (event.get("note_ids") or []) if str(value).strip()]
            source_ids = [str(value) for value in (event.get("source_ids") or []) if str(value).strip()]
            for note_id in note_ids:
                event_links_by_note.setdefault(note_id, [])
                if event_id and event_id not in event_links_by_note[note_id]:
                    event_links_by_note[note_id].append(event_id)
                if note_id not in notes_by_id:
                    missing_notes.append({"event_id": event_id, "event_type": event_type, "note_id": note_id})
            if event_type in extraction_event_types:
                for source_id in source_ids:
                    extracted_from_events.add(source_id)
                    if source_id.startswith("turn-") and raw_turn_ids and source_id not in raw_turn_ids:
                        missing_raw_turns.append({"event_id": event_id, "source_id": source_id})

        for note in notes:
            for event_id in note.event_ids:
                if event_id not in event_ids:
                    missing_events.append({"note_id": note.id, "event_id": event_id})

        changed_files: list[str] = []
        manifest_would_add = sorted(extracted_from_events - existing_extracted)
        manifest_would_remove = sorted(existing_extracted - extracted_from_events)
        note_link_repairs: list[dict[str, Any]] = []
        for note_id, linked_event_ids in sorted(event_links_by_note.items()):
            note = notes_by_id.get(note_id)
            if not note:
                continue
            missing_for_note = [event_id for event_id in linked_event_ids if event_id not in note.event_ids]
            if missing_for_note:
                note_link_repairs.append({"note_id": note_id, "event_ids": missing_for_note})
                if repair_note_event_links and not dry_run:
                    for event_id in missing_for_note:
                        note.event_ids.append(event_id)
                    new_path = self._rewrite_note(note)
                    changed_files.append(str(new_path))
                    repaired_notes.append(note_id)

        if not dry_run:
            if extracted_from_events != existing_extracted:
                manifest["extracted_turn_ids"] = sorted(extracted_from_events)
                self._write_manifest(manifest)
                changed_files.append(str(self.manifest_path))
            self.rebuild_index()
            changed_files.append(str(self.index.db_path))
            with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n- {utc_now_iso()}: rebuilt readable memory derived state from "
                    f"{len(events)} events ({len(repaired_notes)} note link repairs).\n"
                )
            changed_files.append(str(self.tree / "changelog.md"))

        return {
            "dry_run": dry_run,
            "events": len(events),
            "raw_turns": len(raw_turn_ids),
            "notes": len(notes),
            "extracted_turn_ids_from_events": sorted(extracted_from_events),
            "manifest": {
                "existing_extracted_turn_ids": sorted(existing_extracted),
                "would_add": manifest_would_add,
                "would_remove": manifest_would_remove,
            },
            "integrity": {
                "missing_notes_for_events": missing_notes,
                "missing_raw_turns_for_events": missing_raw_turns,
                "missing_events_for_notes": missing_events,
                "note_event_link_repairs": note_link_repairs,
            },
            "repaired_notes": sorted(repaired_notes),
            "changed_files": sorted(set(changed_files)),
            "status": "ok" if not (missing_notes or missing_raw_turns or missing_events) else "needs_review",
        }

    def _iter_unextracted_raw_turns(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        manifest = self._read_manifest()
        done = set(manifest.get("extracted_turn_ids") or [])
        records: list[dict[str, Any]] = []
        for record in self.iter_raw_turns():
            rid = str(record.get("id") or "")
            if not rid or rid in done:
                continue
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
        return records

    def flush_unprocessed_turns(
        self,
        *,
        project: str = "",
        limit: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Extract unprocessed raw turns into reviewable candidates.

        Dry-run is side-effect free: it does not update the manifest, write notes,
        or append extraction events. Apply mode records extractor version per raw
        turn so future backfills can distinguish stale derived candidates.
        """
        self.initialize()
        manifest = self._read_manifest()
        done = set(str(value) for value in (manifest.get("extracted_turn_ids") or []) if str(value).strip())
        extracted_turns = dict(manifest.get("extracted_turns") or {})
        records = self._iter_unextracted_raw_turns(limit=limit)
        candidates: list[dict[str, Any]] = []
        written: list[Path] = []
        written_by_turn: dict[str, int] = {}
        event_ids: list[str] = []

        for record in records:
            rid = str(record.get("id") or "")
            session_id = str(record.get("session_id") or "")
            notes = extract_candidates(record, agent=self.agent, project=project)
            turn_event_ids: list[str] = []
            for note in notes:
                data = note.to_frontmatter()
                data["body"] = note.body
                data["proposed_path"] = str(self.note_path_for(note))
                data["source_turn_id"] = rid
                data["extractor_version"] = EXTRACTOR_VERSION
                candidates.append(data)
                if dry_run:
                    continue
                conflicts = self.apply_conflict_detection(note)
                event = self.append_event(
                    self._event_type_for_note(note),
                    source_ids=[rid] if rid else [],
                    note_ids=[note.id],
                    payload={
                        "note_type": note.type,
                        "note_status": note.status,
                        "project": note.project,
                        "conflicts_with": [item["note_id"] for item in conflicts],
                        "extractor_version": EXTRACTOR_VERSION,
                    },
                    session_id=session_id,
                )
                event_id = str(event["id"])
                event_ids.append(event_id)
                turn_event_ids.append(event_id)
                if event["id"] not in note.event_ids:
                    note.event_ids.append(event["id"])
                written.append(self.write_note(note))
                written_by_turn[rid] = written_by_turn.get(rid, 0) + 1
            if not dry_run and rid:
                done.add(rid)
                extracted_turns[rid] = {
                    "extractor_version": EXTRACTOR_VERSION,
                    "candidate_count": len(notes),
                    "event_ids": turn_event_ids,
                    "extracted_at": utc_now_iso(),
                }

        changed_files: list[str] = []
        if not dry_run:
            manifest["extracted_turn_ids"] = sorted(done)
            manifest["extracted_turns"] = extracted_turns
            manifest["extractor_version"] = EXTRACTOR_VERSION
            self._write_manifest(manifest)
            changed_files.append(str(self.manifest_path))
            if written:
                self.rebuild_index()
                changed_files.append(str(self.index.db_path))
                with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
                    fh.write(f"\n- {utc_now_iso()}: flushed {len(written)} candidates to inbox/tree with extractor {EXTRACTOR_VERSION}.\n")
                changed_files.append(str(self.tree / "changelog.md"))

        return {
            "dry_run": dry_run,
            "extractor_version": EXTRACTOR_VERSION,
            "raw_turns_scanned": len(records),
            "candidate_count": len(candidates),
            "written_count": len(written),
            "written_by_turn": written_by_turn,
            "event_ids": event_ids,
            "candidates": candidates,
            "written": [str(path) for path in written],
            "count": len(written),
            "note_paths": [str(path) for path in written],
            "changed_files": sorted(set(changed_files + [str(path) for path in written])),
        }

    def preview_flush_turns(self, *, project: str = "", limit: int | None = None) -> dict[str, Any]:
        """Preview candidate notes from unprocessed raw turns without writing them."""
        return self.flush_unprocessed_turns(project=project, limit=limit, dry_run=True)

    def flush_turns(self, *, project: str = "", limit: int | None = None) -> list[Path]:
        """Extract unprocessed raw turns into reviewable Markdown notes."""
        result = self.flush_unprocessed_turns(project=project, limit=limit, dry_run=False)
        return [Path(path) for path in result.get("note_paths", [])]

    def dream_cycle(self, *, limit: int = 50, include_sensitive: bool = False) -> dict[str, Any]:
        """Run Dream Cycle v0 as a safe review/proposal pass.

        This writes proposal/audit artifacts only. It deliberately does not
        promote inbox notes, edit constitution files, or apply proposed diffs.
        """
        self.initialize()
        self.rebuild_index()
        result = build_dream_proposal(
            notes=self.list_notes(),
            proposal_dir=self.tree / "reviews" / "dream-cycle",
            audit_path=self.dream_log_path,
            limit=limit,
            include_sensitive=include_sensitive,
        )
        with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n- {utc_now_iso()}: Dream Cycle v0 proposal {result.run_id} "
                f"scanned {result.scanned} notes, proposed {result.proposed} actions.\n"
            )
        return result.as_dict()

    def run_regression_report(self, *, limit: int = 50, dry_run: bool = True) -> dict[str, Any]:
        """Build a deterministic behavioral regression report without mutating memory."""
        self.initialize()
        return build_regression_report(self.list_notes(), limit=limit, dry_run=dry_run)

    def _dream_audit_records(self) -> list[dict[str, Any]]:
        if not self.dream_log_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.dream_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except Exception:
                continue
        return records

    def _select_dream_audit(self, *, run_id: str = "", proposal_path: str = "") -> dict[str, Any]:
        records = self._dream_audit_records()
        if not records:
            raise ValueError("no Dream Cycle audit records found; run readable_memory_dream_cycle first")
        if run_id:
            for record in reversed(records):
                if str(record.get("run_id") or "") == run_id:
                    return record
            raise ValueError(f"Dream Cycle run_id not found: {run_id}")
        if proposal_path:
            requested = str(Path(proposal_path).expanduser())
            for record in reversed(records):
                if str(record.get("proposal_path") or "") == requested:
                    return record
            raise ValueError(f"Dream Cycle proposal_path not found in audit log: {proposal_path}")
        return records[-1]

    def _safe_note_path(self, note: MemoryNote) -> Path:
        path = Path(note.path).expanduser()
        resolved = path.resolve()
        tree_resolved = self.tree.resolve()
        if not resolved.is_relative_to(tree_resolved):
            raise ValueError(f"refusing to edit note outside readable memory tree: {path}")
        rel_parts = resolved.relative_to(tree_resolved).parts
        if not rel_parts or rel_parts[0] == "reviews" or len(rel_parts) == 1:
            raise ValueError(f"refusing to edit non-note/review file: {path}")
        return path

    def _rewrite_note(self, note: MemoryNote) -> Path:
        old_path = self._safe_note_path(note)
        new_path = self.note_path_for(note)
        note.path = str(new_path)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(note.to_markdown(), encoding="utf-8")
        if old_path != new_path and old_path.exists():
            old_path.unlink()
        return new_path

    @staticmethod
    def _add_tags(note: MemoryNote, *tags: str) -> None:
        for tag in tags:
            if tag and tag not in note.tags:
                note.tags.append(tag)

    @staticmethod
    def _conflict_ids_from_tags(note: MemoryNote) -> list[str]:
        prefix = "conflicts-with-"
        ids: list[str] = []
        for tag in note.tags:
            if not tag.startswith(prefix):
                continue
            note_id = tag[len(prefix):].strip()
            if note_id and note_id not in ids:
                ids.append(note_id)
        return ids

    def resolve_conflict(
        self,
        *,
        note_id: str,
        resolution: str,
        reason: str,
        provenance: str,
        replacement_content: str = "",
        dry_run: bool = True,
        include_sensitive: bool = False,
        actor: str = "agent",
    ) -> dict[str, Any]:
        """Explicitly resolve a conflicting memory note.

        Supported resolutions:
        - accept_candidate: promote the conflicting candidate and supersede active conflicting notes.
        - keep_existing: archive the conflicting candidate and keep existing active notes.
        - merge: create a new active merged note that supersedes both the candidate and existing notes.

        Resolution is intentionally explicit: mutating calls require a reason and
        provenance, write a structured event, and preserve old Markdown as
        superseded/archived history instead of deleting it.
        """
        self.initialize()
        note_id = str(note_id).strip()
        resolution = str(resolution).strip()
        if not note_id:
            raise ValueError("conflict resolution requires note_id")
        if resolution not in {"accept_candidate", "keep_existing", "merge"}:
            raise ValueError("resolution must be one of: accept_candidate, keep_existing, merge")
        if not reason.strip():
            raise ValueError("conflict resolution requires reason")
        if not provenance.strip():
            raise ValueError("conflict resolution requires provenance")
        if resolution == "merge" and not replacement_content.strip():
            raise ValueError("merge resolution requires replacement_content")

        notes_by_id = {note.id: note for note in self.list_notes()}
        candidate = notes_by_id.get(note_id)
        if not candidate:
            raise ValueError(f"conflicting note not found: {note_id}")
        if candidate.status != "conflicting":
            raise ValueError(f"note status is {candidate.status}, expected conflicting")
        involved_notes = [candidate]
        conflict_ids = self._conflict_ids_from_tags(candidate)
        existing_notes = [notes_by_id[conflict_id] for conflict_id in conflict_ids if conflict_id in notes_by_id]
        if not existing_notes:
            raise ValueError("conflicting note has no resolvable conflicts-with-* active notes")
        involved_notes.extend(existing_notes)
        if any(note.sensitivity in {"sensitive", "secret_ref"} for note in involved_notes) and not include_sensitive:
            raise ValueError("sensitive conflict resolution requires include_sensitive=true")

        changed_files: list[str] = []
        applied: list[dict[str, Any]] = []
        generated_at = utc_now_iso()
        event_id = ""
        merged_note: MemoryNote | None = None

        if resolution == "accept_candidate":
            candidate.status = "active"
            candidate.source = candidate.source or "conflict_resolution"
            candidate.source_quality = candidate.source_quality or "manual"
            for existing in existing_notes:
                if existing.id not in candidate.supersedes:
                    candidate.supersedes.append(existing.id)
            self._add_tags(candidate, "conflict-resolved", "accepted-candidate")
            candidate.apply_guardrails()
            if candidate.status != "active":
                raise ValueError("candidate could not be activated; source/provenance required")
            for existing in existing_notes:
                existing.status = "superseded"
                if candidate.id not in existing.superseded_by:
                    existing.superseded_by.append(candidate.id)
                self._add_tags(existing, "conflict-resolved", "superseded-by-candidate")
        elif resolution == "keep_existing":
            candidate.status = "archived"
            for existing in existing_notes:
                if existing.id not in candidate.superseded_by:
                    candidate.superseded_by.append(existing.id)
            self._add_tags(candidate, "conflict-resolved", "kept-existing", "rejected-candidate")
        else:
            merged_note = MemoryNote(
                body=replacement_content.strip(),
                type=candidate.type,
                agent=candidate.agent,
                project=candidate.project,
                scope=candidate.scope,
                status="active",
                confidence="reported",
                importance=candidate.importance,
                sensitivity=candidate.sensitivity,
                tags=["conflict-resolved", "merged-resolution"],
                source="conflict_resolution",
                source_ids=list(candidate.source_ids),
                source_quality="manual",
                supersedes=[candidate.id, *[note.id for note in existing_notes]],
                pinned=candidate.pinned,
                pin_scope=candidate.pin_scope,
            )
            candidate.status = "superseded"
            if merged_note.id not in candidate.superseded_by:
                candidate.superseded_by.append(merged_note.id)
            self._add_tags(candidate, "conflict-resolved", "superseded-by-merge")
            for existing in existing_notes:
                existing.status = "superseded"
                if merged_note.id not in existing.superseded_by:
                    existing.superseded_by.append(merged_note.id)
                self._add_tags(existing, "conflict-resolved", "superseded-by-merge")

        if not dry_run:
            event = self.append_event(
                "conflict_resolved",
                note_ids=[note.id for note in involved_notes] + ([merged_note.id] if merged_note else []),
                source_ids=list(candidate.source_ids),
                payload={
                    "resolution": resolution,
                    "reason": reason,
                    "provenance": provenance,
                    "candidate_id": candidate.id,
                    "conflict_ids": [note.id for note in existing_notes],
                    "merged_note_id": merged_note.id if merged_note else "",
                    "actor": actor,
                },
            )
            event_id = str(event["id"])
            for note in involved_notes:
                if event_id not in note.event_ids:
                    note.event_ids.append(event_id)
            if merged_note and event_id not in merged_note.event_ids:
                merged_note.event_ids.append(event_id)

            if merged_note:
                changed_files.append(str(self.write_note(merged_note)))
            for note in involved_notes:
                before_path = note.path
                new_path = self._rewrite_note(note)
                changed_files.append(str(new_path))
                if before_path != str(new_path):
                    changed_files.append(before_path)
            self.rebuild_index()
            with self.promotion_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "type": "conflict_resolved",
                    "event_id": event_id,
                    "generated_at": generated_at,
                    "actor": actor,
                    "resolution": resolution,
                    "reason": reason,
                    "provenance": provenance,
                    "candidate_id": candidate.id,
                    "conflict_ids": [note.id for note in existing_notes],
                    "merged_note_id": merged_note.id if merged_note else "",
                }, ensure_ascii=False, sort_keys=True) + "\n")
            with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n- {generated_at}: resolved memory conflict {candidate.id} "
                    f"with `{resolution}`. Reason: {reason}\n"
                )
            changed_files.extend([str(self.promotion_log_path), str(self.tree / "changelog.md")])

        for note in involved_notes:
            applied.append({
                "note_id": note.id,
                "status": note.status,
                "path": str(self.note_path_for(note)),
                "supersedes": list(note.supersedes),
                "superseded_by": list(note.superseded_by),
            })
        if merged_note:
            applied.append({
                "note_id": merged_note.id,
                "status": merged_note.status,
                "path": str(self.note_path_for(merged_note)),
                "supersedes": list(merged_note.supersedes),
                "superseded_by": list(merged_note.superseded_by),
            })

        return {
            "dry_run": dry_run,
            "actor": actor,
            "resolution": resolution,
            "reason": reason,
            "provenance": provenance,
            "event_ids": [event_id] if event_id else [],
            "applied": applied,
            "changed_files": sorted(set(changed_files)),
            "generated_at": generated_at,
        }

    def apply_dream_proposal(
        self,
        *,
        run_id: str = "",
        proposal_path: str = "",
        note_ids: list[str] | None = None,
        approve_actions: list[str] | None = None,
        apply_all: bool = False,
        dry_run: bool = True,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Apply explicitly selected safe Dream Cycle proposal actions.

        The default is dry-run. Mutating calls must pass either note_ids or
        apply_all=True, which keeps promotion separate from proposal creation.
        """
        self.initialize()
        audit = self._select_dream_audit(run_id=run_id, proposal_path=proposal_path)
        selected_ids = {str(x) for x in (note_ids or []) if str(x).strip()}
        selected_actions = {str(x) for x in (approve_actions or []) if str(x).strip()}
        if not dry_run and not selected_ids and not apply_all:
            raise ValueError("mutating apply requires note_ids or apply_all=true")

        notes_by_id = {note.id: note for note in self.list_notes()}
        changed_files: list[str] = []
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        event_ids: list[str] = []
        safe_actions = {
            "candidate_for_manual_promotion",
            "propose_archive_duplicate",
            "propose_archive_noise",
        }
        archive_actions = {"propose_archive_duplicate", "propose_archive_noise"}

        for item in list(audit.get("items") or []):
            note_id = str(item.get("note_id") or "")
            action = str(item.get("action") or "")
            if selected_ids and note_id not in selected_ids:
                continue
            if selected_actions and action not in selected_actions:
                continue
            if not apply_all and not selected_ids and dry_run and action not in safe_actions:
                # Dry-run without explicit selection is a preview of applicable items.
                continue
            note = notes_by_id.get(note_id)
            if not note:
                skipped.append({"note_id": note_id, "action": action, "reason": "note not found"})
                continue
            if action not in safe_actions:
                skipped.append({"note_id": note_id, "action": action, "reason": "action is review-only or not supported for automatic apply"})
                continue
            if note.sensitivity in {"sensitive", "secret_ref"} and not include_sensitive:
                skipped.append({"note_id": note_id, "action": action, "reason": "sensitive notes require include_sensitive=true"})
                continue
            before_status = note.status
            before_path = note.path
            if action == "candidate_for_manual_promotion":
                if note.status != "inbox":
                    skipped.append({"note_id": note_id, "action": action, "reason": f"status is {note.status}, expected inbox"})
                    continue
                if not note.has_source:
                    skipped.append({"note_id": note_id, "action": action, "reason": "promotion requires source/provenance"})
                    continue
                note.status = "active"
                self._add_tags(note, "promoted-by-dream-cycle")
            elif action in archive_actions:
                if note.status in {"active", "superseded"}:
                    skipped.append({"note_id": note_id, "action": action, "reason": f"refusing to archive {note.status} note from proposal apply"})
                    continue
                note.status = "archived"
                if action == "propose_archive_duplicate":
                    self._add_tags(note, "archived-by-dream-cycle", "duplicate")
                    duplicate_of = str(item.get("duplicate_of") or "")
                    if duplicate_of and duplicate_of not in note.supersedes:
                        note.supersedes.append(duplicate_of)
                else:
                    self._add_tags(note, "archived-by-dream-cycle", "noise")
            action_event_id = ""
            if not dry_run:
                event = self.append_event(
                    "dream_cycle_action_applied",
                    note_ids=[note_id],
                    source_ids=list(note.source_ids),
                    payload={
                        "run_id": str(audit.get("run_id") or ""),
                        "proposal_path": str(audit.get("proposal_path") or ""),
                        "action": action,
                        "before_status": before_status,
                        "after_status": note.status,
                        "before_path": before_path,
                        "after_path": str(self.note_path_for(note)),
                    },
                )
                action_event_id = str(event["id"])
                event_ids.append(action_event_id)
                if action_event_id not in note.event_ids:
                    note.event_ids.append(action_event_id)
                new_path = self._rewrite_note(note)
                changed_files.append(str(new_path))
                if before_path != str(new_path):
                    changed_files.append(before_path)
            applied.append(
                {
                    "note_id": note_id,
                    "action": action,
                    "before_status": before_status,
                    "after_status": note.status,
                    "before_path": before_path,
                    "after_path": str(self.note_path_for(note)),
                    "dry_run": dry_run,
                    "event_ids": [action_event_id] if action_event_id else [],
                }
            )

        generated_at = utc_now_iso()
        result = {
            "run_id": str(audit.get("run_id") or ""),
            "proposal_path": str(audit.get("proposal_path") or ""),
            "dry_run": dry_run,
            "applied": applied,
            "skipped": skipped,
            "event_ids": event_ids,
            "changed_files": sorted(set(changed_files)),
            "generated_at": generated_at,
        }
        if not dry_run:
            self.rebuild_index()
            with self.promotion_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n- {generated_at}: applied Dream Cycle proposal {result['run_id']} "
                    f"({len(applied)} applied, {len(skipped)} skipped).\n"
                )
            result["changed_files"].extend([str(self.promotion_log_path), str(self.tree / "changelog.md")])
            result["changed_files"] = sorted(set(result["changed_files"]))
        return result

    def activate_notes(
        self,
        *,
        note_ids: list[str],
        reason: str,
        provenance: str,
        source: str = "",
        source_ids: list[str] | None = None,
        source_quality: str = "manual",
        dry_run: bool = True,
        include_sensitive: bool = False,
        actor: str = "agent",
    ) -> dict[str, Any]:
        """Explicitly activate selected review notes with provenance and audit.

        This is the direct promotion path separate from Dream Cycle proposals.
        It requires explicit note ids, a human/agent-readable reason, and
        provenance. Mutation defaults to dry-run and writes an audit log when
        applied.
        """
        self.initialize()
        selected_ids = [str(note_id).strip() for note_id in note_ids if str(note_id).strip()]
        if not selected_ids:
            raise ValueError("activation requires note_ids")
        if not reason.strip():
            raise ValueError("activation requires reason")
        if not provenance.strip():
            raise ValueError("activation requires provenance")

        notes_by_id = {note.id: note for note in self.list_notes()}
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        changed_files: list[str] = []
        generated_at = utc_now_iso()
        normalized_source_ids = [str(value).strip() for value in (source_ids or []) if str(value).strip()]
        normalized_quality = source_quality.strip() or "manual"

        for note_id in selected_ids:
            note = notes_by_id.get(note_id)
            if not note:
                skipped.append({"note_id": note_id, "reason": "note not found"})
                continue
            before_status = note.status
            before_path = note.path
            if note.status not in {"inbox", "needs_confirmation", "uncertain"}:
                skipped.append({"note_id": note_id, "reason": f"status is {note.status}, expected inbox/needs_confirmation/uncertain"})
                continue
            if note.type == "open_loop" or note.status == "open_loop":
                skipped.append({"note_id": note_id, "reason": "open_loop notes require fresh task confirmation, not activation into active memory"})
                continue
            if note.sensitivity in {"sensitive", "secret_ref"} and not include_sensitive:
                skipped.append({"note_id": note_id, "reason": "sensitive notes require include_sensitive=true"})
                continue

            if not note.source and source:
                note.source = source
            elif not note.source:
                note.source = "explicit_activation"
            for source_id in normalized_source_ids:
                if source_id not in note.source_ids:
                    note.source_ids.append(source_id)
            if not note.source_quality:
                note.source_quality = normalized_quality
            allowed, lifecycle_reason = can_activate(note)
            if not allowed:
                skipped.append({"note_id": note_id, "reason": lifecycle_reason})
                continue
            note.status = "active"
            self._add_tags(note, "activated", "promoted-by-explicit-activation")
            note.apply_guardrails()
            if note.status != "active":
                skipped.append({"note_id": note_id, "reason": "activation failed guardrails; provenance/source required"})
                continue

            activation_event_id = ""
            after_path = str(self.note_path_for(note))
            if not dry_run:
                event = self.append_event(
                    "memory_note_activated",
                    note_ids=[note_id],
                    source_ids=list(note.source_ids),
                    payload={
                        "reason": reason,
                        "provenance": provenance,
                        "before_status": before_status,
                        "after_status": note.status,
                    },
                )
                activation_event_id = str(event["id"])
                if activation_event_id not in note.event_ids:
                    note.event_ids.append(activation_event_id)
                new_path = self._rewrite_note(note)
                changed_files.append(str(new_path))
                if before_path != str(new_path):
                    changed_files.append(before_path)
            applied.append(
                {
                    "note_id": note_id,
                    "before_status": before_status,
                    "after_status": note.status,
                    "before_path": before_path,
                    "after_path": after_path,
                    "reason": reason,
                    "provenance": provenance,
                    "source": note.source,
                    "source_ids": list(note.source_ids),
                    "source_quality": note.source_quality,
                    "event_ids": [activation_event_id] if activation_event_id else [],
                    "dry_run": dry_run,
                }
            )

        result = {
            "dry_run": dry_run,
            "actor": actor,
            "reason": reason,
            "provenance": provenance,
            "applied": applied,
            "skipped": skipped,
            "changed_files": sorted(set(changed_files)),
            "generated_at": generated_at,
        }
        if not dry_run:
            self.rebuild_index()
            with self.activation_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n- {generated_at}: explicit activation "
                    f"({len(applied)} applied, {len(skipped)} skipped). Reason: {reason}\n"
                )
            result["changed_files"].extend([str(self.activation_log_path), str(self.tree / "changelog.md")])
            result["changed_files"] = sorted(set(result["changed_files"]))
        return result

    def retire_notes(
        self,
        *,
        note_ids: list[str],
        reason: str,
        dry_run: bool = True,
        include_sensitive: bool = False,
        allow_active: bool = False,
        actor: str = "agent",
    ) -> dict[str, Any]:
        """Explicitly remove selected notes from default recall with audit.

        Retirement is reversible in the readable tree because it moves notes to
        archived status instead of deleting Markdown. Active notes require an
        explicit allow_active flag so ordinary cleanup cannot silently forget
        promoted memory.
        """
        self.initialize()
        selected_ids = [str(note_id).strip() for note_id in note_ids if str(note_id).strip()]
        if not selected_ids:
            raise ValueError("retirement requires note_ids")
        if not reason.strip():
            raise ValueError("retirement requires reason")

        notes_by_id = {note.id: note for note in self.list_notes()}
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        changed_files: list[str] = []
        generated_at = utc_now_iso()

        for note_id in selected_ids:
            note = notes_by_id.get(note_id)
            if not note:
                skipped.append({"note_id": note_id, "reason": "note not found"})
                continue
            before_status = note.status
            before_path = note.path
            if note.status in {"archived", "superseded"}:
                skipped.append({"note_id": note_id, "reason": f"status is already {note.status}"})
                continue
            if note.status == "active" and not allow_active:
                skipped.append({"note_id": note_id, "reason": "active notes require allow_active=true for retirement"})
                continue
            if note.sensitivity in {"sensitive", "secret_ref"} and not include_sensitive:
                skipped.append({"note_id": note_id, "reason": "sensitive notes require include_sensitive=true"})
                continue

            note.status = "archived"
            self._add_tags(note, "retired", "retired-by-explicit-retirement")
            retirement_event_id = ""
            after_path = str(self.note_path_for(note))
            if not dry_run:
                event = self.append_event(
                    "memory_note_retired",
                    note_ids=[note_id],
                    source_ids=list(note.source_ids),
                    payload={
                        "reason": reason,
                        "before_status": before_status,
                        "after_status": note.status,
                    },
                )
                retirement_event_id = str(event["id"])
                if retirement_event_id not in note.event_ids:
                    note.event_ids.append(retirement_event_id)
                new_path = self._rewrite_note(note)
                changed_files.append(str(new_path))
                if before_path != str(new_path):
                    changed_files.append(before_path)
            applied.append(
                {
                    "note_id": note_id,
                    "before_status": before_status,
                    "after_status": note.status,
                    "before_path": before_path,
                    "after_path": after_path,
                    "reason": reason,
                    "event_ids": [retirement_event_id] if retirement_event_id else [],
                    "dry_run": dry_run,
                }
            )

        result = {
            "dry_run": dry_run,
            "actor": actor,
            "reason": reason,
            "applied": applied,
            "skipped": skipped,
            "changed_files": sorted(set(changed_files)),
            "generated_at": generated_at,
        }
        if not dry_run:
            self.rebuild_index()
            with self.retirement_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            with (self.tree / "changelog.md").open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n- {generated_at}: explicit retirement "
                    f"({len(applied)} applied, {len(skipped)} skipped). Reason: {reason}\n"
                )
            result["changed_files"].extend([str(self.retirement_log_path), str(self.tree / "changelog.md")])
            result["changed_files"] = sorted(set(result["changed_files"]))
        return result

    def status(self) -> dict[str, Any]:
        notes = self.list_notes()
        counts: dict[str, int] = {}
        for note in notes:
            counts[note.status] = counts.get(note.status, 0) + 1
        return {
            "root": str(self.root),
            "agent": self.agent,
            "notes": len(notes),
            "raw_turns": len(self.iter_raw_turns()),
            "events": len(self.iter_events()),
            "retrieval_logs": len(self.iter_retrieval_logs()),
            "status_counts": counts,
        }
