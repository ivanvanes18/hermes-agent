"""Behavioral learning helpers for readable_tree memory.

The helpers are deterministic by design. They create source-backed Markdown
notes that make user corrections operational: future preflight can retrieve a
behavior rule and regression cases can prove whether behavior changed.
"""

from __future__ import annotations

import re

from .schemas import MISTAKE_CLASSES, MemoryNote

_WRONG_TASK_LAYER_RE = re.compile(
    r"(файл|архитектур|baseline|слой|pending|обещан|созда(ть|ла)|должна была|wrong task layer)",
    re.IGNORECASE,
)
_FAILED_CHECK_RE = re.compile(
    r"(не проверил|не проверила|без проверки|claimed without check|говоришь готово)",
    re.IGNORECASE,
)
_SKILL_MISS_RE = re.compile(
    r"(скилл|skill|superpower|не использовал|не использовала)",
    re.IGNORECASE,
)
_STYLE_RE = re.compile(r"(слишком длинно|зеркалинг|канцелярит|не по-русски|тон)", re.IGNORECASE)
_ASK_ACT_RE = re.compile(r"(зачем спрашиваешь|надо было действовать|asked when should act)", re.IGNORECASE)
_ACT_ASK_RE = re.compile(r"(надо было уточнить|не спросила|acted when should ask)", re.IGNORECASE)


def classify_mistake(text: str) -> str:
    """Classify correction text into the Master Memory Architecture taxonomy."""
    normalized = str(text or "")
    if _WRONG_TASK_LAYER_RE.search(normalized):
        return "wrong_task_layer"
    if _FAILED_CHECK_RE.search(normalized):
        return "claimed_without_check"
    if _SKILL_MISS_RE.search(normalized):
        return "failed_to_use_skill"
    if _STYLE_RE.search(normalized):
        return "style_regression"
    if _ASK_ACT_RE.search(normalized):
        return "asked_when_should_act"
    if _ACT_ASK_RE.search(normalized):
        return "acted_when_should_ask"
    return "unknown"


def trigger_terms_for_mistake(mistake_class: str) -> list[str]:
    """Return search terms used by preflight to retrieve behavior rules."""
    mapping = {
        "wrong_task_layer": ["promised file", "pending artifact", "baseline", "architecture", "check pending files"],
        "claimed_without_check": ["verify before done", "evidence", "checked", "готово", "проверила"],
        "failed_to_use_skill": ["skill", "superpower", "load skill", "use skill"],
        "style_regression": ["tone", "concise", "Russian", "style", "зеркалинг"],
        "asked_when_should_act": ["act without asking", "obvious default", "действуй"],
        "acted_when_should_ask": ["ask clarification", "risk", "privacy", "irreversible"],
        "unknown": ["correction", "behavior rule", "regression"],
    }
    return mapping.get(mistake_class, mapping["unknown"])


def _behavior_rule_body(correction_text: str, mistake_class: str) -> str:
    if mistake_class == "wrong_task_layer":
        return (
            "Behavior rule: when Ivan references a recently promised file, architecture, plan, or says "
            "the artifact should already exist, first check pending files/session state and create or locate "
            "the missing artifact before analyzing an older baseline. Trigger terms: promised file, pending "
            "artifact, baseline, architecture, check pending files. Source correction: "
            f"{correction_text}"
        )
    if mistake_class == "claimed_without_check":
        return (
            "Behavior rule: do not claim work is complete without fresh verification evidence from tools. "
            "If verification was not run, say exactly what remains unchecked. Source correction: "
            f"{correction_text}"
        )
    if mistake_class == "failed_to_use_skill":
        return (
            "Behavior rule: before answering tasks with matching skills, load the relevant skill and follow "
            "its workflow before producing the final answer. Source correction: "
            f"{correction_text}"
        )
    return (
        "Behavior rule: convert this correction into a future preflight check before similar tasks. "
        f"Mistake class: {mistake_class}. Source correction: {correction_text}"
    )


def _regression_case_body(correction_text: str, mistake_class: str) -> str:
    return (
        "Regression case:\n"
        f"mistake_class: {mistake_class}\n"
        f"input_pattern: {', '.join(trigger_terms_for_mistake(mistake_class))}\n"
        "expected_behavior: retrieve the matching behavior rule during preflight, apply it before the final answer, "
        "and state verification evidence when the task outcome depends on tools.\n"
        "fail_signals: answers from memory only; analyzes old baseline before checking pending artifacts; claims done without evidence.\n"
        f"source_correction: {correction_text}"
    )


def build_behavioral_chain(
    correction_text: str,
    *,
    agent: str,
    project: str = "",
    source_id: str = "",
    session_id: str = "",
) -> list[MemoryNote]:
    """Build linked correction, behavior_rule, and regression_case notes."""
    mistake_class = classify_mistake(correction_text)
    if mistake_class not in MISTAKE_CLASSES:
        mistake_class = "unknown"
    source_ids = [source_id] if source_id else []
    tags = ["behavioral-memory", f"mistake:{mistake_class}"]
    common = {
        "agent": agent,
        "project": project,
        "source": "correction_event",
        "source_ids": source_ids,
        "source_quality": "session" if source_ids else "manual",
    }
    correction = MemoryNote(
        type="correction",
        scope="behavioral_learning",
        status="active",
        confidence="reported",
        importance="high",
        sensitivity="internal",
        tags=[*tags, "correction-event"],
        body=f"Correction event: {correction_text}",
        **common,
    )
    rule = MemoryNote(
        type="behavior_rule",
        scope="behavioral_learning",
        status="active",
        confidence="reported",
        importance="high",
        sensitivity="internal",
        tags=[*tags, "preflight-rule", *[f"trigger:{term}" for term in trigger_terms_for_mistake(mistake_class)]],
        body=_behavior_rule_body(correction_text, mistake_class),
        **common,
    )
    regression = MemoryNote(
        type="regression_case",
        scope="behavioral_learning",
        status="active",
        confidence="reported",
        importance="high",
        sensitivity="internal",
        tags=[*tags, "regression-case"],
        body=_regression_case_body(correction_text, mistake_class),
        **common,
    )
    return [correction, rule, regression]
