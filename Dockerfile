# AgentPay VN — MCP server (stdio transport).
# Used by MCP clients (Claude Desktop/Code) and by directories such as
# Glama to build, start, and introspect the server (tools/list).
FROM python:3.11-slim

WORKDIR /app
COPY . /app

# Installs the package and the `agentpay-mcp` console script.
RUN pip install --no-cache-dir .

# The server starts and answers tools/list WITHOUT credentials; a real
# AGENTPAY_API_KEY is only required when a payment tool is actually invoked.
ENTRYPOINT ["agentpay-mcp"]
