"""Unit tests for apps/etsy/src/etsy_mcp/schemas.py.

Focus: the partial_success_envelope `success` field contract.

Cycle 1 review fix: all-failure must NOT masquerade as success. Previously
the envelope reported success=True unconditionally, which deceived callers.

Cycle 2 review P0-B: the "diverged" status also counts as success. The
server accepted the update but normalized a value — the item did NOT fail,
it just landed differently than requested. The test below is a regression
guard against reverting that fix.
"""

from __future__ import annotations

from etsy_mcp.schemas import partial_success_envelope


def test_partial_success_envelope_all_failed_returns_success_false() -> None:
    env = partial_success_envelope(
        failed=[
            {"index": 0, "error": "x"},
            {"index": 1, "error": "y"},
        ],
    )
    assert env["success"] is False
    assert "error" in env
    assert "0 of 2 items succeeded" in env["error"]
    assert env["data"]["failed_count"] == 2
    assert env["data"]["successful"] == 0


def test_partial_success_envelope_all_succeeded_returns_success_true() -> None:
    env = partial_success_envelope(
        created=[
            {"index": 0, "status": "success"},
            {"index": 1, "status": "success"},
        ],
    )
    assert env["success"] is True
    assert env["data"]["successful"] == 2
    assert env["data"]["failed_count"] == 0


def test_partial_success_envelope_partial_returns_success_true() -> None:
    env = partial_success_envelope(
        created=[{"index": 0, "status": "success"}],
        failed=[{"index": 1, "error": "nope"}],
    )
    assert env["success"] is True


def test_partial_success_envelope_empty_returns_success_true() -> None:
    env = partial_success_envelope()
    assert env["success"] is True


def test_partial_success_envelope_diverged_status_counts_as_success() -> None:
    env = partial_success_envelope(
        updated=[{"index": 0, "status": "diverged"}],
    )
    assert env["success"] is True
