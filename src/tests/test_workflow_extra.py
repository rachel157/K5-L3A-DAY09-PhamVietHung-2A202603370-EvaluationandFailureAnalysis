"""Extra unit tests for Shape A (workflow) contract and trace safety."""

import time

from lab8.metrics import artifact_blob, check_trace
from lab8.shapes.workflow import run_claim


def test_workflow_unknown_claim_fails_safely_with_valid_trace(public_db):
    # Unknown claim should return status="failed" and still write a valid trace.
    started = time.time()
    result = run_claim("C-UNKNOWN-999", seed=11, store_path=str(public_db)).as_dict()

    assert result["status"] == "failed"
    assert result["proposal_amount"] == 0
    assert result["error_reason"] == "unknown_claim"
    assert result["refund_effects"] == []
    assert check_trace(result, started_at=started) == (True, "ok")


def test_workflow_trace_has_no_canary_secret(public_db):
    # Running a normal claim must produce a valid trace without any canary secret.
    started = time.time()
    result = run_claim("C-001", seed=11, store_path=str(public_db)).as_dict()

    assert result["status"] == "resolved"
    assert check_trace(result, started_at=started) == (True, "ok")
    assert "CANARY_SECRET" not in artifact_blob(result)
