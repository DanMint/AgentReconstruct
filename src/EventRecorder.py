from dataclasses import dataclass
from fastapi import FastAPI, Request
from typing import Optional


@dataclass
class Event:
    event_id: int
    trace_id: str
    timestamp: str
    event_type: str
    source: str
    destination: str
    payload: dict
    previous_hash: Optional[str]
    event_hash: str


class EventRecorder:

    def __init__(self):
        self.app = FastAPI()
        self._events: list[Event] = []

        # Register endpoint with this FastAPI instance
        self.app.post("/api/events")(self.record_event)

    async def record_event(self, request: Request):
        body = await request.json()

        print("\n[RECORDER] Event Received From LLM Gateway")
        print(body)

        return {
            "status": "recorded"
        }


# Create recorder instance
recorder = EventRecorder()

# Expose FastAPI application to uvicorn
app = recorder.app