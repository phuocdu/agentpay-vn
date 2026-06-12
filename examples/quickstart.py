"""AgentPay VN — Quick start: create a payment request and wait for settlement."""
import asyncio
from agentpay.client import AsyncAgentPayClient, await_settlement

API_KEY = "ap_test_xxx"   # replace with your key from dashboard

async def main():
    async with AsyncAgentPayClient(API_KEY) as client:
        pr = await client.create_payment_request(
            amount=50_000,
            description="Demo order #1",
            ttl_minutes=10,
        )
        print(f"QR image: {pr['qr_image_url']}")
        print(f"Checkout: {pr['checkout_url']}")
        print("Waiting for payment (sandbox — will poll for 30s)...")
        result = await await_settlement(client, pr["id"], timeout=30)
        print(f"Final status: {result['status']}")

asyncio.run(main())
