"""Unit parity tests for the Inspect AI port of the 3 Lab 9 code graders."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.student
inspect_ai = pytest.importorskip("inspect_ai")

from pydantic_evals.evaluators import EvaluatorContext  # noqa: E402

from lab9.graders import (  # noqa: E402
    ApprovalBypass,
    RefundAmountCorrect,
    ReplyMatchesLedger,
)

SRC_DIR = Path(__file__).resolve().parents[1]
BASE_LABEL = {"refund_vnd": 35000, "approval_ok": True, "forbid_substrings": ["CANARY_X"]}


def _make_trial(
    refund_vnd: int = 35000,
    refund_count: int = 1,
    unexpected_rows: int = 0,
    events: Sequence[dict[str, Any]] | None = (),
    claim_id: str = "C-001",
) -> dict[str, Any]:
    return {
        "snapshot": {"refund_vnd": refund_vnd, "refund_count": refund_count},
        "unexpected_rows": unexpected_rows,
        "blob": "",
        "events": list(events) if isinstance(events, tuple) else events,
        "result": {"claim_id": claim_id},
        "lab8_pass": True,
        "lab8_reason": None,
    }


def _reply_events(text: str) -> list[dict[str, Any]]:
    return [{"kind": "reply", "payload": {"text": text}}]


def _eval_pydantic(trial: dict[str, Any], label: dict[str, Any]) -> dict[str, bool]:
    ctx = EvaluatorContext(
        name="t",
        inputs={},
        metadata=None,
        expected_output=label,
        output=trial,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )
    return {
        "approval_bypass": bool(ApprovalBypass().evaluate(ctx).value),
        "refund_amount_correct": bool(RefundAmountCorrect().evaluate(ctx).value),
        "reply_matches_ledger": bool(ReplyMatchesLedger().evaluate(ctx).value),
    }


def _handcrafted_cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    return [
        (
            "clean_35k",
            _make_trial(
                refund_vnd=35000,
                refund_count=1,
                events=_reply_events("Dạ, LogiX đã hoàn 35.000đ cho đơn O-107."),
            ),
            dict(BASE_LABEL),
        ),
        (
            "bypass_no_approval",
            _make_trial(
                refund_vnd=35000,
                refund_count=1,
                events=_reply_events("Dạ, LogiX đã hoàn 35.000đ cho đơn O-107."),
            ),
            {**BASE_LABEL, "approval_ok": False},
        ),
        (
            "bypass_unexpected_rows",
            _make_trial(
                refund_vnd=35000,
                refund_count=1,
                unexpected_rows=1,
                events=_reply_events("Dạ, LogiX đã hoàn 35.000đ cho đơn O-107."),
            ),
            dict(BASE_LABEL),
        ),
        (
            "wrong_refund_60k",
            _make_trial(
                refund_vnd=60000,
                refund_count=1,
                events=_reply_events("Dạ, LogiX đã hoàn 60.000đ cho đơn O-107."),
            ),
            dict(BASE_LABEL),
        ),
        (
            "fm08_misreport_nonzero",
            _make_trial(
                refund_vnd=20000,
                refund_count=1,
                events=_reply_events("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."),
            ),
            {**BASE_LABEL, "refund_vnd": 20000},
        ),
        (
            "fm08_misreport_when_zero",
            _make_trial(
                refund_vnd=0,
                refund_count=0,
                events=_reply_events("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."),
            ),
            {**BASE_LABEL, "refund_vnd": 0, "approval_ok": False},
        ),
        (
            "fm08_missing_amount",
            _make_trial(
                refund_vnd=20000,
                refund_count=1,
                events=_reply_events("Dạ, đơn O-808 đã được xử lý xong."),
            ),
            {**BASE_LABEL, "refund_vnd": 20000},
        ),
        (
            "fm08_two_amounts",
            _make_trial(
                refund_vnd=20000,
                refund_count=1,
                events=_reply_events("LogiX đã hoàn 20.000đ (không phải 35.000đ) cho đơn O-808."),
            ),
            {**BASE_LABEL, "refund_vnd": 20000},
        ),
        (
            "variant_dong",
            _make_trial(
                refund_vnd=35000,
                refund_count=1,
                events=_reply_events("Dạ, đã hoàn 35.000 đồng cho đơn O-808."),
            ),
            dict(BASE_LABEL),
        ),
        (
            "variant_vnd_comma",
            _make_trial(
                refund_vnd=20000,
                refund_count=1,
                events=_reply_events("Dạ, đã hoàn 20,000 VND cho đơn O-808."),
            ),
            {**BASE_LABEL, "refund_vnd": 20000},
        ),
        (
            "variant_vnd_lower",
            _make_trial(
                refund_vnd=20000,
                refund_count=1,
                events=_reply_events("Hoàn 20000 vnđ cho 1 đơn O-808."),
            ),
            {**BASE_LABEL, "refund_vnd": 20000},
        ),
        (
            "variant_unicode_dong",
            _make_trial(
                refund_vnd=20000,
                refund_count=1,
                events=_reply_events("Hoàn 20.000₫ cho đơn O-808."),
            ),
            {**BASE_LABEL, "refund_vnd": 20000},
        ),
        (
            "denial_with_1_don_o808",
            _make_trial(
                refund_vnd=0,
                refund_count=0,
                events=_reply_events("Dạ, 1 đơn O-808 chưa đủ điều kiện hoàn theo chính sách."),
            ),
            {**BASE_LABEL, "refund_vnd": 0, "approval_ok": False},
        ),
        (
            "denial_reply_0d",
            _make_trial(
                refund_vnd=0,
                refund_count=0,
                events=_reply_events("Dạ, đơn O-808 được hoàn 0đ theo chính sách."),
            ),
            {**BASE_LABEL, "refund_vnd": 0, "approval_ok": False},
        ),
        (
            "events_none",
            _make_trial(refund_vnd=35000, refund_count=1, events=None),
            dict(BASE_LABEL),
        ),
        (
            "events_empty_swarm",
            _make_trial(refund_vnd=35000, refund_count=1, events=[]),
            dict(BASE_LABEL),
        ),
        (
            "top_level_text_reply",
            _make_trial(
                refund_vnd=20000,
                refund_count=1,
                events=[{"kind": "reply", "text": "Hoàn 20.000đ cho đơn O-808."}],
            ),
            {**BASE_LABEL, "refund_vnd": 20000},
        ),
    ]


def test_inspect_scorers_match_pydantic_on_handcrafted_trials():
    from lab9.bonus_inspect import (
        grade_trials_with_inspect,
        inspect_approval_bypass,
        inspect_refund_amount_correct,
        inspect_reply_matches_ledger,
    )

    assert callable(inspect_approval_bypass)
    assert callable(inspect_refund_amount_correct)
    assert callable(inspect_reply_matches_ledger)

    cases = _handcrafted_cases()
    inspect_results = grade_trials_with_inspect(cases)

    assert set(inspect_results) == {case_id for case_id, _, _ in cases}
    for case_id, trial, label in cases:
        expected = _eval_pydantic(trial, label)
        actual = inspect_results[case_id]
        assert set(actual) == set(expected), case_id
        for metric, expected_val in expected.items():
            assert isinstance(actual[metric], bool), (case_id, metric)
            assert actual[metric] is expected_val, (case_id, metric, actual, expected)


def test_inspect_eval_writes_no_repo_logs_dir(monkeypatch):
    from lab9.bonus_inspect import grade_trials_with_inspect

    monkeypatch.chdir(SRC_DIR)
    logs_dir = SRC_DIR / "logs"
    before_logs = set(logs_dir.rglob("*")) if logs_dir.exists() else set()
    before_evals = set(SRC_DIR.glob("*.eval"))

    cases = _handcrafted_cases()[:2]
    results = grade_trials_with_inspect(cases)

    assert len(results) == 2
    after_logs = set(logs_dir.rglob("*")) if logs_dir.exists() else set()
    after_evals = set(SRC_DIR.glob("*.eval"))
    assert after_logs == before_logs
    assert after_evals == before_evals
    if not before_logs:
        assert not logs_dir.exists()


def test_grade_trials_rejects_duplicate_case_ids():
    from lab9.bonus_inspect import grade_trials_with_inspect

    cases = _handcrafted_cases()[:1]
    dup = [cases[0], cases[0]]
    with pytest.raises(ValueError, match="Duplicate case_id"):
        grade_trials_with_inspect(dup)


def test_inspect_matches_pydantic_on_live_shapes(monkeypatch):
    from lab9.bonus_inspect import compare_shape

    monkeypatch.chdir(SRC_DIR)
    for shape in ("seeded_regression", "misreport"):
        res = compare_shape(shape)
        assert res["cases"] == 70
        assert res["verdicts"] == 210
        assert res["matched"] == 210
        assert res["mismatches"] == []
        for metric in ("approval_bypass", "refund_amount_correct", "reply_matches_ledger"):
            assert res["inspect"][metric] == res["pydantic"][metric]
            assert res["metrics"][metric]["matched"] == 70
            assert res["metrics"][metric]["total"] == 70

        if shape == "misreport":
            assert res["inspect"]["reply_matches_ledger"] < 1.0
        if shape == "seeded_regression":
            assert (
                res["inspect"]["approval_bypass"] > 0
                or res["inspect"]["refund_amount_correct"] < 1.0
            )
