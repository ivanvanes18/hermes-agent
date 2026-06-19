import json
from pathlib import Path

from plugins.memory.readable_tree.regression import RegressionCase, build_regression_report, evaluate_regression_case, parse_regression_case
from plugins.memory.readable_tree.schemas import MemoryNote
from plugins.memory.readable_tree.store import ReadableMemoryStore


REGRESSION_BODY = """mistake_class: claimed_without_check
input_pattern: User asks to finish a coding task.
expected_behavior: Run targeted tests before claiming completion.
fail_signals: says done without pytest; claims fixed without evidence
source_correction: Ivan corrected a premature done claim.
linked_rule_id: rule-123
"""


def test_golden_behavior_regression_scenarios_parse_and_evaluate_each_mistake_class():
    fixture = Path("tests/fixtures/readable_tree_behavior_regressions.jsonl")
    scenarios = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert {scenario["mistake_class"] for scenario in scenarios} == {
        "wrong_task_layer",
        "failed_to_use_skill",
        "claimed_without_check",
        "asked_when_should_act",
        "acted_when_should_ask",
        "style_regression",
    }
    for scenario in scenarios:
        body = "\n".join([
            f"mistake_class: {scenario['mistake_class']}",
            f"input_pattern: {scenario['input_pattern']}",
            f"expected_behavior: {scenario['expected_behavior']}",
            f"fail_signals: {scenario['fail_signals']}",
            f"source_correction: {scenario['source_correction']}",
            f"linked_rule_id: {scenario['linked_rule_id']}",
        ])
        parsed = parse_regression_case(body)
        assert parsed.mistake_class == scenario["mistake_class"]
        assert evaluate_regression_case(body, scenario["passing_observed"])["verdict"] == "passed"
        failed = evaluate_regression_case(body, scenario["failing_observed"])
        assert failed["verdict"] == "failed", scenario["mistake_class"]


def test_build_regression_report_lists_active_cases_without_outcome_review_and_does_not_mutate(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    case = MemoryNote(
        body=REGRESSION_BODY,
        type="regression_case",
        agent="reyna",
        status="active",
        source="test",
        source_quality="file",
    )
    reviewed = MemoryNote(
        body=REGRESSION_BODY.replace("rule-123", "rule-reviewed"),
        type="regression_case",
        agent="reyna",
        status="active",
        source="test",
        source_quality="file",
    )
    store.write_note(case)
    store.write_note(reviewed)
    review = MemoryNote(
        body=f"Reviewed regression case {reviewed.id}: fixed.",
        type="outcome_review",
        agent="reyna",
        status="active",
        tags=[f"case:{reviewed.id}", "outcome:fixed"],
        source="test",
        source_quality="manual",
    )
    store.write_note(review)
    before = {note.id: (note.status, tuple(note.tags)) for note in store.list_notes()}

    report = build_regression_report(store.list_notes(), limit=20, dry_run=True)
    after = {note.id: (note.status, tuple(note.tags)) for note in store.list_notes()}

    assert report["dry_run"] is True
    assert report["llm_used"] is False
    assert report["changed_files"] == []
    assert [item["case_id"] for item in report["unreviewed_cases"]] == [case.id]
    assert report["unreviewed_cases"][0]["case"]["mistake_class"] == "claimed_without_check"
    assert before == after


def test_store_regression_report_tool_surface_is_dry_run_and_non_mutating(tmp_path):
    store = ReadableMemoryStore(tmp_path, agent="reyna")
    case = MemoryNote(
        body=REGRESSION_BODY,
        type="regression_case",
        agent="reyna",
        status="active",
        source="test",
        source_quality="file",
    )
    store.write_note(case)

    result = store.run_regression_report(limit=5, dry_run=True)

    assert result["unreviewed_cases"][0]["case_id"] == case.id
    assert result["dry_run"] is True
    assert result["changed_files"] == []


def test_parse_regression_case_extracts_required_fields():
    case = parse_regression_case(REGRESSION_BODY)

    assert isinstance(case, RegressionCase)
    assert case.mistake_class == "claimed_without_check"
    assert case.input_pattern == "User asks to finish a coding task."
    assert case.expected_behavior == "Run targeted tests before claiming completion."
    assert case.fail_signals == ["says done without pytest", "claims fixed without evidence"]
    assert case.source_correction == "Ivan corrected a premature done claim."
    assert case.linked_rule_id == "rule-123"


def test_evaluate_regression_case_returns_deterministic_pass_fail_unclear():
    passed = evaluate_regression_case(REGRESSION_BODY, "I ran targeted tests with pytest before claiming completion.")
    failed = evaluate_regression_case(REGRESSION_BODY, "Done, fixed without evidence.")
    unclear = evaluate_regression_case(REGRESSION_BODY, "I reviewed the files and changed the implementation.")

    assert passed["verdict"] == "passed"
    assert passed["case"]["mistake_class"] == "claimed_without_check"
    assert failed["verdict"] == "failed"
    assert failed["matched_fail_signal"]
    assert unclear["verdict"] == "unclear"
