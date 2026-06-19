"""Hybrid retrieval orchestration for readable_tree memory.

All candidate sources return note rows or note IDs that are resolved through the
source-backed store before a Context Pack is built.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .semantic import SemanticCandidateProvider


@dataclass(frozen=True)
class RetrievalCandidate:
    note_id: str
    source: str
    score: int = 0
    reason: str = ""


@dataclass(frozen=True)
class RetrievalResult:
    rows: list[dict[str, Any]]
    provenance: dict[str, Any] = field(default_factory=dict)


def _dedupe_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        note_id = str(row.get("id") or "")
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        out.append(row)
        if len(out) >= max(1, int(limit or 1)):
            break
    return out


def expand_graph_neighbors(graph: dict[str, Any], seed_note_ids: list[str], limit: int = 6) -> list[RetrievalCandidate]:
    """Return note candidates connected to seed notes by one shared graph node.

    The graph layer returns candidate IDs only. Callers must resolve IDs through
    the source-backed store before including any text in a Context Pack.
    """
    seed_nodes = {f"note:{note_id}" for note_id in seed_note_ids if note_id}
    if not seed_nodes:
        return []
    adjacency: dict[str, set[str]] = {}
    for edge in graph.get("edges") or []:
        left = str(edge.get("from") or "")
        right = str(edge.get("to") or "")
        if not left or not right:
            continue
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)

    out: list[RetrievalCandidate] = []
    seen = set(seed_nodes)
    for seed in sorted(seed_nodes):
        for neighbor in sorted(adjacency.get(seed, set())):
            for second_hop in sorted(adjacency.get(neighbor, set())):
                if not second_hop.startswith("note:") or second_hop in seen:
                    continue
                seen.add(second_hop)
                out.append(
                    RetrievalCandidate(
                        note_id=second_hop.removeprefix("note:"),
                        source="graph",
                        score=15,
                        reason="shared graph edge",
                    )
                )
                if len(out) >= max(1, int(limit or 1)):
                    return out
    return out


def retrieve_context_candidates(
    store,
    query: str,
    *,
    agent: str,
    project: str = "",
    session_id: str = "",
    limit: int = 6,
    include_semantic: bool = False,
    include_graph: bool = False,
    graph: dict[str, Any] | None = None,
    semantic_provider: SemanticCandidateProvider | None = None,
) -> RetrievalResult:
    """Collect source-backed context candidate rows for a query.

    The first implementation intentionally preserves the existing FTS-only
    behavior. Semantic and graph flags are recorded in provenance but do not
    add candidates until later Phase 13 tasks wire safe ID resolution.
    """
    lexical_rows = store.index.search(
        query,
        agent=agent,
        project=project or None,
        statuses=["active", "uncertain", "needs_confirmation"],
        include_sensitive=False,
        limit=max(1, int(limit or 6)),
    )
    store.log_retrieval(
        query=query,
        rows=lexical_rows,
        attempts=list(store.index.last_search_attempts),
        source="retrieval_v2:lexical",
        session_id=session_id,
        metadata={"project": project, "include_semantic": include_semantic, "include_graph": include_graph},
    )
    semantic_ids = semantic_provider.search(query, max(1, int(limit or 6))) if include_semantic and semantic_provider else []
    semantic_rows = store.get_index_rows_by_ids(
        semantic_ids,
        statuses=["active", "uncertain", "needs_confirmation"],
        include_sensitive=False,
        include_superseded=False,
    ) if semantic_ids else []
    seed_ids = [str(row.get("id") or "") for row in [*lexical_rows, *semantic_rows]]
    graph_candidates = expand_graph_neighbors(graph or {}, seed_ids, limit=limit) if include_graph else []
    graph_rows = store.get_index_rows_by_ids(
        [candidate.note_id for candidate in graph_candidates],
        statuses=["active", "uncertain", "needs_confirmation"],
        include_sensitive=False,
        include_superseded=False,
    ) if graph_candidates else []
    final_rows = _dedupe_rows([*lexical_rows, *semantic_rows, *graph_rows], limit)
    return RetrievalResult(
        rows=final_rows,
        provenance={
            "version": "readable_memory_retrieval_v2",
            "lexical_count": len(lexical_rows),
            "semantic_candidate_count": len(semantic_ids),
            "semantic_count": len(semantic_rows),
            "graph_candidate_count": len(graph_candidates),
            "graph_count": len(graph_rows),
            "final_count": len(final_rows),
            "semantic_enabled": bool(include_semantic),
            "graph_enabled": bool(include_graph),
        },
    )
