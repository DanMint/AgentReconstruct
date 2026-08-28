import asyncio
import socket
import subprocess
import sys
import time
import uuid

from agent import Agent
from langchain_mcp_adapters.client import MultiServerMCPClient

# Ports
RECORDER_HOST = "127.0.0.1"
RECORDER_PORT = 9100

LLM_GATEWAY_HOST = "127.0.0.1"
LLM_GATEWAY_PORT = 9000

MCP_GATEWAY_HOST = "127.0.0.1"
MCP_GATEWAY_PORT = 9001

MCP_SERVER_HOST = "127.0.0.1"
MCP_SERVER_PORT = 8001

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434

def wait_for_server(host: str, port: int, timeout: int = 10):
    """
    Wait until a TCP server starts accepting connections.
    """

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port),timeout=1):
                return

        except OSError:
            time.sleep(0.2)

    raise RuntimeError(f"Server {host}:{port} did not start.")


def start_uvicorn(module: str, host: str, port: int):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--host",
            host,
            "--port",
            str(port),
        ]
    )

    wait_for_server(host, port)

    return process

async def run_agent():

    # One trace ID for the entire agent execution
    trace_id = str(uuid.uuid4())

    print(f"\n[MAIN] Trace ID: {trace_id}")
    # --------------------------------------------------------
    # MCP Client
    #
    # IMPORTANT:
    # The Agent Host points to MCP Gateway.
    #
    # It DOES NOT point directly to MCP Server :8001.
    # --------------------------------------------------------

    mcp_client = MultiServerMCPClient(
        {
            "math_server": {
                "transport": "http",
                # Gateway address
                "url": (
                    f"http://{MCP_GATEWAY_HOST}:"
                    f"{MCP_GATEWAY_PORT}/mcp"
                ),
                # Same trace ID used by LLM traffic
                "headers": {
                    "X-Trace-ID": trace_id
                },
            }
        }
    )

    # Tool discovery
    print(
        "\n[MAIN] Loading MCP tools "
        "through MCP Gateway..."
    )

    tools = await mcp_client.get_tools()

    print("\n[MAIN] MCP Tools Loaded:")

    for tool in tools:
        print(f" KAZA  - {tool.name}")

    # Verify add exists
    tool_names = [
        tool.name
        for tool in tools
    ]

    if "add" not in tool_names:
        raise RuntimeError(
            "MCP tool 'add' was not discovered."
        )


    # Create Agent Host
    agent = Agent(
        tools=tools,
        trace_id=trace_id,
        agent_prompt=(
            "You are a helpful assistant. "
            "When asked to perform arithmetic, "
            "use the provided MCP tools."
        ),
    )

    # Invoke agent
    print("\n[MAIN] Asking agent to use add tool...")

    result = await agent.invoke(
        messages=(
            "Use the add tool to calculate 47 + 81. "
            "You must use the add tool rather than "
            "calculating it yourself."
        )
    )

    print("\n[AGENT RESULT]")

    print(result)


def main():
    recorder_process = None
    llm_gateway_process = None
    mcp_gateway_process = None
    mcp_server_process = None


    try:
        # Checking ollama running
        print("[MAIN] Checking Ollama...")

        try:
            wait_for_server(OLLAMA_HOST, OLLAMA_PORT, timeout=2)

        except RuntimeError:
            print(
                "[ERROR] Ollama is not running.\n"
                "Start it using:\n"
                "ollama serve"
            )
            return


        print("[MAIN] Ollama ready.")

        # start recorder
        print("\n[MAIN] Starting Event Recorder...")

        recorder_process = start_uvicorn("src.EventRecorder:app", RECORDER_HOST, RECORDER_PORT)

        print("[MAIN] Event Recorder ready.")

        # Start MCP Tool Server
        print("\n[MAIN] Starting MCP Tool Server...")

        mcp_server_process = start_uvicorn("src.tools.toolServer:app", MCP_SERVER_HOST, MCP_SERVER_PORT)

        print("[MAIN] MCP Tool Server ready.")

        # Start MCP Gateway
        print("\n[MAIN] Starting MCP Gateway...")

        mcp_gateway_process = start_uvicorn("src.McpGateway:app", MCP_GATEWAY_HOST, MCP_GATEWAY_PORT)

        print("[MAIN] MCP Gateway ready.")

        # Start LLM Gateway
        print("\n[MAIN] Starting LLM Gateway...")

        llm_gateway_process = start_uvicorn("src.LlmGateway:app", LLM_GATEWAY_HOST, LLM_GATEWAY_PORT)

        print("[MAIN] LLM Gateway ready.")

        # Run Agent
        print("\n[MAIN] Starting Agent Host...")

        asyncio.run(run_agent())

    finally:

        # Shutdown
        print("\n[MAIN] Shutting down...")

        processes = [
            llm_gateway_process,
            mcp_gateway_process,
            mcp_server_process,
            recorder_process,
        ]

        for process in processes:
            if process is not None:
                process.terminate()


        for process in processes:
            if process is not None:
                try:
                    process.wait(timeout=5)

                except subprocess.TimeoutExpired:
                    process.kill()

        print("[MAIN] AgentTrace stopped.")


if __name__ == "__main__":
    main()