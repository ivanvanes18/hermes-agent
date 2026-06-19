"""Deterministic behavioral regression case parsing and evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass(frozen=True)
class RegressionCase:
    mistake_class: str = "unknown"
    input_pattern: str = ""
    expected_behavior: str = ""
    fail_signals: list[str] | None = None
    source_correction: str = ""
    linked_rule_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fail_signals"] = list(self.fail_signals or [])
        return data


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-zа-яё_]{4,}", text.casefold())}


def _field(body: str, name: str) -> str:
    pattern = rf"^{re.escape(name)}:\s*(.+)$"
    for line in str(body or "").splitlines():
        match = re.match(pattern, line.strip(), re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _split_list(value: str) -> list[str]:
    if not value.strip():
        return []
    parts = re.split(r"\s*(?:;|\|)\s*", value.strip())
    return [part.strip() for part in parts if part.strip()]


def parse_regression_case(body: str) -> RegressionCase:
    """Parse the deterministic regression case frontmatter-like body format."""
    return RegressionCase(
        mistake_class=_field(body, "mistake_class") or "unknown",
        input_pattern=_field(body, "input_pattern"),
        expected_behavior=_field(body, "expected_behavior"),
        fail_signals=_split_list(_field(body, "fail_signals")),
        source_correction=_field(body, "source_correction"),
        linked_rule_id=_field(body, "linked_rule_id"),
    )


def build_regression_report(notes: list[Any], *, limit: int = 50, dry_run: bool = True) -> dict[str, Any]:
    """Build a deterministic report for active regression cases needing review.

    The report is intentionally non-mutating and never calls an LLM. Outcome
    reviews link to cases through tags like ``case:<case_id>`` or by mentioning
    the case id in their body.
    """
    note_list = list(notes)
    reviewed_case_ids: set[str] = set()
    for note in note_list:
        if getattr(note, "type", "") != "outcome_review":
            continue
        body = str(getattr(note, "body", "") or "")
        tags = [str(tag) for tag in (getattr(note, "tags", []) or [])]
        for tag in tags:
            if tag.startswith("case:"):
                reviewed_case_ids.add(tag.removeprefix("case:"))
        for candidate in note_list:
            candidate_id = str(getattr(candidate, "id", "") or "")
            if candidate_id and candidate_id in body:
                reviewed_case_ids.add(candidate_id)

    active_cases = [
        note for note in note_list
        if getattr(note, "type", "") == "regression_case" and getattr(note, "status", "") == "active"
    ]
    active_cases.sort(key=lambda note: str(getattr(note, "observed_at", "") or ""), reverse=True)
    unreviewed: list[dict[str, Any]] = []
    for note in active_cases:
        case_id = str(getattr(note, "id", "") or "")
        if case_id in reviewed_case_ids:
            continue
        parsed = parse_regression_case(str(getattr(note, "body", "") or ""))
        unreviewed.append({
            "case_id": case_id,
            "path": str(getattr(note, "path", "") or ""),
            "status": str(getattr(note, "status", "") or ""),
            "case": parsed.to_dict(),
        })
        if len(unreviewed) >= max(1, int(limit)):
            break

    return {
        "dry_run": dry_run,
        "llm_used": False,
        "changed_files": [],
        "scanned_cases": len(active_cases),
        "reviewed_case_ids": sorted(reviewed_case_ids),
        "unreviewed_cases": unreviewed,
        "count": len(unreviewed),
    }


def evaluate_regression_case(case_body: str, observed_behavior: str) -> dict[str, Any]:
    """Evaluate whether observed behavior satisfies a regression case.

    This is a conservative deterministic check. It is not a judge of quality; it
    catches obvious repeats and obvious fixes so Dream Cycle can surface cases for
    human review.
    """
    case = parse_regression_case(case_body)
    observed_terms = _terms(observed_behavior)
    fail_terms = set().union(*(_terms(signal) for signal in (case.fail_signals or []))) if case.fail_signals else set()
    expected_terms = _terms(case.expected_behavior)

    matched_fail_terms = sorted(observed_terms & fail_terms)
    if matched_fail_terms and not {"check", "checking", "checked", "pytest", "провер", "pending"} & observed_terms:
        return {"verdict": "failed", "matched_fail_signal": matched_fail_terms[0], "case": case.to_dict()}

    expected_hits = sorted(observed_terms & expected_terms)
    if expected_hits:
        return {"verdict": "passed", "matched_expected_term": expected_hits[0], "case": case.to_dict()}

    return {"verdict": "unclear", "reason": "no deterministic expected or fail signal match", "case": case.to_dict()}
