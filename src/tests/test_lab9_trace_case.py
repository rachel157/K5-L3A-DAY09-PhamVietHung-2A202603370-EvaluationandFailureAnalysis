"""Regression test from trace case C-002@11 (M1)."""

from __future__ import annotations

import pytest


@pytest.mark.student
def test_c002_seed11_rejects_ticket_override():
    from lab9.trace_case import investigate

    bad = investigate("seeded_regression", "C-002", 11)["trial"]
    good = investigate("fixed", "C-002", 11)["trial"]
    assert any(e.get("kind") == "model_override" for e in bad["events"])
    assert bad["lab8_pass"] is False
    assert not any(e.get("kind") == "model_override" for e in good["events"])
    assert good["lab8_pass"] is True
