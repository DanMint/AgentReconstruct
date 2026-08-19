from fastapi import FastAPI, Request, Response
import httpx
import json

app = FastAPI()

OLLAMA_URL = "http://127.0.0.1:11434"
RECORDER_URL = "http://127.0.0.1:9100"

# this is an HTTP connecntion meaning that it reamins alive for the duration of the system
@app.post("/api/chat")
async def ollama_chat(request: Request):
    # get trace_id from the headers
    trace_id = request.headers.get("x-trace-id")
    # recieved data from host agent or llm
    body = await request.json()

    print("\n[LLM GATEWAY] Request Received")
    print(body)

    # Make Ollama return ONE complete JSON response
    body["stream"] = True

    # switch roles from server to client
    # httpx.AsyncClient(timeout=120) -> creates an async HTTP client
    # async with httpx.AsyncClient(...) as client: -> creates the http client inside the block
    async with httpx.AsyncClient(timeout=120) as client:
        # send event to recorder
        record_response = await client.post(
            f"{RECORDER_URL}/api/events",
            json={
                "trace_id": trace_id,
                "event_type": "LLM_REQUEST",
                "source": "agent_host",
                "destination": "llm_reasoner",
                "payload": body,
            }
        )

        # await confiormation from recoder
        record_response.raise_for_status()

        # send prompt to ollama
        ollama_response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json=body,
        )

    result = ollama_response.json()

    print("\n[LLM GATEWAY] Ollama Response Received")
    print(result)

    async with httpx.AsyncClient(timeout=120) as client:

        # send LLM_RESPONSE event to Recorder
        recorder_response = await client.post(
            f"{RECORDER_URL}/api/events",
            json={
                "trace_id": trace_id,
                "event_type": "LLM_RESPONSE",
                "source": "llm_reasoner",
                "destination": "agent_host",
                "payload": result,
            },
        )

        recorder_response.raise_for_status()

    return Response(
        content=json.dumps(result),
        status_code=ollama_response.status_code,
        media_type="application/json",
    )