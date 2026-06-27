from __future__ import annotations

import json
import re
from pathlib import Path

from plugins.memory.readable_tree import ReadableTreeMemoryProvider
from plugins.memory.readable_tree.context_pack import build_context_pack
from plugins.memory.readable_tree.routing import resolve_branch
from plugins.memory.readable_tree.schemas import MemoryNote
from plugins.memory.readable_tree.store import ReadableMemoryStore


def _pack_json(rendered: str) -> dict:
    blocks = _json_blocks(rendered)
    assert blocks, rendered
    return blocks[-1]


def _json_blocks(rendered: str) -> list[dict]:
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", rendered, flags=re.S)]


def test_context_pack_contract_records_inclusions_exclusions_and_budget():
    active = {
        "id": "active-1",
        "status": "active",
        "type": "decision",
        "importance": "high",
        "sensitivity": "internal",
        "scope": "memory",
        "project": "hermes-agent",
        "source_ids": "source-1",
        "event_ids": "evt-1",
        "source_quality": "direct",
        "body": "Context Pack must be bounded, source-backed, and project-scoped.",
    }
    archived = {
        "id": "archived-1",
        "status": "archived",
        "type": "decision",
        "importance": "high",
        "sensitivity": "internal",
        "scope": "trading",
        "project": "trading",
        "source_ids": "source-2",
        "event_ids": "evt-2",
        "source_quality": "direct",
        "body": "Old archived trading baseline must not become current context.",
    }

    pack = _pack_json(build_context_pack(
        "memory Context Pack",
        [active, archived],
        max_chars=5000,
        routing_decision=resolve_branch("Hermes memory Context Pack").to_dict(),
    ))

    assert pack["contract"]["schema_version"] == "context_pack_contract_v1"
    assert pack["routing_decision"]["branch"] == "hermes-agent"
    assert pack["included_items"] == [{
        "note_id": "active-1",
        "authority": "decision",
        "scope": "memory",
        "project": "hermes-agent",
        "source_ids": ["source-1"],
        "event_ids": ["evt-1"],
        "why_included": "ranked_candidate_with_safe_status_and_scope",
    }]
    assert pack["excluded_items"][0]["note_id"] == "archived-1"
    assert pack["excluded_items"][0]["reason"] == "archived"
    assert pack["char_budget"]["max_chars"] == 5000


def test_branch_resolver_does_not_fallback_to_main_when_unknown_or_ambiguous():
    unknown = resolve_branch("как это делали раньше")
    assert unknown.branch == "unknown"
    assert unknown.clarification_required is True

    ambiguous = resolve_branch("связать trading bot и ВОР импорт")
    assert ambiguous.branch == "ambiguous"
    assert ambiguous.clarification_required is True


def test_prefetch_routes_hermes_memory_query_to_hermes_project_without_main_contamination(tmp_path):
    provider = ReadableTreeMemoryProvider({
        "retrieval_engine_v2": True,
        "behavior_preflight": False,
        "max_prefetch_notes": 5,
        "max_prefetch_chars": 5000,
    })
    provider.initialize("s1", hermes_home=str(tmp_path), agent_identity="reyna")
    assert provider._store is not None
    hermes_note = MemoryNote(
        body="Hermes memory Context Pack Contract is the next executable slice.",
        type="decision",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        sensitivity="internal",
        importance="high",
        source="test",
        source_ids=["hermes-source"],
        source_quality="direct",
    )
    trading_note = MemoryNote(
        body="Trading bot archived baseline is lexically tempting but wrong for memory architecture.",
        type="decision",
        agent="reyna",
        project="trading",
        scope="trading",
        status="active",
        sensitivity="internal",
        importance="high",
        source="test",
        source_ids=["trading-source"],
        source_quality="direct",
    )
    provider._store.write_note(hermes_note)
    provider._store.write_note(trading_note)
    provider._store.rebuild_index()

    pack = _pack_json(provider.prefetch("Hermes memory Context Pack Contract", session_id="s1"))

    assert pack["routing_decision"]["branch"] == "hermes-agent"
    assert [item["note_id"] for item in pack["included_items"]] == [hermes_note.id]
    assert "trading-source" not in pack["source_ids"]


def test_context_pack_contract_matches_schema_fixture():
    schema = json.loads(Path("tests/fixtures/readable_tree_context_pack_contract.schema.json").read_text(encoding="utf-8"))
    row = {
        "id": "note-schema",
        "status": "active",
        "type": "decision",
        "importance": "high",
        "sensitivity": "internal",
        "scope": "memory",
        "project": "hermes-agent",
        "source_ids": "source-schema",
        "event_ids": "evt-schema",
        "source_quality": "direct",
        "body": "Schema fixture proves the contract has a stable review surface.",
    }

    pack = _pack_json(build_context_pack(
        "Hermes memory schema",
        [row],
        max_chars=5000,
        routing_decision=resolve_branch("Hermes memory schema").to_dict(),
    ))

    for field in schema["required_top_level_fields"]:
        assert field in pack
    for field in schema["required_routing_fields"]:
        assert field in pack["routing_decision"]
    for field in schema["required_included_item_fields"]:
        assert field in pack["included_items"][0]


def test_cross_project_routing_fixture_matrix():
    cases = json.loads(Path("tests/fixtures/readable_tree_cross_project_routing.json").read_text(encoding="utf-8"))
    for case in cases:
        decision = resolve_branch(case["query"])
        assert decision.branch == case["expected_branch"], case["name"]
        assert decision.clarification_required is case["clarification_required"], case["name"]
        if case.get("must_allow"):
            assert case["must_allow"] in decision.allowed_scopes, case["name"]


def test_behavior_preflight_pack_includes_rule_fired_trace_and_metric(tmp_path):
    provider = ReadableTreeMemoryProvider({
        "agent": "reyna",
        "behavior_preflight": True,
        "max_prefetch_chars": 5000,
    })
    provider.initialize("s1", hermes_home=str(tmp_path), agent_identity="reyna")
    assert provider._store is not None
    provider._store.record_correction(
        "Ты должна была проверить обещанный architecture file before baseline analysis.",
        project="hermes-agent",
        source_id="turn-preflight",
        session_id="s1",
    )

    context = provider.prefetch("Проверь обещанный architecture baseline file", session_id="s2")
    preflight = _json_blocks(context)[0]

    assert preflight["version"] == "readable_tree_behavior_preflight_v1"
    assert preflight["runtime_contract"]["log_rule_fired"] is True
    assert preflight["preflight_trace"][0]["rule_fired"] is True
    assert preflight["preflight_trace"][0]["rule_used_in_answer"] is None
    assert "wrong_task_layer" in preflight["preflight_trace"][0]["mistake_classes"]

    metrics = provider._store.iter_metrics()
    match_metrics = [record for record in metrics if record["metric"] == "behavior_preflight_matches"]
    assert match_metrics
    assert match_metrics[-1]["metadata"]["rule_fired"] is True
    assert match_metrics[-1]["metadata"]["matched_rule_ids"]
