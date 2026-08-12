from dataclasses import dataclass
from fastapi import FastAPI, Request
from typing import Optional
from datetime import datetime, timezone
import hashlib
import json


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

        self._current_event_id: int = 1
        self._events: list[Event] = []
        self._previous_hash: Optional[str] = None

        self.app.post("/api/events")(self.record_event)

    def calculate_hash(
        self,
        event_id: int,
        trace_id: str,
        timestamp: str,
        event_type: str,
        source: str,
        destination: str,
        payload: dict,
        previous_hash: Optional[str],
    ) -> str:

        data = {
            "event_id": event_id,
            "trace_id": trace_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "source": source,
            "destination": destination,
            "payload": payload,
            "previous_hash": previous_hash,
        }

        serialized = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    async def record_event(self, request: Request):
        body = await request.json()

        print("\n[RECORDER] Event Received")
        print(body)

        # Recorder-created metadata
        event_id = self._current_event_id
        timestamp = datetime.now(timezone.utc).isoformat()
        previous_hash = self._previous_hash

        # Gateway-provided evidence
        trace_id = body["trace_id"]
        event_type = body["event_type"]
        source = body["source"]
        destination = body["destination"]
        payload = body["payload"]

        event_hash = self.calculate_hash(
            event_id=event_id,
            trace_id=trace_id,
            timestamp=timestamp,
            event_type=event_type,
            source=source,
            destination=destination,
            payload=payload,
            previous_hash=previous_hash,
        )

        event = Event(
            event_id=event_id,
            trace_id=trace_id,
            timestamp=timestamp,
            event_type=event_type,
            source=source,
            destination=destination,
            payload=payload,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )

        # Append to hash chain
        self._events.append(event)

        # Prepare state for next event
        self._previous_hash = event.event_hash
        self._current_event_id += 1

        print("\n[RECORDER] Event Recorded")
        print(event)

        return {
            "status": "recorded",
            "event_id": event.event_id,
            "event_hash": event.event_hash,
        }


recorder = EventRecorder()
app = recorder.app