"""Optional semantic candidate adapter for readable_tree memory.

The source-backed Context Pack remains the final contract. Semantic providers may
only suggest note IDs to retrieve through the Markdown/SQLite store; they must
not inject unsourced text directly into prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


DEFAULT_SEMANTIC_CONFIG = {
    "enabled": False,
    "provider": "none",
    "limit": 0,
}


class SemanticCandidateProvider(Protocol):
    """Optional provider that returns candidate readable_tree note IDs."""

    def search(self, query: str, limit: int) -> list[str]:
        """Return candidate note IDs for the query.

        Implementations must return IDs only. The caller is responsible for
        resolving IDs through the source-backed note store before building a
        Context Pack.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class NoopSemanticCandidateProvider:
    """Disabled-by-default semantic adapter."""

    enabled: bool = False
    provider: str = "none"
    config: dict[str, object] = field(default_factory=lambda: dict(DEFAULT_SEMANTIC_CONFIG))

    def search(self, query: str, limit: int) -> list[str]:
        return []


@dataclass(frozen=True)
class KeywordSemanticCandidateProvider:
    """Local contract provider used for retrieval-pipeline evals.

    This is not an embedding model. It returns candidate note IDs using the
    existing source-backed index, so the retrieval engine can exercise the
    semantic-provider contract without allowing unsourced text into prompts.
    """

    store: Any
    config: dict[str, object] = field(default_factory=lambda: dict(DEFAULT_SEMANTIC_CONFIG))

    def search(self, query: str, limit: int) -> list[str]:
        configured_limit = self.config.get("limit") or 1
        raw_limit: object = limit if limit else configured_limit
        try:
            effective_limit = max(1, int(str(raw_limit)))
        except (TypeError, ValueError):
            effective_limit = 1
        rows = self.store.index.search(
            query,
            agent=getattr(self.store, "agent", "default"),
            statuses=["active", "uncertain", "needs_confirmation"],
            include_sensitive=False,
            limit=effective_limit,
        )
        return [str(row.get("id") or "") for row in rows if row.get("id")]


def build_semantic_candidate_provider(
    config: dict[str, object] | None = None,
    *,
    store: object | None = None,
) -> SemanticCandidateProvider:
    """Build the optional semantic provider.

    Providers must return note IDs only. The retrieval engine resolves those IDs
    through the source-backed store before adding rows to a Context Pack.
    """
    merged = dict(DEFAULT_SEMANTIC_CONFIG)
    merged.update(config or {})
    provider = str(merged.get("provider") or "none")
    if not bool(merged.get("enabled")):
        return NoopSemanticCandidateProvider(enabled=False, provider=provider, config=merged)
    if provider == "keyword" and store is not None:
        return KeywordSemanticCandidateProvider(store=store, config=merged)
    return NoopSemanticCandidateProvider(enabled=False, provider="none", config=merged)
