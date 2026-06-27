"""Deterministic closure evaluator for readable_tree memory.

The evaluator is intentionally small and local. It does not decide truth; it
runs the live provider prefetch path against fixture cases and reports whether
Context Pack routing, contamination filters, pack budgets, and behavior
preflight traces match the Human2/readable_tree contract.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .routing import resolve_branch


def _json_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in re.findall(r"```json\n(.*?)\n```", text or "", flags=re.S):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks


def _split_prefetch_blocks(context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    behavior: dict[str, Any] = {}
    pack: dict[str, Any] = {}
    for block in _json_blocks(context):
        version = str(block.get("version") or "")
        if version == "readable_tree_behavior_preflight_v1":
            behavior = block
        elif version.startswith("readable_tree_context_pack"):
            pack = block
    return behavior, pack


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _case_report(provider: Any, case: dict[str, Any]) -> dict[str, Any]:
    query = str(case.get("query") or "")
    context = provider.prefetch(query, session_id="memory-closure-eval")
    behavior, pack = _split_prefetch_blocks(context)
    fallback_routing = resolve_branch(query, configured_project=getattr(provider, "_project", "")).to_dict()
    routing_raw = pack.get("routing_decision") if pack else None
    routing = routing_raw if isinstance(routing_raw, dict) else fallback_routing
    source_ids = _as_list(pack.get("source_ids")) if pack else []
    included_items = list(pack.get("included_items") or []) if pack else []
    excluded_items = list(pack.get("excluded_items") or []) if pack else []
    preflight_trace = list(behavior.get("preflight_trace") or []) if behavior else []
    contamination_failures = [
        source_id for source_id in _as_list(case.get("forbidden_source_ids"))
        if source_id in source_ids
    ]
    expected_sources_missing = [
        source_id for source_id in _as_list(case.get("expected_source_ids"))
        if source_id not in source_ids
    ]
    max_pack_chars = int(case.get("max_pack_chars") or 0)
    pack_chars = len(context or "")
    branch_ok = not case.get("expected_branch") or routing.get("branch") == case.get("expected_branch")
    clarification_ok = (
        "clarification_required" not in case
        or bool(routing.get("clarification_required")) is bool(case.get("clarification_required"))
    )
    behavior_rule_fired = any(bool(item.get("rule_fired")) for item in preflight_trace)
    behavior_ok = not case.get("expect_behavior_rule_fired") or behavior_rule_fired
    budget_ok = not max_pack_chars or pack_chars <= max_pack_chars
    passed = all([
        branch_ok,
        clarification_ok,
        not contamination_failures,
        not expected_sources_missing,
        behavior_ok,
        budget_ok,
    ])
    return {
        "name": str(case.get("name") or query),
        "query": query,
        "expected_branch": case.get("expected_branch"),
        "actual_branch": routing.get("branch"),
        "clarification_required": bool(routing.get("clarification_required")),
        "included_ids": [str(item.get("note_id") or "") for item in included_items],
        "excluded_ids": [str(item.get("note_id") or "") for item in excluded_items],
        "source_ids": source_ids,
        "expected_sources_missing": expected_sources_missing,
        "contamination_failures": contamination_failures,
        "pack_chars": pack_chars,
        "max_pack_chars": max_pack_chars,
        "behavior_rule_fired": behavior_rule_fired,
        "preflight_rule_ids": [str(item.get("rule_id") or "") for item in preflight_trace],
        "branch_ok": branch_ok,
        "clarification_ok": clarification_ok,
        "behavior_ok": behavior_ok,
        "budget_ok": budget_ok,
        "passed": passed,
    }


def run_memory_closure_eval(provider: Any, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Run deterministic Human2/readable_tree closure checks against a provider."""
    reports = [_case_report(provider, case) for case in cases]
    contamination_count = sum(len(report["contamination_failures"]) for report in reports)
    passed_count = sum(1 for report in reports if report["passed"])
    behavior_rules_fired = sum(1 for report in reports if report["behavior_rule_fired"])
    summary = {
        "cases_total": len(reports),
        "cases_passed": passed_count,
        "cases_failed": len(reports) - passed_count,
        "contamination_failures": contamination_count,
        "behavior_rules_fired": behavior_rules_fired,
        "max_pack_chars_observed": max([report["pack_chars"] for report in reports], default=0),
    }
    return {
        "version": "readable_tree_memory_closure_eval_v1",
        "overall_pass": passed_count == len(reports) and contamination_count == 0,
        "summary": summary,
        "cases": reports,
    }
