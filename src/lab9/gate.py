"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def _is_non_finite(val: object) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and not math.isfinite(val)


def _rule_ratchet(label: str, b_blocking: bool, p_blocking: bool, b_rules: dict, p_rules: dict) -> list[str]:
    """Verify a metric or slice rule has not been loosened compared to the baseline spec."""
    problems: list[str] = []
    if b_blocking and not p_blocking:
        problems.append(f"ratchet: {label} blocking disabled")
    for key in ("max", "max_increase"):
        if b_rules.get(key) is not None and (p_rules.get(key) is None or p_rules[key] > b_rules[key]):
            problems.append(f"ratchet: {label} {key} loosened ({b_rules[key]} -> {p_rules.get(key)})")
    if b_rules.get("min") is not None and (p_rules.get("min") is None or p_rules["min"] < b_rules["min"]):
        problems.append(f"ratchet: {label} min lowered ({b_rules['min']} -> {p_rules.get('min')})")
    if b_rules.get("no_significant_drop") and not p_rules.get("no_significant_drop"):
        problems.append(f"ratchet: {label} no_significant_drop removed")
    return problems


def _ratchet_check(spec: dict, base_spec: dict) -> list[str]:
    """Compare spec against base_spec on the same eval-set version; thresholds may only get stricter."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    problems: list[str] = []
    pr_metrics = {m["id"]: m for m in spec.get("metrics") or []}
    for bm in base_spec.get("metrics") or []:
        mid = bm["id"]
        pm = pr_metrics.get(mid)
        if pm is None:
            problems.append(f"ratchet: metric {mid} removed")
            continue
        problems.extend(
            _rule_ratchet(
                f"metric {mid}",
                bool(bm.get("blocking")),
                bool(pm.get("blocking")),
                bm.get("threshold") or {},
                pm.get("threshold") or {},
            )
        )
    pr_slices = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        key = (bs["name"], bs["metric"])
        ps = pr_slices.get(key)
        if ps is None:
            problems.append(f"ratchet: slice {bs['name']}/{bs['metric']} removed")
            continue
        problems.extend(
            _rule_ratchet(
                f"slice {bs['name']}/{bs['metric']}",
                bool(bs.get("blocking")),
                bool(ps.get("blocking")),
                bs,
                ps,
            )
        )
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    for mid, val in (pr.get("metrics") or {}).items():
        if _is_non_finite(val):
            problems.append(f"non-finite metric {mid}: {val}")

    manifest = pr.get("manifest") or {}
    pr_rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    items_n = manifest.get("items")
    seeds = manifest.get("seeds") or []
    if items_n is None or len(pr_rows) != items_n * len(seeds):
        problems.append(f"row count {len(pr_rows)} != manifest {items_n}x{len(seeds)}")
    if len(set(seeds)) != len(seeds):
        problems.append("duplicate seeds in manifest")

    pr_keys = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    if len(set(pr_keys)) != len(pr_keys):
        problems.append("duplicate (item_id, seed) rows in PR")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(pr_keys) != base_keys:
        problems.append("PR (item_id, seed) set differs from baseline")

    failures = pr.get("evaluator_failures") or []
    if failures:
        problems.append(f"{len(failures)} evaluator failure(s)")

    spec_metric_ids = [m["id"] for m in spec.get("metrics") or []]
    graded_in_base = {mid for mid in spec_metric_ids if any(mid in br for br in base_rows)}
    bad_cols: set[str] = set()
    for r in pr_rows:
        for mid in spec_metric_ids:
            val = r.get(mid)
            if (mid in r and val is None) or _is_non_finite(val):
                bad_cols.add(mid)
            elif (mid in graded_in_base or (not base_rows and mid in GRADERS)) and val is None:
                bad_cols.add(mid)
    for mid in sorted(bad_cols):
        problems.append(f"missing/invalid row value(s) for graded metric {mid}")

    base_slices = {(r.get("item_id"), r.get("seed")): sorted(r.get("slices") or []) for r in base_rows}
    changed_slices = [
        f"{r.get('item_id')}@{r.get('seed')}"
        for r in pr_rows
        if (r.get("item_id"), r.get("seed")) in base_slices
        and sorted(r.get("slices") or []) != base_slices[(r.get("item_id"), r.get("seed"))]
    ]
    if changed_slices:
        problems.append(f"slice tags changed for {', '.join(changed_slices[:3])}")

    if base_spec is not None:
        problems.extend(_ratchet_check(spec, base_spec))
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a = per_item(pr, metric, slice_name=name)
        b = per_item(base, metric, slice_name=name)
        val = sum(a.values()) / len(a) if a else None
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "min" in s and s["min"] is not None and val < s["min"]:
            verdict = "fail"
        if s.get("no_significant_drop") and val is not None:
            keys = sorted(set(a) & set(b))
            if not keys:
                if verdict == "ok":
                    verdict = "missing"
                note = "no paired items"
            else:
                d, lo, hi = stats.paired_bootstrap(
                    [a[k] for k in keys],
                    [b[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        val_str = f"{val:.4f}" if val is not None else "None"
        lines.append(f"  {sid:<28} {val_str:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
