from __future__ import annotations

from plugins.memory.readable_tree import ReadableTreeMemoryProvider
from plugins.memory.readable_tree.schemas import MemoryNote
from plugins.memory.readable_tree.store import ReadableMemoryStore


def _metric_names(store: ReadableMemoryStore) -> list[str]:
    return [str(record.get("metric") or "") for record in store.iter_metrics()]


def test_provider_feature_flags_default_to_safe_rollout_values():
    provider = ReadableTreeMemoryProvider({})

    assert provider.feature_flags == {
        "behavior_preflight": True,
        "behavior_auto_record_corrections": False,
        "dream_behavior_sections": True,
        "retrieval_engine_v2": False,
        "semantic_index": False,
    }


def test_disabling_behavior_preflight_returns_normal_prefetch_without_preflight_pack(tmp_path):
    provider = ReadableTreeMemoryProvider({
        "agent": "reyna",
        "behavior_preflight": False,
        "max_prefetch_notes": 3,
        "max_prefetch_chars": 2000,
    })
    provider.initialize("session-1", hermes_home=str(tmp_path))
    assert provider._store is not None

    behavior = MemoryNote(
        type="behavior_rule",
        agent="reyna",
        scope="behavioral_learning",
        status="active",
        source="test",
        source_ids=["turn-1"],
        source_quality="manual",
        body="Before claiming complete, check tests and cite evidence.",
    )
    provider._store.write_note(behavior)
    provider._store.rebuild_index()

    context = provider.prefetch("claiming complete check tests", session_id="session-1")

    assert "## Behavior Preflight Pack" not in context
    assert "Context Pack v2" in context
    assert "behavior_preflight_matches" not in _metric_names(provider._store)


def test_log_metric_appends_local_jsonl_shape(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")

    store.log_metric("corrections_recorded", value=2, session_id="session-1", metadata={"source": "test"})

    records = store.iter_metrics()
    assert len(records) == 1
    record = records[0]
    assert record["metric"] == "corrections_recorded"
    assert record["value"] == 2
    assert record["agent"] == "reyna"
    assert record["session_id"] == "session-1"
    assert record["metadata"] == {"source": "test"}
    assert isinstance(record["timestamp"], str)
    assert store.metrics_log_path == tmp_path / "readable_memory" / "metrics.log.jsonl"


def test_record_correction_logs_correction_and_global_behavior_counts(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")

    store.record_correction(
        "You claimed work was complete without checking tests.",
        project="hermes-agent",
        source_id="turn-1",
        session_id="session-1",
    )

    metrics = store.iter_metrics()
    names = [record["metric"] for record in metrics]
    assert "corrections_recorded" in names
    assert "behavior_rules_active" in names
    assert "regression_cases_active" in names
    counts = {record["metric"]: record["value"] for record in metrics}
    assert counts["behavior_rules_active"] == 1
    assert counts["regression_cases_active"] == 1


def test_review_behavior_outcome_logs_fixed_and_repeated_only(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")

    store.review_behavior_outcome("rule-1", "fixed", "Checked tests before claiming done.", session_id="session-1")
    store.review_behavior_outcome("rule-2", "unclear", "Evidence was ambiguous.", session_id="session-1")
    store.review_behavior_outcome("rule-3", "repeated", "Again claimed done without evidence.", session_id="session-1")

    names = _metric_names(store)
    assert "outcome_fixed" in names
    assert "outcome_repeated" in names
    assert "outcome_unclear" not in names


def test_provider_logs_preflight_zero_result_and_truncation_metrics(tmp_path):
    provider = ReadableTreeMemoryProvider({"agent": "reyna", "max_prefetch_notes": 3, "max_prefetch_chars": 300})
    provider.initialize("session-1", hermes_home=str(tmp_path))
    assert provider._store is not None

    provider.prefetch("topic with no stored notes", session_id="session-1")
    assert "retrieval_zero_result_after_fallbacks" in _metric_names(provider._store)

    behavior = MemoryNote(
        type="behavior_rule",
        agent="reyna",
        scope="behavioral_learning",
        status="active",
        source="test",
        source_ids=["turn-1"],
        source_quality="manual",
        body="Before claiming work is complete, check tests and cite the evidence.",
    )
    provider._store.write_note(behavior)
    long_fact = MemoryNote(
        type="fact",
        agent="reyna",
        scope="project",
        status="active",
        source="test",
        source_ids=["turn-2"],
        source_quality="manual",
        body="Long project note about completion evidence. " * 80,
    )
    provider._store.write_note(long_fact)
    provider._store.rebuild_index()

    provider.behavior_preflight("claiming complete requires checking tests", session_id="session-2")
    provider.prefetch("completion evidence project note", session_id="session-2")

    names = _metric_names(provider._store)
    assert "behavior_preflight_matches" in names
    assert "context_pack_truncations" in names
