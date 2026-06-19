"""Deterministic session summary cache for readable_tree memory.

This module deliberately avoids LLM calls. It builds a reviewable skeleton from
raw turns so later review/extraction can work from a bounded derived artifact
while the raw turns remain the evidence source.
"""

from __future__ import annotations

from typing import Any

from .schemas import MemoryNote


def _clip(value: str, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _bullet_lines(values: list[str]) -> str:
    if not values:
        return "- (needs review)"
    return "\n".join(f"- {value}" for value in values)


def build_session_summary(raw_turns: list[dict[str, Any]]) -> MemoryNote:
    """Build a reviewable deterministic session summary note from raw turns."""
    turns = [turn for turn in raw_turns if isinstance(turn, dict)]
    session_id = str(turns[0].get("session_id") or "") if turns else ""
    source_ids = [str(turn.get("id") or "") for turn in turns if str(turn.get("id") or "").strip()]
    user_lines = [_clip(str(turn.get("user") or "")) for turn in turns if str(turn.get("user") or "").strip()]
    assistant_lines = [_clip(str(turn.get("assistant") or "")) for turn in turns if str(turn.get("assistant") or "").strip()]
    goal = user_lines[0] if user_lines else "(needs review)"
    body = (
        "# Session summary\n"
        f"session_id: {session_id}\n"
        f"goal: {goal}\n"
        "decisions:\n"
        f"{_bullet_lines([])}\n"
        "requirements:\n"
        f"{_bullet_lines(user_lines[1:])}\n"
        "corrections:\n"
        f"{_bullet_lines([])}\n"
        "artifacts:\n"
        f"{_bullet_lines(assistant_lines)}\n"
        "open_questions:\n"
        f"{_bullet_lines([])}\n"
        f"source_turn_ids: {', '.join(source_ids)}"
    )
    return MemoryNote(
        body=body,
        type="session_summary",
        status="needs_review",
        confidence="derived",
        importance="medium",
        sensitivity="internal",
        tags=["derived-cache", "session-summary"],
        source="session_summary",
        source_ids=source_ids,
        source_quality="session",
    )
