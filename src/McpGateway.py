from fastapi import FastAPI, Request, Response
import httpx
import json


app = FastAPI()

MCP_SERVER_URL = "http://127.0.0.1:8001/mcp"
RECORDER_URL = "http://127.0.0.1:9100"


def get_event_types(method: str) -> tuple[str, str]:
    """
    Convert MCP protocol methods into AgentTrace
    event types.
    """

    if method == "tools/call":
        return "TOOL_REQUEST", "TOOL_RESPONSE"

    if method == "tools/list":
        return "TOOL_LIST_REQUEST", "TOOL_LIST_RESPONSE"

    if method == "initialize":
        return "MCP_INITIALIZE_REQUEST", "MCP_INITIALIZE_RESPONSE"

    return "MCP_REQUEST", "MCP_RESPONSE"


@app.post("/mcp")
async def mcp_proxy(request: Request):

    # Receive MCP request from Agent Host
    trace_id = request.headers.get("x-trace-id")

    raw_body = await request.body()

    body = json.loads(raw_body)

    print("\n[MCP GATEWAY] Request Received")
    print(body)

    method = body.get("method", "unknown")

    request_event_type, response_event_type = get_event_types(method)

    # Headers needed by MCP
    forward_headers = {
        "Content-Type": request.headers.get(
            "content-type",
            "application/json"
        ),
        "Accept": request.headers.get(
            "accept",
            "application/json"
        ),
    }

    if request.headers.get("mcp-protocol-version"):
        forward_headers["Mcp-Protocol-Version"] = request.headers["mcp-protocol-version"]

    # Gateway becomes client
    async with httpx.AsyncClient(timeout=120) as client:
        # Record request FIRST
        recorder_response = await client.post(
            f"{RECORDER_URL}/api/events",
            json={
                "trace_id": trace_id,
                "event_type": request_event_type,
                "source": "agent_host",
                "destination": "mcp_server",
                "payload": body,
            },
        )

        recorder_response.raise_for_status()

        # Forward actual MCP request
        mcp_response = await client.post(
            MCP_SERVER_URL,
            content=raw_body,
            headers=forward_headers,
        )

    # Receive MCP server response
    try:
        result = mcp_response.json()
    except Exception:
        result = {
            "raw_response": mcp_response.text
        }

    print("\n[MCP GATEWAY] MCP Response Received")
    print(result)

    # Record MCP response
    async with httpx.AsyncClient(timeout=120) as client:

        recorder_response = await client.post(
            f"{RECORDER_URL}/api/events",
            json={
                "trace_id": trace_id,
                "event_type": response_event_type,
                "source": "mcp_server",
                "destination": "agent_host",
                "payload": result,
            },
        )

        recorder_response.raise_for_status()

    # Return original MCP response to client
    response_headers = {}

    if "mcp-session-id" in mcp_response.headers:
        response_headers["Mcp-Session-Id"] = mcp_response.headers["mcp-session-id"]

    return Response(
        content=mcp_response.content,
        status_code=mcp_response.status_code,
        headers=response_headers,
        media_type="application/json",
    )