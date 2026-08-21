from pathlib import Path
from typing import Optional
import sqlite3
import hashlib
import json


class ReconstructionEngine:

    def __init__(self, db_path: Optional[str] = None):

        if db_path is None:
            project_root = Path(__file__).resolve().parent.parent
            self.db_path = project_root / "data" / "events.db"
        else:
            self.db_path = Path(db_path)

        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row


    def load_trace(self, trace_id: str) -> list[dict]:
        """
        Load all events associated with a trace ID.
        """

        cursor = self.db.execute(
            """
            SELECT event_id, trace_id, timestamp, event_type,
                   source, destination, payload,
                   previous_hash, event_hash
            FROM events
            WHERE trace_id = ?
            ORDER BY event_id ASC
            """,
            (trace_id,)
        )

        rows = cursor.fetchall()

        events = []

        for row in rows:
            events.append({
                "event_id": row["event_id"],
                "trace_id": row["trace_id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "source": row["source"],
                "destination": row["destination"],
                "payload": json.loads(row["payload"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
            })

        return events


    def calculate_hash(self, event: dict) -> str:
        """
        Recalculate the hash of an event using the same
        method as the Event Recorder.
        """

        data = {
            "event_id": event["event_id"],
            "trace_id": event["trace_id"],
            "timestamp": event["timestamp"],
            "event_type": event["event_type"],
            "source": event["source"],
            "destination": event["destination"],
            "payload": event["payload"],
            "previous_hash": event["previous_hash"],
        }

        serialized = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":")
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()


    def get_previous_global_hash(self, event_id: int) -> Optional[str]:
        """
        Get the hash of the event immediately before this
        event in the global Recorder chain.
        """

        cursor = self.db.execute(
            """
            SELECT event_hash
            FROM events
            WHERE event_id < ?
            ORDER BY event_id DESC
            LIMIT 1
            """,
            (event_id,)
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return row["event_hash"]


    def verify_integrity(self, events: list[dict]) -> dict:
        """
        Verify each event hash and previous hash.
        """

        failures = []

        for event in events:

            calculated_hash = self.calculate_hash(event)

            if calculated_hash != event["event_hash"]:
                failures.append({
                    "event_id": event["event_id"],
                    "failure": "EVENT_HASH_MISMATCH",
                    "stored_hash": event["event_hash"],
                    "calculated_hash": calculated_hash,
                })

            expected_previous_hash = self.get_previous_global_hash(
                event["event_id"]
            )

            if event["previous_hash"] != expected_previous_hash:
                failures.append({
                    "event_id": event["event_id"],
                    "failure": "PREVIOUS_HASH_MISMATCH",
                    "stored_previous_hash": event["previous_hash"],
                    "expected_previous_hash": expected_previous_hash,
                })

        return {
            "valid": len(failures) == 0,
            "failures": failures,
        }


    def extract_execution(self, events: list[dict]) -> list[dict]:
        """
        Extract events between TRACE_START and TRACE_END.
        """

        start_index = None
        end_index = None

        for index, event in enumerate(events):

            if event["event_type"] == "TRACE_START":
                start_index = index
                break

        if start_index is None:
            raise ValueError("TRACE_START was not found.")

        for index in range(start_index, len(events)):

            if events[index]["event_type"] == "TRACE_END":
                end_index = index
                break

        if end_index is None:
            raise ValueError("TRACE_END was not found.")

        return events[start_index:end_index + 1]


    def normalize_event(self, event: dict) -> dict:
        """
        Convert a raw database event into a simpler
        semantic representation.
        """

        event_type = event["event_type"]
        payload = event["payload"]

        normalized = {
            "event_id": event["event_id"],
            "event_type": event_type,
            "source": event["source"],
            "destination": event["destination"],
            "timestamp": event["timestamp"],
            "details": {},
        }

        if event_type == "USER_INPUT":

            normalized["details"] = {
                "role": payload.get("role"),
                "content": payload.get("content"),
            }

        elif event_type == "LLM_REQUEST":

            normalized["details"] = {
                "model": payload.get("model"),
                "messages": payload.get("messages", []),
                "tools": payload.get("tools", []),
            }

        elif event_type == "LLM_RESPONSE":

            message = payload.get("message", {})

            normalized["details"] = {
                "model": payload.get("model"),
                "content": message.get("content"),
                "tool_calls": message.get("tool_calls", []),
            }

        elif event_type == "TOOL_REQUEST":

            params = payload.get("params", {})

            normalized["details"] = {
                "tool_name": params.get("name"),
                "arguments": params.get("arguments", {}),
                "rpc_id": payload.get("id"),
            }

        elif event_type == "TOOL_RESPONSE":

            result = payload.get("result", {})

            normalized["details"] = {
                "rpc_id": payload.get("id"),
                "result": result.get(
                    "structuredContent",
                    result.get("content")
                ),
                "is_error": result.get("isError", False),
            }

        elif event_type == "FINAL_RESPONSE":

            normalized["details"] = {
                "content": payload.get("content")
            }

        elif event_type not in ("TRACE_START", "TRACE_END"):

            normalized["details"] = {
                "payload": payload
            }

        return normalized


    def normalize_execution(self, events: list[dict]) -> list[dict]:
        """
        Normalize every event in an execution.
        """

        return [
            self.normalize_event(event)
            for event in events
        ]


    def find_next_event(
        self,
        events: list[dict],
        start_index: int,
        event_type: str
    ) -> Optional[dict]:
        """
        Find the next event of a specific type.
        """

        for index in range(start_index + 1, len(events)):

            if events[index]["event_type"] == event_type:
                return events[index]

        return None


    def reconstruct_dependencies(self, events: list[dict]) -> list[dict]:
        """
        Reconstruct relationships between execution events.
        """

        dependencies = []

        for index, event in enumerate(events):

            event_type = event["event_type"]

            if event_type == "TRACE_START":

                target = self.find_next_event(
                    events,
                    index,
                    "USER_INPUT"
                )

                if target is not None:
                    dependencies.append({
                        "from_event": event["event_id"],
                        "to_event": target["event_id"],
                        "relationship": "execution_started",
                    })


            elif event_type == "USER_INPUT":

                target = self.find_next_event(
                    events,
                    index,
                    "LLM_REQUEST"
                )

                if target is not None:
                    dependencies.append({
                        "from_event": event["event_id"],
                        "to_event": target["event_id"],
                        "relationship": "input_consumed_by",
                    })


            elif event_type == "LLM_REQUEST":

                target = self.find_next_event(
                    events,
                    index,
                    "LLM_RESPONSE"
                )

                if target is not None:
                    dependencies.append({
                        "from_event": event["event_id"],
                        "to_event": target["event_id"],
                        "relationship": "produced_response",
                    })


            elif event_type == "LLM_RESPONSE":

                message = event["payload"].get("message", {})
                tool_calls = message.get("tool_calls", [])

                if len(tool_calls) > 0:

                    for tool_call in tool_calls:

                        function = tool_call.get("function", {})

                        tool_name = function.get("name")
                        arguments = function.get("arguments", {})

                        for candidate in events[index + 1:]:

                            if candidate["event_type"] != "TOOL_REQUEST":
                                continue

                            params = candidate["payload"].get(
                                "params",
                                {}
                            )

                            if (
                                params.get("name") == tool_name
                                and
                                params.get("arguments", {}) == arguments
                            ):

                                dependencies.append({
                                    "from_event": event["event_id"],
                                    "to_event": candidate["event_id"],
                                    "relationship": "requested_tool",
                                })

                                break

                else:

                    target = self.find_next_event(
                        events,
                        index,
                        "FINAL_RESPONSE"
                    )

                    if target is not None:
                        dependencies.append({
                            "from_event": event["event_id"],
                            "to_event": target["event_id"],
                            "relationship": "became_final_response",
                        })


            elif event_type == "TOOL_REQUEST":

                request_id = event["payload"].get("id")

                for candidate in events[index + 1:]:

                    if candidate["event_type"] != "TOOL_RESPONSE":
                        continue

                    response_id = candidate["payload"].get("id")

                    if request_id == response_id:

                        dependencies.append({
                            "from_event": event["event_id"],
                            "to_event": candidate["event_id"],
                            "relationship": "produced_tool_result",
                        })

                        break


            elif event_type == "TOOL_RESPONSE":

                target = self.find_next_event(
                    events,
                    index,
                    "LLM_REQUEST"
                )

                if target is not None:
                    dependencies.append({
                        "from_event": event["event_id"],
                        "to_event": target["event_id"],
                        "relationship": "tool_result_consumed_by",
                    })


            elif event_type == "FINAL_RESPONSE":

                target = self.find_next_event(
                    events,
                    index,
                    "TRACE_END"
                )

                if target is not None:
                    dependencies.append({
                        "from_event": event["event_id"],
                        "to_event": target["event_id"],
                        "relationship": "execution_completed",
                    })

        return dependencies


    def reconstruct(self, trace_id: str) -> dict:
        """
        Reconstruct a complete execution from the database.
        """

        all_events = self.load_trace(trace_id)

        if len(all_events) == 0:
            raise ValueError(
                f"No events found for trace_id: {trace_id}"
            )

        integrity = self.verify_integrity(all_events)

        execution_events = self.extract_execution(all_events)

        timeline = self.normalize_execution(execution_events)

        dependencies = self.reconstruct_dependencies(
            execution_events
        )

        return {
            "trace_id": trace_id,
            "integrity": integrity,
            "total_trace_events": len(all_events),
            "execution_event_count": len(execution_events),
            "timeline": timeline,
            "dependencies": dependencies,
        }


    def print_timeline(self, reconstruction: dict) -> None:
        """
        Print the reconstructed execution.
        """

        print("\n================================")
        print("RECONSTRUCTED EXECUTION")
        print("================================")

        print(f"\nTrace ID: {reconstruction['trace_id']}")
        print(
            "Integrity Valid:",
            reconstruction["integrity"]["valid"]
        )

        print("\n--------------------------------")
        print("TIMELINE")
        print("--------------------------------")

        for event in reconstruction["timeline"]:

            print(
                f"\n[{event['event_id']}] "
                f"{event['event_type']}"
            )

            print(
                f"    {event['source']} "
                f"-> {event['destination']}"
            )

            if event["details"]:
                print("    Details:")
                print(
                    json.dumps(
                        event["details"],
                        indent=4,
                        default=str
                    )
                )

        print("\n--------------------------------")
        print("DEPENDENCIES")
        print("--------------------------------")

        for dependency in reconstruction["dependencies"]:

            print(
                f"\nE{dependency['from_event']} "
                f"--[{dependency['relationship']}]--> "
                f"E{dependency['to_event']}"
            )


    def close(self) -> None:
        """
        Close the database connection.
        """

        self.db.close()


def main():

    engine = ReconstructionEngine()

    trace_id = input(
        "Enter trace_id: "
    ).strip()

    try:

        reconstruction = engine.reconstruct(trace_id)

        engine.print_timeline(reconstruction)

    finally:

        engine.close()


if __name__ == "__main__":
    main()