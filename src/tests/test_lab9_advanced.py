"""M5-M7 self-check (Advanced/Expert). Run: python -m pytest -q -m student -o addopts= -k advanced
Public vectors only; the instructor grades with hidden ones."""
import copy
import math

import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def stats():
    from lab9 import stats

    return stats


@pytest.mark.parametrize("n,c,k,want", [(5, 5, 5, 1.0), (5, 0, 1, 0.0), (5, 2, 1, 0.4), (10, 3, 3, 1 - 35 / 120)])
def test_pass_at_k(stats, n, c, k, want):
    assert math.isclose(stats.pass_at_k(n, c, k), want, abs_tol=1e-9)


@pytest.mark.parametrize("n,c,k,want", [(5, 5, 5, 1.0), (5, 4, 5, 0.0), (5, 4, 3, 0.4), (10, 8, 2, 28 / 45)])
def test_pass_hat_k(stats, n, c, k, want):
    assert math.isclose(stats.pass_hat_k(n, c, k), want, abs_tol=1e-9)


def test_pass_k_rejects_bad_args(stats):
    for args in [(5, 6, 1), (5, 2, 0), (3, 1, 4), (5, -1, 1), (0, 0, 1)]:
        with pytest.raises(ValueError):
            stats.pass_at_k(*args)
        with pytest.raises(ValueError):
            stats.pass_hat_k(*args)


def _report(rows, metrics, items=4, seeds=(1, 2)):
    return {"manifest": {"eval_set_sha": "x", "items": items, "seeds": list(seeds)},
            "rows": rows, "metrics": metrics, "evaluator_failures": []}


ROWS = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["denial"] if i < 2 else []}
        for i in range(4) for s in (1, 2)]
SPEC = {"eval_set_version": "v2", "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                                               "threshold": {"min": 0.8}}]}


def test_integrity_flags_nan_and_dropped_rows():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    assert gate.integrity_check(base, base, SPEC) == []
    nan = _report(copy.deepcopy(ROWS), {"pass_rate": float("nan")})
    assert gate.integrity_check(nan, base, SPEC)
    dropped = _report(copy.deepcopy(ROWS[:-1]), {"pass_rate": 1.0})
    assert gate.integrity_check(dropped, base, SPEC)


def test_integrity_flags_loosened_spec():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    loose = copy.deepcopy(SPEC)
    loose["metrics"][0]["threshold"]["min"] = 0.5
    assert gate.integrity_check(base, base, loose, SPEC)
    assert gate.integrity_check(base, base, SPEC, SPEC) == []


def test_integrity_flags_duplicate_row_keeping_row_count():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    dup_rows = copy.deepcopy(ROWS[:-1]) + [copy.deepcopy(ROWS[0])]
    assert len(dup_rows) == len(ROWS)
    assert gate.integrity_check(_report(dup_rows, {"pass_rate": 1.0}), base, SPEC)

    # Cherry-picked seeds with manifest["seeds"] rewritten to match row count
    cherry_rows = [copy.deepcopy(r) for r in ROWS if r["seed"] == 1]
    cherry = _report(cherry_rows, {"pass_rate": 1.0}, items=4, seeds=(1,))
    assert gate.integrity_check(cherry, base, SPEC)


def test_integrity_flags_none_metric_and_evaluator_failures():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    none_rows = copy.deepcopy(ROWS)
    none_rows[0]["pass_rate"] = None
    assert gate.integrity_check(_report(none_rows, {"pass_rate": 1.0}), base, SPEC)

    dropped_col = copy.deepcopy(ROWS)
    del dropped_col[0]["pass_rate"]
    assert gate.integrity_check(_report(dropped_col, {"pass_rate": 1.0}), base, SPEC)

    inf_rep = _report(copy.deepcopy(ROWS), {"pass_rate": float("inf")})
    assert gate.integrity_check(inf_rep, base, SPEC)

    fail_rep = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    fail_rep["evaluator_failures"] = ["E-001@11:x"]
    assert gate.integrity_check(fail_rep, base, SPEC)


def test_integrity_flags_slice_relabelling_and_ratchet_drop():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    relabeled = copy.deepcopy(ROWS)
    relabeled[0]["slices"] = []
    assert gate.integrity_check(_report(relabeled, {"pass_rate": 1.0}), base, SPEC)

    strict_spec = {
        "eval_set_version": "v2",
        "metrics": [
            {"id": "approval_bypass", "kind": "safety", "blocking": True, "threshold": {"max": 0}},
            {"id": "pass_rate", "kind": "capability", "blocking": True,
             "threshold": {"min": 0.85, "no_significant_drop": True}},
            {"id": "cost_per_success", "kind": "system", "blocking": False,
             "threshold": {"max_increase": 0.10}},
        ],
        "slices": [
            {"name": "denial", "metric": "pass_rate", "min": 0.90, "no_significant_drop": True, "blocking": True},
        ],
    }
    base_full_rows = [dict(r, approval_bypass=False) for r in copy.deepcopy(ROWS)]
    base_full = _report(base_full_rows, {"approval_bypass": 0, "pass_rate": 1.0, "cost_per_success": 50.0})
    assert gate.integrity_check(base_full, base_full, strict_spec, strict_spec) == []

    # Drop no_significant_drop on metric
    s1 = copy.deepcopy(strict_spec)
    del s1["metrics"][1]["threshold"]["no_significant_drop"]
    assert gate.integrity_check(base_full, base_full, s1, strict_spec)

    # Remove a metric completely
    s2 = copy.deepcopy(strict_spec)
    s2["metrics"] = s2["metrics"][1:]
    assert gate.integrity_check(base_full, base_full, s2, strict_spec)

    # Flip blocking True -> False on metric
    s3 = copy.deepcopy(strict_spec)
    s3["metrics"][1]["blocking"] = False
    assert gate.integrity_check(base_full, base_full, s3, strict_spec)

    # Raise max / max_increase
    s4 = copy.deepcopy(strict_spec)
    s4["metrics"][0]["threshold"]["max"] = 1
    assert gate.integrity_check(base_full, base_full, s4, strict_spec)
    s5 = copy.deepcopy(strict_spec)
    s5["metrics"][2]["threshold"]["max_increase"] = 0.25
    assert gate.integrity_check(base_full, base_full, s5, strict_spec)

    # Slice ratchet drops: remove slice, drop no_significant_drop, lower min, flip blocking
    s6 = copy.deepcopy(strict_spec)
    s6["slices"] = []
    assert gate.integrity_check(base_full, base_full, s6, strict_spec)
    s7 = copy.deepcopy(strict_spec)
    del s7["slices"][0]["no_significant_drop"]
    assert gate.integrity_check(base_full, base_full, s7, strict_spec)
    s8 = copy.deepcopy(strict_spec)
    s8["slices"][0]["min"] = 0.7
    assert gate.integrity_check(base_full, base_full, s8, strict_spec)
    s9 = copy.deepcopy(strict_spec)
    s9["slices"][0]["blocking"] = False
    assert gate.integrity_check(base_full, base_full, s9, strict_spec)

    # Different eval_set_version permits new baseline thresholds
    v3_spec = copy.deepcopy(s1)
    v3_spec["eval_set_version"] = "v3"
    assert gate.integrity_check(base_full, base_full, v3_spec, strict_spec) == []


def test_slice_check_blocks_a_slice_below_floor():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    rows = copy.deepcopy(ROWS)
    for r in rows:
        if "denial" in r["slices"] and r["seed"] == 1:
            r["pass_rate"] = False
    spec = dict(SPEC, slices=[{"name": "denial", "metric": "pass_rate", "min": 0.9, "blocking": True}])
    blocked, _ = gate.slice_check(_report(rows, {"pass_rate": 0.75}), base, spec)
    assert blocked == ["slice:denial/pass_rate"]


def test_slice_check_no_significant_drop_blocks_above_floor():
    from lab9 import gate

    rows = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["money_movement"]}
            for i in range(4) for s in (1, 2)]
    base = _report(copy.deepcopy(rows), {"pass_rate": 1.0})
    pr_rows = copy.deepcopy(rows)
    for r in pr_rows:
        if r["seed"] == 1:
            r["pass_rate"] = False
    spec = dict(SPEC, slices=[{"name": "money_movement", "metric": "pass_rate", "min": 0.5,
                               "no_significant_drop": True, "blocking": True}])
    blocked, lines = gate.slice_check(_report(pr_rows, {"pass_rate": 0.5}), base, spec)
    assert blocked == ["slice:money_movement/pass_rate"]
    assert len(lines) == 1


def test_slice_check_non_blocking_and_missing_edges():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    rows = copy.deepcopy(ROWS)
    for r in rows:
        if "denial" in r["slices"]:
            r["pass_rate"] = False

    # Non-blocking slice violation warns without blocking
    spec_warn = dict(SPEC, slices=[{"name": "denial", "metric": "pass_rate", "min": 0.9, "blocking": False}])
    blocked, lines = gate.slice_check(_report(rows, {"pass_rate": 0.5}), base, spec_warn)
    assert blocked == []
    assert any("warn" in line for line in lines)

    # Missing slice in PR blocks if blocking=True, skips cleanly if blocking=False
    spec_missing = dict(SPEC, slices=[{"name": "adversarial", "metric": "pass_rate", "min": 0.9, "blocking": True}])
    blocked_missing, lines_missing = gate.slice_check(_report(rows, {"pass_rate": 0.5}), base, spec_missing)
    assert blocked_missing == ["slice:adversarial/pass_rate"]
    assert any("MISSING" in line for line in lines_missing)

    spec_missing_nb = dict(SPEC, slices=[{"name": "adversarial", "metric": "pass_rate", "min": 0.9, "blocking": False}])
    blocked_missing_nb, lines_missing_nb = gate.slice_check(_report(rows, {"pass_rate": 0.5}), base, spec_missing_nb)
    assert blocked_missing_nb == []
    assert any("MISSING" in line for line in lines_missing_nb)

    # Empty overlap between PR and baseline slice items does not crash paired_bootstrap
    base_no_slice = _report([dict(r, slices=[]) for r in ROWS], {"pass_rate": 1.0})
    spec_drop = dict(SPEC, slices=[{"name": "denial", "metric": "pass_rate", "min": 0.5,
                                    "no_significant_drop": True, "blocking": True}])
    blocked_empty, _ = gate.slice_check(_report(copy.deepcopy(ROWS), {"pass_rate": 1.0}), base_no_slice, spec_drop)
    assert blocked_empty == ["slice:denial/pass_rate"]


def test_integrity_rejects_malformed_manifest_and_nonfinite_ratchet():
    from lab9 import gate

    single_row = [copy.deepcopy(ROWS[0])]
    single_base = _report(single_row, {"pass_rate": 1.0}, items=1, seeds=(1,))
    bool_items = _report(copy.deepcopy(single_row), {"pass_rate": 1.0}, items=True, seeds=(1,))
    assert gate.integrity_check(bool_items, single_base, SPEC)

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    none_seeds = _report([], {"pass_rate": 1.0}, items=0, seeds=())
    none_seeds["manifest"]["seeds"] = None
    assert any("manifest" in p or "seeds" in p for p in gate.integrity_check(none_seeds, none_seeds, SPEC))

    nan_min_spec = copy.deepcopy(SPEC)
    nan_min_spec["metrics"][0]["threshold"]["min"] = float("nan")
    assert gate.integrity_check(base, base, nan_min_spec, SPEC)

    max_spec = {"eval_set_version": "v2", "metrics": [{"id": "pass_rate", "kind": "safety", "blocking": True,
                                                       "threshold": {"max": 0}}]}
    nan_max_spec = copy.deepcopy(max_spec)
    nan_max_spec["metrics"][0]["threshold"]["max"] = float("nan")
    assert gate.integrity_check(base, base, nan_max_spec, max_spec)
