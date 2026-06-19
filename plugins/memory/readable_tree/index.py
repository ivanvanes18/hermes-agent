"""SQLite FTS index for readable_tree memory notes."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable, Any

from .schemas import MemoryNote


_QUERY_STOPWORDS = {
    "about", "after", "again", "all", "and", "are", "because", "before", "can", "could",
    "does", "for", "from", "have", "how", "into", "must", "not", "our", "should",
    "that", "the", "then", "there", "this", "what", "when", "where", "which", "why", "with",
    "а", "без", "бы", "в", "во", "вот", "для", "до", "его", "ее", "если", "же", "за", "и",
    "или", "как", "ко", "ли", "мы", "на", "над", "надо", "нас", "не", "но", "ну", "о",
    "об", "от", "по", "под", "при", "про", "с", "со", "то", "у", "что", "это",
}


def _query_terms(query: str, *, max_terms: int = 12) -> list[str]:
    """Extract safe word-like terms for SQLite FTS5 queries."""
    terms: list[str] = []
    for raw in re.findall(r"\w+", query.casefold(), flags=re.UNICODE):
        term = raw.strip("-_")
        if len(term) < 3 or term in _QUERY_STOPWORDS:
            continue
        if term.isdigit():
            continue
        # Keep generated FTS syntax simple and safe. Raw user punctuation such
        # as hyphens can be parsed by FTS5 as operators/column qualifiers.
        term = re.sub(r"[^0-9a-zа-яё_]+", "", term, flags=re.IGNORECASE)
        if not term or term in _QUERY_STOPWORDS or term in terms:
            continue
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def normalize_query_for_fts_and(query: str, *, max_terms: int = 12) -> str:
    """Convert a human sentence into a safe strict FTS AND query."""
    return " ".join(_query_terms(query, max_terms=max_terms))


def normalize_query_for_fts_or(query: str, *, max_terms: int = 12) -> str:
    """Convert a human sentence into a conservative FTS OR query.

    FTS5 treats plain whitespace as AND. That is good for precise keyword queries
    but brittle for natural-language questions. This fallback keeps only useful
    word-like terms and joins them with OR so recall degrades gracefully.
    """
    return " OR ".join(_query_terms(query, max_terms=max_terms))


class ReadableMemoryIndex:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_search_attempts: list[dict[str, Any]] = []

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='notes_fts'"
            ).fetchone()
            if existing:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(notes_fts)").fetchall()}
                required = {"source_quality", "event_ids", "supersedes", "superseded_by", "pinned", "pin_scope"}
                if not required.issubset(columns):
                    conn.execute("DROP TABLE notes_fts")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    id UNINDEXED,
                    path UNINDEXED,
                    type UNINDEXED,
                    agent UNINDEXED,
                    project UNINDEXED,
                    scope UNINDEXED,
                    status UNINDEXED,
                    sensitivity UNINDEXED,
                    importance UNINDEXED,
                    observed_at UNINDEXED,
                    source_ids UNINDEXED,
                    source_quality UNINDEXED,
                    event_ids UNINDEXED,
                    supersedes UNINDEXED,
                    superseded_by UNINDEXED,
                    pinned UNINDEXED,
                    pin_scope UNINDEXED,
                    tags,
                    body
                )
                """
            )

    def rebuild(self, notes: Iterable[MemoryNote]) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute("DELETE FROM notes_fts")
            conn.executemany(
                """
                INSERT INTO notes_fts(
                    id, path, type, agent, project, scope, status, sensitivity,
                    importance, observed_at, source_ids, source_quality,
                    event_ids, supersedes, superseded_by, pinned, pin_scope, tags, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        n.id,
                        n.path,
                        n.type,
                        n.agent,
                        n.project,
                        n.scope,
                        n.status,
                        n.sensitivity,
                        n.importance,
                        n.observed_at,
                        ",".join(n.source_ids),
                        n.source_quality,
                        ",".join(n.event_ids),
                        ",".join(n.supersedes),
                        ",".join(n.superseded_by),
                        "1" if n.pinned else "0",
                        n.pin_scope,
                        " ".join(n.tags),
                        n.body,
                    )
                    for n in notes
                ],
            )

    def search(
        self,
        query: str,
        *,
        agent: str | None = None,
        project: str | None = None,
        scope: str | None = None,
        statuses: list[str] | None = None,
        sensitivity: str | list[str] | None = None,
        importance: str | list[str] | None = None,
        source_quality: str | list[str] | None = None,
        pinned: bool | None = None,
        pin_scope: str | None = None,
        include_superseded: bool = False,
        recency_days: int | None = None,
        observed_after: str | None = None,
        observed_before: str | None = None,
        include_sensitive: bool = False,
        limit: int = 8,
    ) -> list[dict]:
        self.initialize()

        def as_values(value: Any) -> list[str]:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(v) for v in value if str(v).strip()]
            return [str(value)] if str(value).strip() else []

        def add_in_filter(filters: list[str], params: list[str], field: str, values: list[str]) -> None:
            if not values:
                return
            filters.append(f"{field} IN (%s)" % ",".join("?" for _ in values))
            params.extend(values)

        def recency_cutoff(days: int | None) -> str | None:
            if not days:
                return None
            from datetime import datetime, timedelta, timezone
            return (datetime.now(timezone.utc) - timedelta(days=int(days))).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        def metadata_filters() -> tuple[list[str], list[str]]:
            filters: list[str] = []
            params: list[str] = []
            if agent:
                filters.append("agent = ?")
                params.append(agent)
            if project:
                filters.append("project = ?")
                params.append(project)
            if scope:
                filters.append("scope = ?")
                params.append(scope)
            add_in_filter(filters, params, "status", statuses or [])
            add_in_filter(filters, params, "sensitivity", as_values(sensitivity))
            add_in_filter(filters, params, "importance", as_values(importance))
            add_in_filter(filters, params, "source_quality", as_values(source_quality))
            if pinned is not None:
                filters.append("pinned = ?")
                params.append("1" if pinned else "0")
            if pin_scope:
                filters.append("pin_scope = ?")
                params.append(pin_scope)
            cutoff = observed_after or recency_cutoff(recency_days)
            if cutoff:
                filters.append("observed_at >= ?")
                params.append(cutoff)
            if observed_before:
                filters.append("observed_at <= ?")
                params.append(observed_before)
            if not include_sensitive and not sensitivity:
                filters.append("sensitivity NOT IN ('sensitive', 'secret_ref')")
            if not include_superseded:
                filters.append("(superseded_by IS NULL OR superseded_by = '')")
                if not statuses:
                    filters.append("status NOT IN ('superseded', 'archived', 'open_loop', 'conflicting')")
            return filters, params

        self.last_search_attempts = []
        original_query = query.strip()
        strict_query = normalize_query_for_fts_and(original_query)
        normalized_query = normalize_query_for_fts_or(original_query)
        rank_terms = [term for term in normalized_query.split(" OR ") if term]

        def row_score(row: dict) -> int:
            """Rank safe candidates after metadata filtering.

            SQLite FTS is the candidate generator; this score keeps the Context
            Pack biased toward durable, source-backed, promoted memories instead
            of whichever OR fallback row happened to be newest.
            """
            status_scores = {
                "active": 80,
                "needs_confirmation": 25,
                "uncertain": 20,
                "inbox": 5,
                "open_loop": -10,
                "conflicting": 0,
                "archived": -50,
                "superseded": -80,
            }
            importance_scores = {"critical": 45, "high": 35, "medium": 10, "low": 0}
            source_quality_scores = {
                "direct": 30,
                "manual": 30,
                "confirmed": 30,
                "file": 25,
                "tool": 25,
                "session": 20,
                "inferred": 0,
            }
            score = 0
            score += status_scores.get(str(row.get("status") or ""), 0)
            score += importance_scores.get(str(row.get("importance") or ""), 0)
            score += source_quality_scores.get(str(row.get("source_quality") or ""), 0)
            if str(row.get("pinned") or "0") == "1":
                score += 25
            searchable = " ".join(
                str(row.get(key) or "").casefold()
                for key in ["body", "tags", "type", "scope", "project", "source_ids"]
            )
            term_hits = sum(1 for term in rank_terms if term.casefold() in searchable)
            score += min(60, term_hits * 8)
            if rank_terms and term_hits == len(rank_terms):
                score += 15
            return score

        def select_rows(filters: list[str], params: list[str]) -> list[dict]:
            where = "WHERE " + " AND ".join(filters) if filters else ""
            candidate_limit = max(int(limit) * 8, 50)
            sql = f"SELECT * FROM notes_fts {where} ORDER BY observed_at DESC LIMIT ?"
            with self._connect() as conn:
                rows = [dict(row) for row in conn.execute(sql, params + [str(candidate_limit)]).fetchall()]
            rows.sort(key=lambda row: (row_score(row), str(row.get("observed_at") or "")), reverse=True)
            return rows[:limit]

        def record_attempt(strategy: str, query_text: str, rows: list[dict], error: str = "") -> None:
            entry: dict[str, Any] = {
                "strategy": strategy,
                "query": query_text,
                "result_count": len(rows),
            }
            if error:
                entry["error"] = error
            self.last_search_attempts.append(entry)

        def attempt_fts(strategy: str, fts_query: str) -> list[dict]:
            filters, params = metadata_filters()
            if fts_query.strip():
                filters.insert(0, "notes_fts MATCH ?")
                params.insert(0, fts_query.strip())
            try:
                rows = select_rows(filters, params)
                record_attempt(strategy, fts_query, rows)
                return rows
            except sqlite3.OperationalError as exc:
                record_attempt(strategy, fts_query, [], str(exc))
                return []

        rows = attempt_fts("strict_and", strict_query)
        if not original_query:
            return rows

        if normalized_query and normalized_query != strict_query:
            relaxed_rows = attempt_fts("relaxed_or", normalized_query)
            if relaxed_rows:
                rows = relaxed_rows

        artifact_terms = [term for term in _query_terms(original_query, max_terms=8) if len(term) >= 4]
        artifact_query = " OR ".join(artifact_terms)
        if artifact_query:
            artifact_rows = attempt_fts("quoted_artifact_terms", artifact_query)
            if not rows and artifact_rows:
                rows = artifact_rows

        if rows:
            return rows

        # FTS syntax can reject arbitrary punctuation, and natural-language terms
        # can still miss after normalization. Last resort: OR body LIKE against the
        # same normalized tokens while preserving every metadata/safety filter.
        like_filters, like_params = metadata_filters()
        like_terms = [term for term in normalized_query.split(" OR ") if term]
        if not like_terms and original_query:
            like_terms = [original_query]
        if like_terms:
            like_filters.append("(" + " OR ".join("body LIKE ?" for _ in like_terms) + ")")
            like_params.extend(f"%{term}%" for term in like_terms)
        try:
            rows = select_rows(like_filters, like_params)
            record_attempt("like_terms", " OR ".join(like_terms), rows)
            return rows
        except sqlite3.OperationalError as exc:
            record_attempt("like_terms", " OR ".join(like_terms), [], str(exc))
            return []

    def rows_by_ids(
        self,
        note_ids: list[str],
        *,
        statuses: list[str] | None = None,
        include_sensitive: bool = False,
        include_superseded: bool = False,
    ) -> list[dict]:
        """Resolve exact note IDs through index metadata filters.

        This is for graph/semantic candidate IDs. It deliberately applies the
        same default safety exclusions as normal retrieval before returning rows
        that can enter a Context Pack.
        """
        self.initialize()
        wanted = [str(note_id) for note_id in note_ids if str(note_id).strip()]
        if not wanted:
            return []
        filters = ["id IN (%s)" % ",".join("?" for _ in wanted)]
        params: list[str] = list(wanted)
        if statuses:
            filters.append("status IN (%s)" % ",".join("?" for _ in statuses))
            params.extend(str(value) for value in statuses)
        if not include_sensitive:
            filters.append("sensitivity NOT IN ('sensitive', 'secret_ref')")
        if not include_superseded:
            filters.append("(superseded_by IS NULL OR superseded_by = '')")
            if not statuses:
                filters.append("status NOT IN ('superseded', 'archived', 'open_loop', 'conflicting')")
        where = "WHERE " + " AND ".join(filters)
        sql = f"SELECT * FROM notes_fts {where}"
        with self._connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        by_id = {str(row.get("id") or ""): row for row in rows}
        return [by_id[note_id] for note_id in wanted if note_id in by_id]
