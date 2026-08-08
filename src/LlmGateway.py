from fastapi import FastAPI, Request, Response
import httpx
import json

app = FastAPI()

OLLAMA_URL = "http://127.0.0.1:11434"

@app.post("/api/chat")
async def ollama_chat(request: Request):
    # recieved data from host agent or llm
    body = await request.json()

    print("\n[LLM GATEWAY] Request Received")
    print(body)

    # Make Ollama return ONE complete JSON response
    body["stream"] = False

    # switch roles from server to client
    # httpx.AsyncClient(timeout=120) -> creates an async HTTP client
    # async with httpx.AsyncClient(...) as client: -> creates the http client inside the block
    async with httpx.AsyncClient(timeout=120) as client:
        ollama_response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json=body,
        )

    result = ollama_response.json()

    print("\n[LLM GATEWAY] Ollama Response Received")
    print(result)

    return Response(
        content=json.dumps(result),
        status_code=ollama_response.status_code,
        media_type="application/json",
    )