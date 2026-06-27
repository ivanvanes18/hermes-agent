from __future__ import annotations

import json
from pathlib import Path

from agent.memory_manager import MemoryManager
from plugins.memory.readable_tree import ReadableTreeMemoryProvider
from plugins.memory.readable_tree.eval import run_memory_closure_eval
from plugins.memory.readable_tree.schemas import MemoryNote


def _seed_memory_closure_provider(tmp_path) -> ReadableTreeMemoryProvider:
    provider = ReadableTreeMemoryProvider({
        "agent": "reyna",
        "retrieval_engine_v2": True,
        "behavior_preflight": True,
        "max_prefetch_notes": 6,
        "max_prefetch_chars": 5000,
    })
    provider.initialize("closure-seed", hermes_home=str(tmp_path), agent_identity="reyna")
    assert provider._store is not None
    notes = [
        MemoryNote(
            body="Hermes memory closure uses source-backed Context Pack contracts and project routing.",
            type="decision",
            agent="reyna",
            project="hermes-agent",
            scope="memory",
            status="active",
            sensitivity="internal",
            importance="high",
            source="fixture",
            source_ids=["src-hermes-memory"],
            source_quality="direct",
        ),
        MemoryNote(
            body="Проекторий ВОР XLSX импорт сметы хранится отдельно от trading workflow.",
            type="decision",
            agent="reyna",
            project="projectoriy",
            scope="smeta",
            status="active",
            sensitivity="internal",
            importance="high",
            source="fixture",
            source_ids=["src-projectoriy"],
            source_quality="direct",
        ),
        MemoryNote(
            body="Trading risk hyperliquid workflow must not inherit Projectoriy VOR assumptions.",
            type="decision",
            agent="reyna",
            project="trading",
            scope="trading",
            status="active",
            sensitivity="internal",
            importance="high",
            source="fixture",
            source_ids=["src-trading"],
            source_quality="direct",
        ),
    ]
    for note in notes:
        provider._store.write_note(note)
    provider._store.record_correction(
        "Ты должна была проверить обещанный architecture file before baseline analysis.",
        project="hermes-agent",
        source_id="src-correction",
        session_id="closure-seed",
    )
    provider._store.rebuild_index()
    return provider


def test_memory_closure_eval_reports_pack_size_routing_contamination_and_behavior(tmp_path):
    provider = _seed_memory_closure_provider(tmp_path)
    cases = json.loads(Path("tests/fixtures/readable_tree_memory_closure_cases.json").read_text(encoding="utf-8"))

    report = run_memory_closure_eval(provider, cases)

    assert report["overall_pass"] is True
    assert report["summary"]["cases_total"] == len(cases)
    assert report["summary"]["cases_passed"] == len(cases)
    assert report["summary"]["contamination_failures"] == 0
    assert report["summary"]["behavior_rules_fired"] >= 1
    for case in report["cases"]:
        assert case["pack_chars"] <= case["max_pack_chars"]
        assert not case["contamination_failures"]
        assert case["passed"] is True


def test_memory_closure_runtime_tool_path(tmp_path):
    provider = ReadableTreeMemoryProvider({"agent": "reyna", "behavior_preflight": True})
    provider.initialize("closure-runtime", hermes_home=str(tmp_path), agent_identity="reyna")
    mgr = MemoryManager()
    mgr.add_provider(provider)

    assert mgr.has_tool("readable_memory_status")
    assert mgr.has_tool("readable_memory_record_correction")
    assert mgr.has_tool("readable_memory_behavior_preflight")

    correction = json.loads(mgr.handle_tool_call("readable_memory_record_correction", {
        "correction": "Ты должна была проверить обещанный architecture file before baseline analysis.",
        "project": "hermes-agent",
        "source_id": "src-runtime-correction",
        "session_id": "closure-runtime",
    }))
    assert correction["success"] is True

    preflight = json.loads(mgr.handle_tool_call("readable_memory_behavior_preflight", {
        "query": "Проверь обещанный architecture baseline file"
    }))
    assert "preflight_trace" in preflight["context"]
    assert "wrong_task_layer" in preflight["context"]
    rule_id = preflight["context"].split('"rule_id":"', 1)[1].split('"', 1)[0]

    outcome = json.loads(mgr.handle_tool_call("readable_memory_review_outcome", {
        "rule_id": rule_id,
        "outcome": "fixed",
        "evidence": "Runtime tool path retrieved the rule and recorded outcome evidence.",
        "rule_used_in_answer": True,
        "session_id": "closure-runtime",
    }))
    assert outcome["success"] is True
    assert outcome["rule_used_in_answer"] is True
    assert outcome["related_case_ids"]

    report = json.loads(mgr.handle_tool_call("readable_memory_run_regression_report", {"limit": 5}))
    assert report["unreviewed_cases"] == []


def test_memory_closure_dream_cycle_is_proposal_only_then_selected_apply(tmp_path):
    provider = ReadableTreeMemoryProvider({"agent": "reyna"})
    provider.initialize("closure-dream", hermes_home=str(tmp_path), agent_identity="reyna")
    assert provider._store is not None
    selected = MemoryNote(
        body="Dream closure sourced inbox fact.",
        type="fact",
        agent="reyna",
        status="inbox",
        source="fixture",
        source_ids=["turn-dream-selected"],
        source_quality="manual",
    )
    other = MemoryNote(
        body="Dream closure other sourced inbox fact.",
        type="fact",
        agent="reyna",
        status="inbox",
        source="fixture",
        source_ids=["turn-dream-other"],
        source_quality="manual",
    )
    provider._store.write_note(selected)
    provider._store.write_note(other)
    mgr = MemoryManager()
    mgr.add_provider(provider)

    dream = json.loads(mgr.handle_tool_call("readable_memory_dream_cycle", {"limit": 10}))
    after_dream = {note.id: note.status for note in provider._store.list_notes()}
    preview = json.loads(mgr.handle_tool_call("readable_memory_apply_proposal", {
        "run_id": dream["run_id"],
        "note_ids": [selected.id],
        "dry_run": True,
    }))
    after_preview = {note.id: note.status for note in provider._store.list_notes()}
    applied = json.loads(mgr.handle_tool_call("readable_memory_apply_proposal", {
        "run_id": dream["run_id"],
        "note_ids": [selected.id],
        "dry_run": False,
    }))
    after_apply = {note.id: note.status for note in provider._store.list_notes()}

    assert dream["proposed"] >= 2
    assert after_dream == {selected.id: "inbox", other.id: "inbox"}
    assert preview["applied"][0]["note_id"] == selected.id
    assert preview["changed_files"] == []
    assert after_preview == after_dream
    assert applied["applied"][0]["event_ids"]
    assert after_apply[selected.id] == "active"
    assert after_apply[other.id] == "inbox"
