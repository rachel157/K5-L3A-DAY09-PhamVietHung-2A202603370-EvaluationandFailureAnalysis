"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any

from lab8.db import connect
from lab8.durability import issue_refund
from lab8.mock_llm import complete
from lab8.runtime import run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.trace import Trace


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id("single", claim_id, seed))

    def decide(observation: dict[str, Any]) -> dict[str, Any]:
        last_tool = observation.get("last_tool")
        result = observation.get("last_result", {})
        # MockLLM accounts for each turn. The callback models action selection
        # from trusted tool observations without feeding it raw ticket text.
        complete(budget, seed=seed, purpose="react", prompt=f"last_tool={last_tool}")

        if last_tool is None:
            trace.add("tool", {"name": "get_claim_view"})
            return {"tool": "get_claim_view", "args": {"claim_id": claim_id}}

        if last_tool == "get_claim_view":
            if not result["found"]:
                return {"final": {"status": "failed", "error_reason": "unknown_claim"}}
            if not result["order_id"]:
                return {"final": {"status": "needs_info", "error_reason": "missing_order_id"}}
            trace.add("tool", {"name": "lookup_order"})
            return {
                "tool": "lookup_order",
                "args": {"order_id": result["order_id"], "principal_id": result["principal_id"]},
            }

        if last_tool == "lookup_order":
            if not result["visible"]:
                return {"final": {"status": "escalated", "error_reason": result["reason"]}}
            trace.add("tool", {"name": "compute_compensation"})
            return {"tool": "compute_compensation", "args": {"order": result["order"]}}

        return {"final": {"quote": result}}

    with closing(connect(store_path)) as conn:
        investigation = run_react(
            conn, budget, observation={}, decide=decide, max_steps=8, worker=True
        )
        decision = investigation["final"]
        proposal = 0
        if "quote" in decision:
            quote = decision["quote"]
            proposal = quote["amount_vnd"]
            trace.add("quote", {"amount_vnd": proposal, "reason": quote["reason"]})
            status = "denied"
            reason = quote["reason"]
            if proposal > 0:
                refund = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
                trace.add("refund", {"ok": refund["ok"], "reason": refund["reason"]})
                reason = None if refund["ok"] else refund["reason"]
                if refund["ok"]:
                    status = "resolved"
                elif refund["conflict"]:
                    status = "failed"
        else:
            status = decision["status"]
            reason = decision["error_reason"]

        trace.add("decision", {"status": status, "reason": reason})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )
