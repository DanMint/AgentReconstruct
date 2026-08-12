import subprocess
import sys
import socket
import time

from agent import Agent


RECORDER_HOST = "127.0.0.1"
RECORDER_PORT = 9100

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 9000

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434


def wait_for_server(host: str, port: int, timeout: int = 10):
    """
    Wait until a TCP server is accepting connections.
    """

    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            with socket.create_connection(
                (host, port),
                timeout=1,
            ):
                return

        except OSError:
            time.sleep(0.2)

    raise RuntimeError(
        f"Server {host}:{port} did not start."
    )


def main():
    # make sure ollama is running
    try:
        wait_for_server(
            OLLAMA_HOST,
            OLLAMA_PORT,
            timeout=2,
        )

    except RuntimeError:
        print(
            "[ERROR] Ollama is not running.\n"
            "Start it using: ollama serve"
        )
        return


    recorder_process = None
    gateway_process = None

    try:

       # start event recorder

        print("[MAIN] Starting Event Recorder...")

        recorder_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.EventRecorder:app",
                "--host",
                RECORDER_HOST,
                "--port",
                str(RECORDER_PORT),
            ]
        )

        wait_for_server(
            RECORDER_HOST,
            RECORDER_PORT,
        )

        print("[MAIN] Event Recorder ready.")


        # start LLM gateway

        print("[MAIN] Starting LLM Gateway...")

        gateway_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.LlmGateway:app",
                "--host",
                GATEWAY_HOST,
                "--port",
                str(GATEWAY_PORT),
            ]
        )

        wait_for_server(
            GATEWAY_HOST,
            GATEWAY_PORT,
        )

        print("[MAIN] LLM Gateway ready.")


        # create LLM agent

        print("[MAIN] Starting Agent...")

        agent = Agent(
            agent_prompt="You are a helpful assistant."
        )

        result = agent.invoke(
            messages="Tell me a joke"
        )

        print("\n[AGENT RESULT]")
        print(result)


    finally:

        # shut down when done

        if gateway_process is not None:
            gateway_process.terminate()

        if recorder_process is not None:
            recorder_process.terminate()

        print("\n[MAIN] AgentTrace stopped.")


if __name__ == "__main__":
    main()