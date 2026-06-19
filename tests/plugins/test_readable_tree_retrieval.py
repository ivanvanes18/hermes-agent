from __future__ import annotations

import json
from pathlib import Path

from plugins.memory.readable_tree import ReadableTreeMemoryProvider
from plugins.memory.readable_tree.retrieval import expand_graph_neighbors, retrieve_context_candidates
from plugins.memory.readable_tree.schemas import MemoryNote
from plugins.memory.readable_tree.semantic import build_semantic_candidate_provider
from plugins.memory.readable_tree.store import ReadableMemoryStore


def test_retrieval_engine_v2_returns_source_backed_fts_rows_only(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    store.initialize()
    note = MemoryNote(
        body="Иван решил: память должна оставаться source-backed, а semantic search может быть только candidate generator.",
        type="decision",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        importance="high",
        sensitivity="internal",
        source="test",
        source_ids=["session:test"],
        source_quality="direct",
    )
    store.write_note(note)
    store.rebuild_index()

    result = retrieve_context_candidates(
        store,
        "как мы решили делать semantic search в памяти",
        agent="reyna",
        project="hermes-agent",
        session_id="s1",
        limit=5,
        include_semantic=False,
        include_graph=False,
    )

    assert [row["id"] for row in result.rows] == [note.id]
    assert result.provenance["lexical_count"] == 1
    assert result.provenance["semantic_count"] == 0
    assert result.provenance["graph_count"] == 0
    assert result.provenance["final_count"] == 1


def test_retrieval_engine_v2_flag_defaults_off_and_can_be_enabled(tmp_path):
    provider = ReadableTreeMemoryProvider({"retrieval_engine_v2": True, "semantic_index": False})
    provider.initialize("s1", hermes_home=str(tmp_path), agent_identity="reyna")
    assert provider.feature_flags["retrieval_engine_v2"] is True
    assert provider.feature_flags["semantic_index"] is False


def test_graph_neighbor_expansion_returns_related_note_candidates_only():
    graph = {
        "nodes": [
            {"kind": "note", "id": "decision-a"},
            {"kind": "note", "id": "artifact-b"},
            {"kind": "event", "id": "event-1"},
        ],
        "edges": [
            {"from": "event:event-1", "to": "note:decision-a", "type": "event_to_note"},
            {"from": "event:event-1", "to": "note:artifact-b", "type": "event_to_note"},
        ],
    }

    candidates = expand_graph_neighbors(graph, ["decision-a"], limit=5)

    assert [candidate.note_id for candidate in candidates] == ["artifact-b"]
    assert candidates[0].source == "graph"


def test_graph_candidates_are_resolved_through_status_and_sensitivity_filters(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    store.initialize()
    visible = MemoryNote(
        body="Visible graph neighbor",
        type="decision",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        sensitivity="internal",
        source="test",
        source_ids=["s1"],
        source_quality="direct",
    )
    secret = MemoryNote(
        body="Secret graph neighbor",
        type="decision",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        sensitivity="secret_ref",
        source="test",
        source_ids=["s2"],
        source_quality="direct",
    )
    store.write_note(visible)
    store.write_note(secret)
    store.rebuild_index()

    rows = store.get_index_rows_by_ids(
        [visible.id, secret.id],
        statuses=["active"],
        include_sensitive=False,
        include_superseded=False,
    )

    assert [row["id"] for row in rows] == [visible.id]


def test_prefetch_includes_timeline_snippets_for_selected_notes(tmp_path):
    provider = ReadableTreeMemoryProvider({"retrieval_engine_v2": True, "max_prefetch_notes": 3, "max_prefetch_chars": 3000})
    provider.initialize("s1", hermes_home=str(tmp_path), agent_identity="reyna")
    note = MemoryNote(
        body="Timeline-backed memory decision for retrieval engine.",
        type="decision",
        agent="reyna",
        scope="memory",
        status="active",
        sensitivity="internal",
        source="test",
        source_ids=["source-1"],
        source_quality="direct",
    )
    assert provider._store is not None
    provider._store.write_note(note)
    provider._store.append_event(
        "decision_made",
        note_ids=[note.id],
        source_ids=["source-1"],
        payload={"reason": "timeline evidence test"},
    )
    provider._store.rebuild_index()

    context = provider.prefetch("Timeline-backed retrieval engine decision", session_id="s1")

    assert "timeline" in context.lower()
    assert "timeline evidence test" in context


class StaticSemanticProvider:
    def __init__(self, note_ids):
        self.note_ids = note_ids

    def search(self, query: str, limit: int) -> list[str]:
        return list(self.note_ids)[:limit]


def test_semantic_candidates_are_ids_only_and_resolved_through_store_filters(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    store.initialize()
    semantic_note = MemoryNote(
        body="Semantic-only memory about hybrid retrieval.",
        type="decision",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        sensitivity="internal",
        source="test",
        source_ids=["semantic-source"],
        source_quality="direct",
    )
    secret_note = MemoryNote(
        body="Semantic secret should not enter the context pack.",
        type="decision",
        agent="reyna",
        project="hermes-agent",
        scope="memory",
        status="active",
        sensitivity="secret_ref",
        source="test",
        source_ids=["secret-source"],
        source_quality="direct",
    )
    store.write_note(semantic_note)
    store.write_note(secret_note)
    store.rebuild_index()

    result = retrieve_context_candidates(
        store,
        "query with no lexical hit",
        agent="reyna",
        project="hermes-agent",
        session_id="s1",
        limit=5,
        include_semantic=True,
        semantic_provider=StaticSemanticProvider([semantic_note.id, secret_note.id]),
    )

    assert [row["id"] for row in result.rows] == [semantic_note.id]
    assert result.provenance["semantic_candidate_count"] == 2
    assert result.provenance["semantic_count"] == 1


def test_semantic_provider_factory_defaults_to_disabled_noop():
    provider = build_semantic_candidate_provider({"enabled": True, "provider": "none"})
    assert provider.search("anything", 5) == []


def test_retrieval_eval_queries_hit_source_backed_notes(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    store.initialize()
    bodies = [
        "По памяти из видео решили: source-backed memory uses a compact Context Pack.",
        "Агент учится на ошибках Ивана: Behavioral Learning Loop creates behavior rules and regression cases from corrections.",
        "Semantic search не источник истины: it is a candidate generator only; source-backed notes remain truth.",
        "События и заметки памяти связаны: readable memory graph links source event nodes to note nodes.",
    ]
    for body in bodies:
        store.write_note(MemoryNote(
            body=body,
            type="decision",
            agent="reyna",
            project="hermes-agent",
            scope="memory",
            status="active",
            sensitivity="internal",
            source="fixture",
            source_ids=["fixture"],
            source_quality="direct",
        ))
    store.rebuild_index()

    fixture = Path("tests/fixtures/readable_memory_retrieval_eval.jsonl")
    provider = build_semantic_candidate_provider({"enabled": True, "provider": "keyword", "limit": 4}, store=store)
    for line in fixture.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        result = retrieve_context_candidates(
            store,
            case["query"],
            agent="reyna",
            project="hermes-agent",
            limit=4,
            include_semantic=True,
            include_graph=False,
            semantic_provider=provider,
        )
        text = "\n".join(str(row.get("body") or "") for row in result.rows).casefold()
        for term in case["expected_terms"]:
            assert term.casefold() in text, (case["query"], term, text)
