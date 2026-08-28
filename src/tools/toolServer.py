from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "AgentTraceTools",
    stateless_http=True,
    json_response=True,
)

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""

    print(f"\n[MCP SERVER] add({a}, {b})")

    return a + b

app = mcp.streamable_http_app()