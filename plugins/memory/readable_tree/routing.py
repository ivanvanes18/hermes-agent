"""Project/branch routing contract for readable_tree Context Packs.

The resolver is intentionally deterministic and local.  It does not decide what
is true; it decides which project scopes are safe to retrieve before building a
Context Pack.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


DEFAULT_PROJECT_REGISTRY: dict[str, dict[str, Any]] = {
    "main": {
        "aliases": ["main", "general", "общий", "общая", "основной", "default"],
        "allowed_scopes": ["global", "main"],
        "denied_scopes": [],
    },
    "trading": {
        "aliases": ["trading", "trade", "трейдинг", "торгов", "бот", "бирж", "risk", "hyperliquid"],
        "allowed_scopes": ["project:trading", "domain:trading", "workflow:trading"],
        "denied_scopes": ["project:projectoriy", "domain:smeta"],
    },
    "projectoriy": {
        "aliases": ["проекторий", "projectoriy", "вор", "xlsx", "xls", "импорт", "смет", "gge", "ггэ", "lsr", "лср"],
        "allowed_scopes": ["project:projectoriy", "domain:smeta", "workflow:xlsx_import"],
        "denied_scopes": ["project:trading"],
    },
    "hermes-agent": {
        "aliases": ["hermes", "readable_tree", "memory", "память", "context pack", "контекст", "agent memory"],
        "allowed_scopes": ["project:hermes-agent", "domain:agent-memory", "workflow:context-pack"],
        "denied_scopes": ["project:trading", "project:projectoriy"],
    },
}


@dataclass(frozen=True)
class RoutingDecision:
    branch: str
    confidence: float
    matched_aliases: list[str] = field(default_factory=list)
    allowed_scopes: list[str] = field(default_factory=list)
    denied_scopes: list[str] = field(default_factory=list)
    clarification_required: bool = False
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "confidence": self.confidence,
            "matched_aliases": self.matched_aliases,
            "allowed_scopes": self.allowed_scopes,
            "denied_scopes": self.denied_scopes,
            "clarification_required": self.clarification_required,
            "evidence": self.evidence,
        }


def _text_has_alias(text: str, alias: str) -> bool:
    alias_norm = alias.casefold().strip()
    if not alias_norm:
        return False
    if re.search(r"\s", alias_norm):
        return alias_norm in text
    return bool(re.search(rf"(?<!\w){re.escape(alias_norm)}(?!\w)", text, flags=re.UNICODE))


def resolve_branch(
    query: str,
    *,
    configured_project: str = "",
    registry: dict[str, dict[str, Any]] | None = None,
) -> RoutingDecision:
    """Resolve the safest branch/project for a memory query.

    A configured project is treated as a high-confidence session route.  If no
    route is configured, lexical aliases can pick a branch.  Multiple strong
    lexical matches require clarification instead of falling back to Main.
    """
    reg = registry or DEFAULT_PROJECT_REGISTRY
    configured = str(configured_project or "").strip()
    if configured:
        key = configured.casefold()
        entry = reg.get(key) or reg.get(configured) or {}
        return RoutingDecision(
            branch=configured,
            confidence=0.95,
            matched_aliases=[configured],
            allowed_scopes=list(entry.get("allowed_scopes") or [f"project:{configured}"]),
            denied_scopes=list(entry.get("denied_scopes") or []),
            clarification_required=False,
            evidence=["configured_project"],
        )

    text = str(query or "").casefold()
    scores: list[tuple[str, list[str]]] = []
    for branch, entry in reg.items():
        aliases = [alias for alias in entry.get("aliases", []) if _text_has_alias(text, str(alias))]
        if aliases:
            scores.append((branch, aliases))
    scores.sort(key=lambda item: (len(item[1]), item[0]), reverse=True)
    if not scores:
        entry = reg.get("main", {})
        return RoutingDecision(
            branch="unknown",
            confidence=0.0,
            matched_aliases=[],
            allowed_scopes=list(entry.get("allowed_scopes") or ["global"]),
            denied_scopes=[],
            clarification_required=True,
            evidence=["no_alias_match"],
        )
    if len(scores) > 1:
        return RoutingDecision(
            branch="ambiguous",
            confidence=0.4,
            matched_aliases=[alias for _, aliases in scores for alias in aliases],
            allowed_scopes=[],
            denied_scopes=[],
            clarification_required=True,
            evidence=[f"matched:{branch}" for branch, _ in scores],
        )
    top_branch, top_aliases = scores[0]
    entry = reg.get(top_branch, {})
    confidence = min(0.9, 0.45 + 0.15 * len(top_aliases))
    return RoutingDecision(
        branch=top_branch,
        confidence=round(confidence, 2),
        matched_aliases=top_aliases,
        allowed_scopes=list(entry.get("allowed_scopes") or [f"project:{top_branch}"]),
        denied_scopes=list(entry.get("denied_scopes") or []),
        clarification_required=False,
        evidence=["alias_match"],
    )
