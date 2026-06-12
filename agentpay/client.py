"""AgentPay VN — Python SDK (sync & async).

Provides both a synchronous ``AgentPayClient`` and an asynchronous
``AsyncAgentPayClient`` built on ``httpx``.  Both classes expose the same
methods so you can swap them without changing call-sites.

Usage (sync)::

    from agentpay.client import AgentPayClient

    client = AgentPayClient("ap_live_xxx")
    pr = client.create_payment_request(amount=50_000, description="Order #1")
    print(pr["checkout_url"])

Usage (async)::

    from agentpay.client import AsyncAgentPayClient, await_settlement

    async with AsyncAgentPayClient("ap_live_xxx") as client:
        pr = await client.create_payment_request(amount=50_000, description="Order #1")
        result = await await_settlement(client, pr["id"], timeout=120)
        print(result["status"])  # "settled"
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

import httpx

from agentpay import BASE_URL

_DEFAULT_TIMEOUT = httpx.Timeout(15.0)


class AgentPayClient:
    """Synchronous AgentPay client backed by ``httpx.Client``.

    Args:
        api_key: Your ``ap_live_*`` or ``ap_test_*`` API key.
        base_url: Override the API base URL (useful for self-hosting).
        timeout: Request timeout in seconds (default 15).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "AgentPayClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Payment requests
    # ------------------------------------------------------------------

    def create_payment_request(
        self,
        amount: int,
        description: str,
        ttl_minutes: int = 60,
        metadata: Optional[dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new VietQR payment request.

        Args:
            amount: Amount in VND (minimum 1 000).
            description: Short description shown to the payer (max 100 chars).
            ttl_minutes: QR validity window in minutes (5–1 440, default 60).
            metadata: Arbitrary key/value pairs echoed back in webhook events.
            idempotency_key: Client-generated key to deduplicate retries (24 h window).

        Returns:
            Payment request object; key fields: ``id``, ``qr_image_url``,
            ``checkout_url``, ``pay_code``, ``status``, ``expires_at``.
        """
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        payload: dict[str, Any] = {
            "amount": amount,
            "description": description[:100],
            "ttl_minutes": ttl_minutes,
        }
        if metadata:
            payload["metadata"] = metadata
        r = self._client.post("/payment-requests", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

    def get_payment_request(self, payment_request_id: str) -> dict[str, Any]:
        """Fetch the current state of a payment request.

        Args:
            payment_request_id: The ``id`` field from ``create_payment_request``.

        Returns:
            Payment request object with up-to-date ``status``.
        """
        r = self._client.get(f"/payment-requests/{payment_request_id}")
        r.raise_for_status()
        return r.json()

    def cancel_payment_request(self, payment_request_id: str) -> dict[str, Any]:
        """Cancel a pending payment request.

        Args:
            payment_request_id: The ``id`` of a ``pending`` payment request.

        Returns:
            Updated payment request with ``status = "cancelled"``.

        Raises:
            httpx.HTTPStatusError: 409 if the request is not ``pending``.
        """
        r = self._client.post(f"/payment-requests/{payment_request_id}/cancel")
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def list_transactions(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """List settled transactions for reconciliation.

        Args:
            since: Only return transactions settled at or after this timestamp.
            limit: Maximum number of results (1–200, default 50).
            cursor: Pagination cursor from the previous response's ``next_cursor``.

        Returns:
            Dict with ``data`` (list of transaction objects) and optional
            ``next_cursor`` for the next page.
        """
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since.isoformat()
        if cursor:
            params["cursor"] = cursor
        r = self._client.get("/transactions", params=params)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Webhook endpoints
    # ------------------------------------------------------------------

    def register_webhook(
        self,
        url: str,
        events: list[str],
    ) -> dict[str, Any]:
        """Register a URL to receive webhook events.

        Args:
            url: HTTPS endpoint that will receive POST requests.
            events: List of event types to subscribe to.  Allowed values:
                ``payment.settled``, ``payment.underpaid``, ``payment.expired``.

        Returns:
            Dict with ``id`` and ``secret`` (shown once — store it immediately).
            Verify incoming webhooks by checking ``HMAC-SHA256(secret, raw_body)``
            against the ``AgentPay-Signature`` request header.
        """
        r = self._client.post("/webhook-endpoints", json={"url": url, "events": events})
        r.raise_for_status()
        return r.json()


class AsyncAgentPayClient:
    """Asynchronous AgentPay client backed by ``httpx.AsyncClient``.

    Supports use as an async context manager::

        async with AsyncAgentPayClient(api_key) as client:
            pr = await client.create_payment_request(...)

    Args:
        api_key: Your ``ap_live_*`` or ``ap_test_*`` API key.
        base_url: Override the API base URL (useful for self-hosting).
        timeout: Request timeout in seconds (default 15).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncAgentPayClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Payment requests
    # ------------------------------------------------------------------

    async def create_payment_request(
        self,
        amount: int,
        description: str,
        ttl_minutes: int = 60,
        metadata: Optional[dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new VietQR payment request.

        Args:
            amount: Amount in VND (minimum 1 000).
            description: Short description shown to the payer (max 100 chars).
            ttl_minutes: QR validity window in minutes (5–1 440, default 60).
            metadata: Arbitrary key/value pairs echoed back in webhook events.
            idempotency_key: Client-generated key to deduplicate retries (24 h window).

        Returns:
            Payment request object; key fields: ``id``, ``qr_image_url``,
            ``checkout_url``, ``pay_code``, ``status``, ``expires_at``.
        """
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        payload: dict[str, Any] = {
            "amount": amount,
            "description": description[:100],
            "ttl_minutes": ttl_minutes,
        }
        if metadata:
            payload["metadata"] = metadata
        r = await self._client.post("/payment-requests", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

    async def get_payment_request(self, payment_request_id: str) -> dict[str, Any]:
        """Fetch the current state of a payment request.

        Args:
            payment_request_id: The ``id`` field from ``create_payment_request``.

        Returns:
            Payment request object with up-to-date ``status``.
        """
        r = await self._client.get(f"/payment-requests/{payment_request_id}")
        r.raise_for_status()
        return r.json()

    async def cancel_payment_request(self, payment_request_id: str) -> dict[str, Any]:
        """Cancel a pending payment request.

        Args:
            payment_request_id: The ``id`` of a ``pending`` payment request.

        Returns:
            Updated payment request with ``status = "cancelled"``.

        Raises:
            httpx.HTTPStatusError: 409 if the request is not ``pending``.
        """
        r = await self._client.post(f"/payment-requests/{payment_request_id}/cancel")
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    async def list_transactions(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """List settled transactions for reconciliation.

        Args:
            since: Only return transactions settled at or after this timestamp.
            limit: Maximum number of results (1–200, default 50).
            cursor: Pagination cursor from the previous response's ``next_cursor``.

        Returns:
            Dict with ``data`` (list of transaction objects) and optional
            ``next_cursor`` for the next page.
        """
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since.isoformat()
        if cursor:
            params["cursor"] = cursor
        r = await self._client.get("/transactions", params=params)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Webhook endpoints
    # ------------------------------------------------------------------

    async def register_webhook(
        self,
        url: str,
        events: list[str],
    ) -> dict[str, Any]:
        """Register a URL to receive webhook events.

        Args:
            url: HTTPS endpoint that will receive POST requests.
            events: List of event types to subscribe to.  Allowed values:
                ``payment.settled``, ``payment.underpaid``, ``payment.expired``.

        Returns:
            Dict with ``id`` and ``secret`` (shown once — store it immediately).
            Verify incoming webhooks by checking ``HMAC-SHA256(secret, raw_body)``
            against the ``AgentPay-Signature`` request header.
        """
        r = await self._client.post(
            "/webhook-endpoints", json={"url": url, "events": events}
        )
        r.raise_for_status()
        return r.json()


# ------------------------------------------------------------------
# Standalone helper
# ------------------------------------------------------------------

async def await_settlement(
    client: AsyncAgentPayClient,
    payment_request_id: str,
    timeout: int = 180,
    poll_interval: int = 5,
) -> dict[str, Any]:
    """Poll a payment request until it leaves ``pending`` state or times out.

    Designed to be awaited immediately after sending the QR to the payer.

    Args:
        client: An ``AsyncAgentPayClient`` instance (must still be open).
        payment_request_id: The ``id`` returned by ``create_payment_request``.
        timeout: Maximum seconds to wait (default 180, max enforced by caller).
        poll_interval: Seconds between polls (default 5).

    Returns:
        The final payment request object.  Check ``result["status"]``:
        ``"settled"`` means money arrived; anything else means it did not.

    Example::

        result = await await_settlement(client, pr["id"], timeout=120)
        if result["status"] == "settled":
            deliver_order()
    """
    import time

    deadline = time.monotonic() + timeout
    while True:
        pr = await client.get_payment_request(payment_request_id)
        if pr["status"] != "pending":
            return pr
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return pr  # still pending — caller decides what to do
        await asyncio.sleep(min(poll_interval, remaining))
