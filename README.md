# AgentPay VN

**VietQR payment infrastructure for AI agents — collect money inside any conversation.**

AgentPay VN lets AI agents (Claude, GPT, custom bots) generate payment QR codes, send them to users, and automatically confirm when the money arrives — all without ever holding or touching funds.  Money flows directly from the payer's bank account into the merchant's account; AgentPay only reads the bank transaction feed to confirm settlement.

> **Status:** Early access / self-hosted — running on the same swarm as [Sổ Nợ AI](https://sono.servicesai.vn).

---

## How it works

```
AI Agent                   AgentPay API              Bank feed (SePay)
   |                            |                           |
   |-- create_payment_request ->|                           |
   |<- { qr_image_url, id } ----|                           |
   |                            |                           |
   |-- send QR to user -------->|                           |
   |                            |      user scans & pays    |
   |                            |<-- webhook (bank txn) ----|
   |                            |-- match AP* pay_code      |
   |                            |-- status → settled        |
   |<-- await_settlement done --|                           |
   |                            |                           |
   |-- deliver order / unlock ->|                           |
```

1. **Create** — agent calls `POST /v1/payment-requests` → gets a VietQR image URL and a checkout page.
2. **Send** — agent embeds the QR image or sends the checkout link to the user in chat.
3. **Await** — agent calls `await_settlement()` (or the MCP tool) to poll until `status = settled`.
4. **Deliver** — only after confirmed settlement does the agent release the goods/service.

**AgentPay never holds money.** The QR points directly at the merchant's bank account number.  The platform only monitors the bank transaction feed to detect matching transfers.

---

## Quick start

### 1. Install

```bash
pip install agentpay-vn
```

### 2. Set your API key

```bash
export AGENTPAY_API_KEY=ap_test_xxx   # sandbox key for testing
```

Get a key from the admin dashboard (self-hosted) or contact the platform operator.

### 3. Collect a payment (3 lines)

```python
from agentpay.client import AsyncAgentPayClient, await_settlement
import asyncio

async def main():
    async with AsyncAgentPayClient("ap_test_xxx") as client:
        pr = await client.create_payment_request(amount=50_000, description="Order #1")
        print(pr["checkout_url"])          # send this link to your user
        result = await await_settlement(client, pr["id"], timeout=120)
        assert result["status"] == "settled"

asyncio.run(main())
```

See [`examples/quickstart.py`](examples/quickstart.py) for the full runnable version.

---

## MCP server setup

AgentPay ships an [MCP](https://modelcontextprotocol.io) server so any MCP-compatible AI agent can call it as a tool — no extra code needed.

### Claude Desktop / Claude Code

Add to `claude_desktop_config.json` (or use [`examples/claude_desktop_config.json`](examples/claude_desktop_config.json)):

```json
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
```

Or use the installed console script:

```json
{
  "mcpServers": {
    "agentpay": {
      "command": "agentpay-mcp",
      "env": { "AGENTPAY_API_KEY": "ap_live_xxx" }
    }
  }
}
```

### Available MCP tools

| Tool | Description |
|------|-------------|
| `create_payment_request` | Generate a VietQR code for a given amount |
| `check_payment` | Get current status of a payment request |
| `await_settlement` | Poll until payment arrives or timeout (max 600 s) |
| `list_recent_payments` | List last N settled transactions |

---

## Python SDK

### Synchronous

```python
from agentpay.client import AgentPayClient

with AgentPayClient("ap_live_xxx") as client:
    # Create
    pr = client.create_payment_request(
        amount=150_000,
        description="Consulting session 30 min",
        ttl_minutes=30,
        idempotency_key="session-abc-123",
    )

    # Poll manually
    import time
    for _ in range(60):
        pr = client.get_payment_request(pr["id"])
        if pr["status"] != "pending":
            break
        time.sleep(5)

    # Reconcile
    txns = client.list_transactions(limit=10)
```

### Asynchronous

```python
from agentpay.client import AsyncAgentPayClient, await_settlement

async with AsyncAgentPayClient("ap_live_xxx") as client:
    pr = await client.create_payment_request(amount=75_000, description="eBook download")
    result = await await_settlement(client, pr["id"], timeout=300)
    if result["status"] == "settled":
        send_download_link(result["metadata"].get("email"))
```

### Webhook verification

```python
import hashlib, hmac

def verify_webhook(raw_body: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

Register a webhook endpoint:

```python
ep = client.register_webhook(
    url="https://your-server.com/webhooks/agentpay",
    events=["payment.settled", "payment.expired"],
)
print(ep["secret"])  # store this — shown only once
```

---

## API reference

- **OpenAPI spec:** [`agentpay-openapi.yaml`](agentpay-openapi.yaml)
- **Base URL:** `https://agentpay.servicesai.vn/v1`
- **Authentication:** `Authorization: Bearer ap_live_xxx` (or `ap_test_xxx` for sandbox)

### Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/payment-requests` | Create payment request |
| `GET` | `/v1/payment-requests/{id}` | Get status |
| `POST` | `/v1/payment-requests/{id}/cancel` | Cancel pending request |
| `GET` | `/v1/transactions` | List settled transactions |
| `POST` | `/v1/webhook-endpoints` | Register webhook URL |
| `POST` | `/v1/sandbox/simulate-settlement` | Simulate payment (sandbox only) |
| `GET` | `/pay/{pay_code}` | Public checkout page (HTML, mobile-friendly) |

---

## Self-hosting

AgentPay runs as part of the [Sổ Nợ AI](https://github.com/drave-io/sono-ai) FastAPI backend.

### Requirements

- Docker Swarm cluster (same as Sono)
- MongoDB (shared with Sono)
- SePay bank feed account (for live payments)
- Nginx with `agentpay.servicesai.vn` vhost (see [`server/`](../nginx/sono.servicesai.vn.conf))

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTPAY_BASE_URL` | `https://agentpay.servicesai.vn` | Public base URL for checkout links |
| `MONGO_URI` | `mongodb://localhost:27017` | Inherited from Sono |
| `BILLING_WEBHOOK_TOKEN` | — | SePay webhook token (inherited) |

### Create an API key (admin)

```bash
curl -X POST https://sono.servicesai.vn/api/admin/agentpay/keys \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"org_id": "<shop-user-id>", "name": "My bot", "livemode": true}'
```

The response includes the full key — store it immediately; it is shown only once.

---

## Rate limits

| Tier | Settled payments/month | Requests/minute |
|------|----------------------|-----------------|
| Free | 50 | 120 |

---

## Design principles

1. **No money held** — QR codes point directly at the merchant's bank account.  AgentPay only reads the transaction feed; it never touches the money.

2. **Idempotency** — pass an `Idempotency-Key` header on `POST /payment-requests` to safely retry without creating duplicates (24-hour deduplication window).

3. **HMAC webhook verification** — every outbound webhook is signed with `HMAC-SHA256(whsec_..., raw_body)` in the `AgentPay-Signature` header.  Always verify before processing.

4. **Sandbox** — use `ap_test_*` keys and `POST /v1/sandbox/simulate-settlement` to develop and test without real transactions.

5. **Minimal trust surface** — the MCP server is a thin REST client with no local secrets beyond the API key.  Compromising an agent key only exposes one tenant's payment-request creation ability.

---

## License

MIT © 2025 Drave / Sổ Nợ AI team
