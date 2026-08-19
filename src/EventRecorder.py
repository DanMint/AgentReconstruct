from dataclasses import dataclass
from fastapi import FastAPI, Request
from typing import Optional
from datetime import datetime, timezone
from pathlib import Path

import asyncio
import hashlib
import json
import sqlite3


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

        # cretaes an application level lock inside the recorder. so that two events wont be considered as the same event
        self._write_lock = asyncio.Lock()
        # database location
        project_root = Path(__file__).resolve().parent.parent
        data_directory = project_root / "data"
        data_directory.mkdir(parents=True,exist_ok=True)
        self.db_path = data_directory / "events.db"

        # open SQLite. the idea for writing to the DB: new event -> events.db-wal -> incorperated checkpoint -> events.db
        self._db = sqlite3.connect(self.db_path)
        # WAL allows readers while Recorder writes
        self._db.execute("PRAGMA journal_mode=WAL;")
        # prefer durability for forensic evidence. controls how aggressively SQLite ensures data has actually reached durable storage 
        self._db.execute("PRAGMA synchronous=FULL;")

        # create schema
        self._create_tables()

        # recover hash-chain state if Recorder was restarted
        self._current_event_id = 1
        self._previous_hash: Optional[str] = None
        self._load_chain_state()

        # register API
        self.app.post("/api/events")(self.record_event)

        self.app.get("/api/traces/{trace_id}")(self.get_trace)

    # database initialization
    def _create_tables(self) -> None:
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (

                event_id INTEGER PRIMARY KEY,

                trace_id TEXT NOT NULL,

                timestamp TEXT NOT NULL,

                event_type TEXT NOT NULL,

                source TEXT NOT NULL,

                destination TEXT NOT NULL,

                payload TEXT NOT NULL,

                previous_hash TEXT,

                event_hash TEXT NOT NULL UNIQUE

            )
            """
        )

        # fast lookup by trace
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_events_trace_id
            ON events(trace_id)
            """
        )

        # useful for reconstruction
        self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_events_trace_order
            ON events(trace_id, event_id)
            """
        )

        self._db.commit()


    # restore previous chain state. if agent was stopped it could be restored from a specific state using the DB entries
    def _load_chain_state(self) -> None:
        cursor = self._db.execute(
            """
            SELECT event_id, event_hash
            FROM events
            ORDER BY event_id DESC
            LIMIT 1
            """
        )

        row = cursor.fetchone()

        if row is None:
            self._current_event_id = 1
            self._previous_hash = None
        else:
            last_event_id = row[0]
            last_event_hash = row[1]
            self._current_event_id = (last_event_id + 1)
            self._previous_hash = (last_event_hash)

    # hash generation
    def calculate_hash(
        self,
        event_id: int,
        trace_id: str,
        timestamp: str,
        event_type: str,
        source: str,
        destination: str,
        payload: dict,
        previous_hash: Optional[str]
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

        serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))

        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    # record event
    async def record_event(self, request: Request) -> dict:

        body = await request.json()

        print("\n[RECORDER] Event Received")

        print(body)

        # only one event can modify chain state at a time. only one coroutine is allowed at a time
        async with self._write_lock:
            event_id = self._current_event_id
            timestamp = datetime.now(timezone.utc).isoformat()
            previous_hash = (self._previous_hash)

            # Gateway evidence
            trace_id = body["trace_id"]
            event_type = body["event_type"]
            source = body["source"]
            destination = body["destination"]
            payload = body["payload"]

            # calculate hash
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

            # persist event
            try:
                self._db.execute(
                    """
                    INSERT INTO events (
                        event_id,
                        trace_id,
                        timestamp,
                        event_type,
                        source,
                        destination,
                        payload,
                        previous_hash,
                        event_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.trace_id,
                        event.timestamp,
                        event.event_type,
                        event.source,
                        event.destination,
                        json.dumps(event.payload),
                        event.previous_hash,
                        event.event_hash,
                    ),
                )
                self._db.commit()

            except Exception:
                self._db.rollback()
                raise

            # ONLY advance chain after successful DB commit
            self._previous_hash = (event.event_hash)
            self._current_event_id += 1

        print("\n[RECORDER] Event Persisted")
        print(event)

        return {
            "status": "recorded",
            "event_id": event.event_id,
            "event_hash": event.event_hash,
        }

    # retrieve complete execution trace
    async def get_trace(self, trace_id: str) -> dict:
        cursor = self._db.execute(
            """
            SELECT
                event_id,
                trace_id,
                timestamp,
                event_type,
                source,
                destination,
                payload,
                previous_hash,
                event_hash

            FROM events

            WHERE trace_id = ?

            ORDER BY event_id ASC
            """,
            (trace_id,),
        )

        rows = cursor.fetchall()

        events = []

        for row in rows:
            events.append(
                {
                    "event_id": row[0],
                    "trace_id": row[1],
                    "timestamp": row[2],
                    "event_type": row[3],
                    "source": row[4],
                    "destination": row[5],
                    "payload": json.loads(
                        row[6]
                    ),
                    "previous_hash": row[7],
                    "event_hash": row[8],
                }
            )

        return {
            "trace_id": trace_id,
            "event_count": len(events),
            "events": events,
        }

recorder = EventRecorder()

app = recorder.app