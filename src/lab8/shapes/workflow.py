"""Shape A — deterministic workflow. Student work.
... (giữ nguyên docstring gốc ở đầu file) ...
"""

from __future__ import annotations

import sqlite3

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.mock_llm import complete
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import compute_compensation, get_claim_view, lookup_order, tool_cost
from lab8.trace import Trace


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    # Open the database connection and make sure it always closes at the end.
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
    # Create a budget to count tool/model calls and a trace to record steps.
    budget = Budget()
    run_id = make_run_id("workflow", claim_id, seed)
    trace = Trace(run_id)

    # Step 1: Read safe claim fields (no secret fields).
    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim.get("found"):
        trace.add("error", {"reason": "unknown_claim"})
        return finish(
            conn,
            shape="workflow",
            claim_id=claim_id,
            seed=seed,
            status="failed",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="unknown_claim",
        )

    # Step 2: Check if order_id exists. If missing, ask for more info.
    order_id = claim.get("order_id")
    if not order_id:
        complete(budget, seed=seed, purpose="draft", prompt="needs_info")
        trace.add("decision", {"status": "needs_info"})
        return finish(
            conn,
            shape="workflow",
            claim_id=claim_id,
            seed=seed,
            status="needs_info",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="missing_order_id",
        )

    # Step 3: Look up the order using principal_id to check ownership.
    budget.add_tool(tool_cost())
    order_view = lookup_order(conn, order_id, claim["principal_id"])
    trace.add(
        "lookup_order",
        {"visible": order_view.get("visible"), "reason": order_view.get("reason")},
    )
    if not order_view.get("visible"):
        complete(budget, seed=seed, purpose="draft", prompt="escalated")
        return finish(
            conn,
            shape="workflow",
            claim_id=claim_id,
            seed=seed,
            status="escalated",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=order_view.get("reason"),
        )

    # Step 4: Calculate refund money using code (never trust numbers in ticket text).
    budget.add_tool(tool_cost())
    quote_payload = compute_compensation(conn, order_view["order"])
    proposal = int(quote_payload["amount_vnd"])
    trace.add("quote", quote_payload)

    # Use MockLLM only to write the reply message, not to decide the money.
    complete(budget, seed=seed, purpose="draft", prompt=f"proposal={proposal}")

    # Step 5: If quote is 0, deny directly and do not call issue_refund.
    if proposal <= 0:
        return finish(
            conn,
            shape="workflow",
            claim_id=claim_id,
            seed=seed,
            status="denied",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=quote_payload.get("reason"),
        )

    # Step 6: Send the FULL quote to the host. Let the host check approval and cap.
    # Pass crash_at and do not hide InjectedCrash so crash tests can verify safety.
    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    # Step 7: Return final status based on host outcome.
    # Keep proposal_amount as the full quote even if the host pays less or denies.
    if not outcome["ok"]:
        status = "failed" if outcome["conflict"] else "denied"
        return finish(
            conn,
            shape="workflow",
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
        shape="workflow",
        claim_id=claim_id,
        seed=seed,
        status="resolved",
        proposal_amount=proposal,
        budget=budget,
        trace=trace,
        error_reason=None,
    )
