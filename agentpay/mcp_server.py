"""AgentPay VN — MCP Server (Tier 1: Receive).

Exposes 4 payment tools for any MCP-compatible AI agent
(Claude Desktop/Code, custom agents built with the Agent SDK, n8n, etc.).

Quick start::

    pip install agentpay-vn
    export AGENTPAY_API_KEY=ap_test_xxx
    agentpay-mcp           # stdio transport

Or via the module directly::

    python -m agentpay.mcp_server

Declare in your MCP client config (e.g. ``claude_desktop_config.json``)::

    {
      "mcpServers": {
        "agentpay": {
          "command": "python",
          "args": ["-m", "agentpay.mcp_server"],
          "env": {
            "AGENTPAY_API_KEY": "ap_test_xxx",
            "AGENTPAY_BASE_URL": "https://agentpay.servicesai.vn/v1"
          }
        }
      }
    }

Design principles:
- This server is a THIN CLIENT of the REST API — no business logic lives here.
  Losing an MCP key only exposes the ability to create payment requests for one
  tenant; it does not expose bank credentials or money flows.
- Every tool returns structured text that is both human-readable and
  machine-parseable so LLMs can relay it to users and use ids in later steps.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("AGENTPAY_BASE_URL", "https://agentpay.servicesai.vn/v1")
API_KEY = os.environ.get("AGENTPAY_API_KEY", "")
TIMEOUT = httpx.Timeout(15.0)

mcp = FastMCP(
    "agentpay",
    instructions=(
        "AgentPay VN — collect VietQR payments from users inside a conversation. "
        "Standard flow: "
        "1) call create_payment_request to get a QR code; "
        "2) send qr_image_url or checkout_url to the payer; "
        "3) call await_settlement (or check_payment periodically) to learn when "
        "money has arrived; "
        "4) only fulfill the order / unlock content AFTER status=settled. "
        "Never conclude a payment succeeded unless you see status=settled."
    ),
)


def _client() -> httpx.AsyncClient:
    if not API_KEY:
        raise RuntimeError(
            "AGENTPAY_API_KEY environment variable is not set. "
            "Obtain a key from the AgentPay dashboard."
        )
    return httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {API_KEY}"},
    )


def _fmt_vnd(n: int | None) -> str:
    """Format an integer as Vietnamese Dong, e.g. 50000 -> '50.000 ₫'."""
    return f"{n:,.0f}".replace(",", ".") + " ₫" if n is not None else "—"


def _render(pr: dict[str, Any]) -> str:
    """Return a human + machine-readable summary of a payment request."""
    lines = [
        f"Payment request `{pr['id']}` — status: **{pr['status']}**",
        f"Amount: {_fmt_vnd(pr.get('amount'))}"
        + (f" · received: {_fmt_vnd(pr.get('paid_amount'))}" if pr.get("paid_amount") else ""),
        f"Transfer code (pay_code): {pr.get('pay_code')}",
        f"QR image: {pr.get('qr_image_url')}",
        f"Checkout page: {pr.get('checkout_url')}",
        f"Expires at: {pr.get('expires_at')}",
    ]
    if pr.get("settled_at"):
        lines.append(f"Settled at: {pr['settled_at']}")
    if not pr.get("livemode", True):
        lines.append("(SANDBOX — simulated transaction, no real money)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_payment_request(
    amount: int,
    description: str,
    ttl_minutes: int = 60,
    metadata_note: str = "",
) -> str:
    """Create a VietQR payment request.

    Args:
        amount: Amount in VND, minimum 1 000.
        description: Short description for the payer (e.g. "Order #123 — 2 kg coffee").
        ttl_minutes: QR validity window in minutes (5–1 440, default 60).
        metadata_note: Internal note from the agent (order id, conversation id, etc.)
            — echoed back in webhook events.

    Returns:
        id, pay_code, QR image URL, and checkout page URL.  Send ``qr_image_url``
        or ``checkout_url`` to the payer, then call ``await_settlement(id)`` to
        wait for the money to arrive.
    """
    payload: dict[str, Any] = {
        "amount": amount,
        "description": description[:100],
        "ttl_minutes": ttl_minutes,
    }
    if metadata_note:
        payload["metadata"] = {"note": metadata_note}

    async with _client() as c:
        r = await c.post("/payment-requests", json=payload)
        r.raise_for_status()
        return _render(r.json())


@mcp.tool()
async def check_payment(payment_request_id: str) -> str:
    """Check the current status of a payment request.

    Returns:
        One of: pending | settled | underpaid | expired | cancelled,
        along with the amount received so far.
        Only treat a payment as complete when status=settled.
    """
    async with _client() as c:
        r = await c.get(f"/payment-requests/{payment_request_id}")
        r.raise_for_status()
        return _render(r.json())


@mcp.tool()
async def await_settlement(payment_request_id: str, timeout_seconds: int = 180) -> str:
    """Wait for a payment request to be settled (polls on behalf of the agent).

    Polls every 5 seconds until status != pending or the timeout is reached
    (maximum 600 s).  Call this after sending the QR to the payer.
    If the timeout expires while still pending, ask the user whether to keep
    waiting or cancel.

    Args:
        payment_request_id: The ``id`` returned by ``create_payment_request``.
        timeout_seconds: How long to wait in seconds (10–600, default 180).
    """
    timeout_seconds = min(max(timeout_seconds, 10), 600)
    deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds

    async with _client() as c:
        while True:
            r = await c.get(f"/payment-requests/{payment_request_id}")
            r.raise_for_status()
            pr = r.json()
            if pr["status"] != "pending":
                return _render(pr)
            if datetime.now(timezone.utc).timestamp() >= deadline:
                return (
                    f"Timed out after {timeout_seconds}s — payment request "
                    f"`{payment_request_id}` is still **pending** (no payment detected). "
                    "You can call await_settlement again to keep waiting, or check_payment "
                    "later."
                )
            await asyncio.sleep(5)


@mcp.tool()
async def list_recent_payments(limit: int = 10) -> str:
    """List the most recently settled transactions (quick reconciliation).

    Args:
        limit: Number of transactions to return (1–50, default 10).
    """
    limit = min(max(limit, 1), 50)
    async with _client() as c:
        r = await c.get("/transactions", params={"limit": limit})
        r.raise_for_status()
        data = r.json().get("data", [])

    if not data:
        return "No settled transactions found."
    lines = [f"{len(data)} most recent settled transactions:"]
    for t in data:
        lines.append(
            f"- {t['settled_at']} · {_fmt_vnd(t['amount'])} · "
            f"pr={t['payment_request_id']} · bank_ref={t.get('bank_ref', '—')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the ``agentpay-mcp`` console script."""
    mcp.run()  # stdio transport — the MCP client manages the process lifecycle


if __name__ == "__main__":
    main()
