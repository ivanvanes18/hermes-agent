"""Deterministic candidate extraction for readable_tree memory."""

from __future__ import annotations

import re
from typing import Any

from .schemas import MemoryNote

EXTRACTOR_VERSION = "regex-v2"

_EXPLICIT_RE = re.compile(
    r"\b(remember this|do not forget|don't forget|важно|запомни|не забудь|по умолчанию|always|never)\b",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(r"\b(decided|we decided|решили|выбрали|final verdict|вердикт)\b", re.IGNORECASE)
_REQUIREMENT_RE = re.compile(r"\b(requirement|requires?|must|требование|нужно|надо|должен|должна|должно)\b", re.IGNORECASE)
_CONSTRAINT_RE = re.compile(r"\b(should not|нельзя|обязательно|constraint|ограничение)\b", re.IGNORECASE)
_RISK_RE = re.compile(r"\b(risk|опасность|риск|может сломать|опасно)\b", re.IGNORECASE)
_CORRECTION_RE = re.compile(r"\b(correction|исправление|ошибка|ты должна|ты должен|надо было|следовало)\b", re.IGNORECASE)
_ARTIFACT_RE = re.compile(r"\b(artifact|артефакт|file|path|doc|document|файл|документ)\b|[\w./-]+\.(?:md|py|json|yaml|yml|toml|txt)\b", re.IGNORECASE)
_FUTURE_INTENT_RE = re.compile(
    r"\b("
    r"future intent|open[- ]loop|someday|later|finish later|return to|"
    r"вернуться|потом|позже|когда-нибудь|отложили|не закончили|"
    r"надо будет|будет нужно|сделаем позже|следующий шаг потом|будущий шаг"
    r")\b",
    re.IGNORECASE,
)
_UNFINISHED_RE = re.compile(r"\b(todo|next step|следующий шаг)\b", re.IGNORECASE)
_MEASUREMENT_RE = re.compile(r"\b\d+(?:[\.,]\d+)?\s?(kg|кг|km|км|bpm|%|hours|час)\b", re.IGNORECASE)
_SECRET_MARKER_RE = re.compile(r"\b(api[_ -]?key|token|secret|password|passwd|pwd|bearer|пароль|секрет)\b", re.IGNORECASE)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!turn-)(?<!evt-)(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_TOKEN_VALUE_RE = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"
)
_CONTEXT_ECHO_RE = re.compile(
    r"\b(Readable Tree Memory|Recalled memory evidence|source-backed data|memory-context|source_ids:|body_quote|path:)\b",
    re.IGNORECASE,
)


def _note_type(text: str) -> str:
    if _CORRECTION_RE.search(text):
        return "correction"
    if _ARTIFACT_RE.search(text):
        return "artifact"
    if _FUTURE_INTENT_RE.search(text):
        return "open_loop"
    if _DECISION_RE.search(text):
        return "decision"
    if _CONSTRAINT_RE.search(text):
        return "constraint"
    if _REQUIREMENT_RE.search(text):
        return "requirement"
    if _RISK_RE.search(text):
        return "risk"
    if _UNFINISHED_RE.search(text):
        return "open_loop"
    if _MEASUREMENT_RE.search(text):
        return "measurement"
    if _EXPLICIT_RE.search(text):
        return "fact"
    return "fact"


def _importance(text: str, note_type: str) -> str:
    if note_type in {"correction", "behavior_rule_seed", "regression_case_seed", "risk"}:
        return "high"
    if note_type in {"open_loop", "artifact", "requirement"}:
        return "medium"
    if _EXPLICIT_RE.search(text) or note_type in {"decision", "constraint", "measurement"}:
        return "high"
    return "low"


def classify_sensitivity(text: str) -> str:
    """Deterministically classify sensitive text before note write/indexing."""
    if _PRIVATE_KEY_RE.search(text) or _TOKEN_VALUE_RE.search(text):
        return "secret_ref"
    if _SECRET_MARKER_RE.search(text):
        return "secret_ref"
    if _EMAIL_RE.search(text) or _PHONE_RE.search(text):
        return "sensitive"
    return "internal"


def redact_sensitive_text(text: str) -> str:
    """Return storage-safe text with direct secrets/PII replaced by placeholders."""
    redacted = _PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", text)
    redacted = _TOKEN_VALUE_RE.sub("[REDACTED_SECRET_TOKEN]", redacted)
    redacted = re.sub(
        r"(?i)(\b(?:api[_ -]?key|token|secret|password|passwd|pwd|bearer|пароль|секрет)\b\s*[:=]?\s*)(\S+)",
        r"\1[REDACTED_SECRET_VALUE]",
        redacted,
    )
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted


def _sensitivity(text: str) -> str:
    return classify_sensitivity(text)


def _candidate_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip(" -\t")
        if not line or len(line) < 8:
            continue
        if _CONTEXT_ECHO_RE.search(line):
            continue
        if any(rx.search(line) for rx in (_EXPLICIT_RE, _DECISION_RE, _REQUIREMENT_RE, _CONSTRAINT_RE, _RISK_RE, _CORRECTION_RE, _ARTIFACT_RE, _FUTURE_INTENT_RE, _UNFINISHED_RE, _MEASUREMENT_RE)):
            lines.append(line[:800])
    return lines


def extract_candidates(
    raw_record: dict[str, Any],
    *,
    agent: str = "default",
    project: str = "",
) -> list[MemoryNote]:
    """Extract reviewable notes from a raw turn record.

    This is deliberately deterministic in v1: it errs toward inbox capture while
    avoiding LLM-based autonomous promotion.
    """

    source_id = str(raw_record.get("id") or raw_record.get("session_id") or "")
    observed_at = str(raw_record.get("timestamp") or "")
    # Extract durable candidates from the user's side of the turn only. The
    # assistant often says things like "verdict", "next step", or "must" while
    # managing the current task; treating those as long-term memory creates a
    # self-feeding inbox during memory maintenance sessions.
    text = str(raw_record.get("user") or "")
    notes: list[MemoryNote] = []
    seen: set[str] = set()

    for line in _candidate_lines(text):
        if line in seen:
            continue
        seen.add(line)
        note_type = _note_type(line)
        importance = _importance(line, note_type)
        sensitivity = _sensitivity(line)
        storage_body = redact_sensitive_text(line) if sensitivity in {"sensitive", "secret_ref"} else line
        if note_type == "open_loop":
            status = "open_loop"
        else:
            status = "needs_review" if note_type in {"correction", "behavior_rule_seed", "regression_case_seed", "risk"} or importance == "high" else "inbox"
        confidence = "reported" if any(rx.search(line) for rx in (_EXPLICIT_RE, _DECISION_RE, _REQUIREMENT_RE, _CONSTRAINT_RE, _CORRECTION_RE, _ARTIFACT_RE)) else "uncertain"
        tags = ["auto-extracted", "inbox"]
        if note_type == "open_loop":
            tags.extend(["future-intent", "not-current-instruction"])
        note = MemoryNote(
            type=note_type,
            agent=agent,
            project=project,
            scope=note_type if note_type != "fact" else "general",
            status=status,
            observed_at=observed_at,
            confidence=confidence,
            importance=importance,
            sensitivity=sensitivity,
            tags=tags,
            source="raw_turn",
            source_ids=[source_id] if source_id else [],
            source_quality="session",
            body=storage_body,
        )
        notes.append(note)
    return notes
