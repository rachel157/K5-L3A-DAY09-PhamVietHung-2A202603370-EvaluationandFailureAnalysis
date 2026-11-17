"""Shape C — orchestrator plus read-only investigators. Student work.

1. Build a handoff with `lab8.handoff.make_handoff`. Allowed tools are read-only.
   Never put parent_secret, raw headers, or the full claim row into facts.
2. `lab8.runtime.run_readonly_investigators` runs those tools.
3. The orchestrator quotes from the investigator's order view and calls
   `durability.issue_refund`. Investigators have no write registry.
   Pass the full quote; the host subtracts earlier refunds on the same order.
   `lookup_refund_history` is a read-only tool you may hand to an investigator.
4. Trace the sanitized handoff, not the parent context.

An LLM summary of the parent context is not a sanitizer. Use the allowlist.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from lab8.compensation import quote
from lab8.config_loader import as_of
from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.handoff import make_handoff
from lab8.mock_llm import complete
from lab8.runtime import run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish, safe_dump
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

DEFAULT_INVESTIGATOR_TOOLS: tuple[str, ...] = (
    "lookup_order",
    "lookup_policy",
    "lookup_refund_history",
    "compute_compensation",
)


def build_handoff(
    claim_id: str,
    *,
    seed: int,
    facts: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
) -> dict[str, Any]:
    return make_handoff(
        request_id=f"REQ-{claim_id}-s{seed}",
        claim_id=claim_id,
        task="investigate_order_and_policy",
        facts=dict(facts or {}),
        allowed_tools=list(allowed_tools) if allowed_tools is not None else list(DEFAULT_INVESTIGATOR_TOOLS),
    )


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(
    conn: sqlite3.Connection,
    claim_id: str,
    *,
    seed: int,
    crash_at: str | None,
) -> RunResult:
    budget = Budget()
    run_id = make_run_id("orchestrator", claim_id, seed)
    trace = Trace(run_id)

    claim_view = get_claim_view(conn, claim_id)
    budget.add_tool(tool_cost())

    if not claim_view.get("found"):
        trace.add("error", {"reason": "unknown_claim"})
        return finish(
            conn,
            shape="orchestrator",
            claim_id=claim_id,
            seed=seed,
            status="failed",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="unknown_claim",
        )

    if not claim_view.get("order_id"):
        complete(budget, seed=seed, purpose="draft", prompt=f"claim={claim_id};status=needs_info")
        trace.add("decision", {"status": "needs_info", "reason": "missing_order_id"})
        return finish(
            conn,
            shape="orchestrator",
            claim_id=claim_id,
            seed=seed,
            status="needs_info",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="missing_order_id",
        )

    complete(budget, seed=seed, purpose="plan", prompt=f"claim={claim_id};order={claim_view['order_id']}")

    handoff = build_handoff(claim_id, seed=seed)
    trace.add("handoff", safe_dump(handoff))

    investigated = run_readonly_investigators(conn, budget, handoff, principal_id=claim_view["principal_id"])
    order_view = investigated["tools"].get("lookup_order") or {}
    policy_view = investigated["tools"].get("lookup_policy") or {}
    refund_history = investigated["tools"].get("lookup_refund_history") or {}

    trace.add(
        "investigator",
        safe_dump({
            "claim_view": investigated["claim_view"],
            "lookup_order": order_view,
            "refund_history": refund_history,
            "policy_ids": [p["policy_id"] for p in (policy_view.get("policies") or [])],
        }),
    )

    if not order_view.get("visible"):
        complete(budget, seed=seed, purpose="draft", prompt=f"claim={claim_id};status=escalated")
        return finish(
            conn,
            shape="orchestrator",
            claim_id=claim_id,
            seed=seed,
            status="escalated",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=order_view.get("reason"),
        )

    quote_obj = quote(
        order_view["order"],
        policy_view.get("policies") or [],
        as_of=str(policy_view.get("as_of") or as_of()),
    )
    proposal = int(quote_obj.amount_vnd)
    trace.add(
        "quote",
        {
            "amount_vnd": proposal,
            "reason": quote_obj.reason,
            "clause_ids": quote_obj.clause_ids,
            "parts": quote_obj.parts,
        },
    )
    complete(budget, seed=seed, purpose="draft", prompt=f"claim={claim_id};proposal={proposal}")

    if proposal <= 0:
        return finish(
            conn,
            shape="orchestrator",
            claim_id=claim_id,
            seed=seed,
            status="denied",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=quote_obj.reason,
        )

    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    trace.add(
        "refund_outcome",
        {
            "ok": bool(outcome["ok"]),
            "reason": outcome["reason"],
            "conflict": bool(outcome["conflict"]),
            "committed_vnd": (outcome.get("effect") or {}).get("amount_vnd"),
        },
    )

    if not outcome["ok"]:
        status = "failed" if outcome["conflict"] else "denied"
        return finish(
            conn,
            shape="orchestrator",
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=outcome["reason"],
        )

    return finish(
        conn,
        shape="orchestrator",
        claim_id=claim_id,
        seed=seed,
        status="resolved",
        proposal_amount=proposal,
        budget=budget,
        trace=trace,
        error_reason=None,
    )
