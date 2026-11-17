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
    for args in [(5, 6, 1), (5, 2, 0), (3, 1, 4)]:
        with pytest.raises(ValueError):
            stats.pass_at_k(*args)


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

    # Empty overlap between PR and baseline slice items does not crash paired_bootstrap
    base_no_slice = _report([dict(r, slices=[]) for r in ROWS], {"pass_rate": 1.0})
    spec_drop = dict(SPEC, slices=[{"name": "denial", "metric": "pass_rate", "min": 0.5,
                                    "no_significant_drop": True, "blocking": True}])
    blocked_empty, _ = gate.slice_check(_report(copy.deepcopy(ROWS), {"pass_rate": 1.0}), base_no_slice, spec_drop)
    assert blocked_empty == ["slice:denial/pass_rate"]
