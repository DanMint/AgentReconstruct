from pathlib import Path
from typing import Optional
import sqlite3
import hashlib
import json


class ReconstructionEngine:

    def __init__(self, db_path: Optional[str] = None):

        self.project_root = Path(__file__).resolve().parent.parent

        if db_path is None:
            self.db_path = self.project_root / "data" / "events.db"
        else:
            self.db_path = Path(db_path)

        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row


    def load_trace(self, trace_id: str) -> list[dict]:
        """
        Load a complete trace from SQLite.
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


    def load_json(self, json_path: str | Path) -> list[dict]:
        """
        Load an ablated trace from JSON.
        """

        json_path = Path(json_path)

        if not json_path.exists():
            raise FileNotFoundError(
                f"JSON file not found: {json_path}"
            )

        with open(
            json_path,
            "r",
            encoding="utf-8"
        ) as file:
            events = json.load(file)

        if not isinstance(events, list):
            raise ValueError(
                "Ablated JSON must contain a list of events."
            )

        return events


    def calculate_hash(self, event: dict) -> str:
        """
        Recalculate the hash of an original database event.
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


    def get_previous_global_hash(
        self,
        event_id: int
    ) -> Optional[str]:

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
        Verify the original trusted database trace.

        Ablated traces are intentionally modified and
        should not be integrity checked.
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


    def extract_execution(
        self,
        events: list[dict]
    ) -> list[dict]:
        """
        Extract TRACE_START through TRACE_END.
        """

        start_index = None
        end_index = None

        for index, event in enumerate(events):

            if event.get("event_type") == "TRACE_START":
                start_index = index
                break

        if start_index is None:
            raise ValueError(
                "TRACE_START was not found."
            )

        for index in range(start_index, len(events)):

            if events[index].get("event_type") == "TRACE_END":
                end_index = index
                break

        if end_index is None:
            raise ValueError(
                "TRACE_END was not found."
            )

        return events[start_index:end_index + 1]


    def normalize_event(self, event: dict) -> dict:
        """
        Convert raw evidence into a semantic event.
        """

        event_type = event.get("event_type")
        payload = event.get("payload", {})

        normalized = {
            "event_id": event.get("event_id"),
            "event_type": event_type,
            "source": event.get("source"),
            "destination": event.get("destination"),
            "timestamp": event.get("timestamp"),
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
                "arguments": params.get("arguments"),
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
                "is_error": result.get("isError"),
            }


        elif event_type == "FINAL_RESPONSE":

            normalized["details"] = {
                "content": payload.get("content")
            }


        elif event_type not in (
            "TRACE_START",
            "TRACE_END",
        ):

            normalized["details"] = {
                "payload": payload
            }

        return normalized


    def normalize_execution(
        self,
        events: list[dict]
    ) -> list[dict]:

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

        for index in range(
            start_index + 1,
            len(events)
        ):

            if events[index].get("event_type") == event_type:
                return events[index]

        return None


    def reconstruct_dependencies(
        self,
        events: list[dict]
    ) -> list[dict]:

        dependencies = []

        for index, event in enumerate(events):

            event_type = event.get("event_type")


            if event_type == "TRACE_START":

                target = self.find_next_event(
                    events,
                    index,
                    "USER_INPUT"
                )

                if target is not None:
                    dependencies.append({
                        "from_event": event.get("event_id"),
                        "to_event": target.get("event_id"),
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
                        "from_event": event.get("event_id"),
                        "to_event": target.get("event_id"),
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
                        "from_event": event.get("event_id"),
                        "to_event": target.get("event_id"),
                        "relationship": "produced_response",
                    })


            elif event_type == "LLM_RESPONSE":

                payload = event.get("payload", {})
                message = payload.get("message", {})
                tool_calls = message.get("tool_calls", [])

                if len(tool_calls) > 0:

                    for tool_call in tool_calls:

                        function = tool_call.get(
                            "function",
                            {}
                        )

                        tool_name = function.get("name")
                        arguments = function.get("arguments")

                        for candidate in events[index + 1:]:

                            if (
                                candidate.get("event_type")
                                != "TOOL_REQUEST"
                            ):
                                continue

                            candidate_payload = candidate.get(
                                "payload",
                                {}
                            )

                            params = candidate_payload.get(
                                "params",
                                {}
                            )

                            candidate_name = params.get("name")
                            candidate_arguments = params.get(
                                "arguments"
                            )

                            if (
                                tool_name is not None
                                and
                                candidate_name == tool_name
                                and
                                arguments is not None
                                and
                                candidate_arguments is not None
                                and
                                candidate_arguments == arguments
                            ):

                                dependencies.append({
                                    "from_event": event.get(
                                        "event_id"
                                    ),
                                    "to_event": candidate.get(
                                        "event_id"
                                    ),
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
                            "from_event": event.get(
                                "event_id"
                            ),
                            "to_event": target.get(
                                "event_id"
                            ),
                            "relationship": "became_final_response",
                        })


            elif event_type == "TOOL_REQUEST":

                payload = event.get("payload", {})

                request_id = payload.get("id")

                if request_id is None:
                    continue

                for candidate in events[index + 1:]:

                    if (
                        candidate.get("event_type")
                        != "TOOL_RESPONSE"
                    ):
                        continue

                    candidate_payload = candidate.get(
                        "payload",
                        {}
                    )

                    response_id = candidate_payload.get("id")

                    if (
                        response_id is not None
                        and
                        request_id == response_id
                    ):

                        dependencies.append({
                            "from_event": event.get(
                                "event_id"
                            ),
                            "to_event": candidate.get(
                                "event_id"
                            ),
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
                        "from_event": event.get("event_id"),
                        "to_event": target.get("event_id"),
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
                        "from_event": event.get("event_id"),
                        "to_event": target.get("event_id"),
                        "relationship": "execution_completed",
                    })

        return dependencies


    def save_reconstruction(
        self,
        reconstruction: dict,
        filename: str
    ) -> Path:
        """
        Save reconstruction to:

        data/reconstructions/<trace_id>/<filename>
        """

        trace_id = reconstruction.get("trace_id")

        if trace_id is None:
            trace_id = "unknown_trace"

        output_directory = (
            self.project_root
            / "data"
            / "reconstructions"
            / trace_id
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        if not filename.endswith(".json"):
            filename = f"{filename}.json"

        output_path = (
            output_directory
            / filename
        )

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                reconstruction,
                file,
                indent=4
            )

        return output_path


    def reconstruct_from_events(
        self,
        events: list[dict],
        trace_id: Optional[str] = None
    ) -> dict:
        """
        Reconstruct from an in-memory event list.
        """

        if len(events) == 0:
            return {
                "trace_id": trace_id,
                "success": False,
                "failure_reason": "NO_EVENTS",
                "timeline": [],
                "dependencies": [],
            }

        if trace_id is None:
            trace_id = events[0].get("trace_id")

        try:

            execution_events = self.extract_execution(
                events
            )

        except ValueError as error:

            return {
                "trace_id": trace_id,
                "success": False,
                "failure_reason": str(error),
                "timeline": [],
                "dependencies": [],
            }

        timeline = self.normalize_execution(
            execution_events
        )

        dependencies = self.reconstruct_dependencies(
            execution_events
        )

        return {
            "trace_id": trace_id,
            "success": True,
            "execution_event_count": len(
                execution_events
            ),
            "timeline": timeline,
            "dependencies": dependencies,
        }


    def reconstruct_json(
        self,
        json_path: str | Path
    ) -> dict:
        """
        Reconstruct an ablated JSON file and save
        the reconstructed result.
        """

        json_path = Path(json_path)

        events = self.load_json(
            json_path
        )

        trace_id = None

        if len(events) > 0:
            trace_id = events[0].get("trace_id")

        reconstruction = self.reconstruct_from_events(
            events,
            trace_id
        )

        output_path = self.save_reconstruction(
            reconstruction,
            json_path.name
        )

        reconstruction["saved_to"] = str(
            output_path
        )

        return reconstruction


    def reconstruct(
        self,
        trace_id: str
    ) -> dict:
        """
        Reconstruct the original trusted trace from SQLite
        and save the result.
        """

        all_events = self.load_trace(
            trace_id
        )

        if len(all_events) == 0:
            raise ValueError(
                f"No events found for trace_id: {trace_id}"
            )

        integrity = self.verify_integrity(
            all_events
        )

        execution_events = self.extract_execution(
            all_events
        )

        timeline = self.normalize_execution(
            execution_events
        )

        dependencies = self.reconstruct_dependencies(
            execution_events
        )

        reconstruction = {
            "trace_id": trace_id,
            "success": True,
            "integrity": integrity,
            "total_trace_events": len(all_events),
            "execution_event_count": len(
                execution_events
            ),
            "timeline": timeline,
            "dependencies": dependencies,
        }

        output_path = self.save_reconstruction(
            reconstruction,
            "database_full_evidence.json"
        )

        reconstruction["saved_to"] = str(
            output_path
        )

        return reconstruction


    def print_timeline(
        self,
        reconstruction: dict
    ) -> None:

        print("\n================================")
        print("RECONSTRUCTED EXECUTION")
        print("================================")

        print(
            f"\nTrace ID: "
            f"{reconstruction.get('trace_id')}"
        )

        print(
            "Success:",
            reconstruction.get("success", True)
        )

        if "integrity" in reconstruction:
            print(
                "Integrity Valid:",
                reconstruction["integrity"]["valid"]
            )
        else:
            print(
                "Integrity Valid: "
                "Not checked (ablated evidence)"
            )

        if not reconstruction.get(
            "success",
            True
        ):

            print(
                "Failure:",
                reconstruction.get(
                    "failure_reason"
                )
            )

            return

        print("\n--------------------------------")
        print("TIMELINE")
        print("--------------------------------")

        for event in reconstruction["timeline"]:

            print(
                f"\n[{event.get('event_id')}] "
                f"{event.get('event_type')}"
            )

            print(
                f"    {event.get('source')} "
                f"-> {event.get('destination')}"
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

        if reconstruction.get("saved_to"):

            print(
                f"\nSaved reconstruction: "
                f"{reconstruction['saved_to']}"
            )


    def close(self) -> None:
        self.db.close()


def main():

    engine = ReconstructionEngine()

    print("\n1. Reconstruct from SQLite")
    print("2. Reconstruct ablated JSON")

    choice = input(
        "\nSelect mode: "
    ).strip()

    try:

        if choice == "1":

            trace_id = input(
                "Enter trace_id: "
            ).strip()

            reconstruction = engine.reconstruct(
                trace_id
            )


        elif choice == "2":

            json_path = input(
                "Enter JSON path: "
            ).strip()

            reconstruction = engine.reconstruct_json(
                json_path
            )


        else:

            print("Invalid choice.")
            return

        engine.print_timeline(
            reconstruction
        )

    finally:
        engine.close()


if __name__ == "__main__":
    main()