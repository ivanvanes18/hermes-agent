#!/usr/bin/env python3
"""Proposal-only readable_memory Dream Cycle report helper.

This script is designed for Hermes cron with no_agent=True. It never applies
proposal actions. It prints a short operator message only when the review queue
is non-empty or when a daily heartbeat is due.

Install into a profile by copying it to:
    ~/.hermes/scripts/readable_memory_dream_cycle_report.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home()
ROOT = HOME / ".hermes" / "readable_memory"
TREE = ROOT / "tree"
METRICS = ROOT / "metrics"
STATE = METRICS / "dream_cycle_report_state.json"
MOSCOW = ZoneInfo("Europe/Moscow")
DAILY_REPORT_AFTER_HOURS = 20


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def count_review_notes() -> dict[str, int]:
    counts = {"inbox": 0, "needs_review": 0, "needs_confirmation": 0, "conflicting": 0}
    if not TREE.exists():
        return counts
    for path in TREE.rglob("*.md"):
        if path.name == "changelog.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:1200]
        for status in counts:
            if f"status: {status}" in text or f"status: '{status}'" in text or f'status: "{status}"' in text:
                counts[status] += 1
                break
    return counts


def fmt_dt(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(MOSCOW).strftime("%Y-%m-%d %H:%M MSK")


def main() -> None:
    now = datetime.now(timezone.utc)
    METRICS.mkdir(parents=True, exist_ok=True)
    state = load_json(STATE, {})
    counts = count_review_notes()
    review_total = sum(counts.values())
    last_report_at = state.get("last_report_at")
    due_daily = not last_report_at
    if last_report_at:
        try:
            due_daily = now - datetime.fromisoformat(last_report_at.replace("Z", "+00:00")) >= timedelta(hours=DAILY_REPORT_AFTER_HOURS)
        except Exception:
            due_daily = True

    sample = {
        "ts": now.isoformat().replace("+00:00", "Z"),
        "review_total": review_total,
        "status_counts": counts,
    }
    state["last_sample"] = sample

    if due_daily or review_total:
        state["last_report_at"] = sample["ts"]
        print("🧠 Память: Dream Cycle review сигнал")
        print(f"Время: {fmt_dt(sample['ts'])}")
        print(f"Review queue: {review_total} = " + ", ".join(f"{k}:{v}" for k, v in counts.items()))
        print('Следующий безопасный шаг: попросить Рейну выполнить readable_memory_dream_cycle({"limit": 50, "include_sensitive": false}) и применить только выбранные предложения через dry-run.')

    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
