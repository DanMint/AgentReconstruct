from pathlib import Path
from typing import Optional
import sqlite3
import json


class GroundTruth:

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
        Load the complete trusted trace from the Recorder.
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


    def extract_execution(self, events: list[dict]) -> list[dict]:
        """
        Extract the user execution between TRACE_START
        and TRACE_END.
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


    def find_next_event(
        self,
        events: list[dict],
        start_index: int,
        event_type: str
    ) -> Optional[dict]:

        for index in range(start_index + 1, len(events)):

            if events[index]["event_type"] == event_type:
                return events[index]

        return None


    def build_dependencies(self, events: list[dict]) -> list[dict]:
        """
        Construct the canonical dependency graph from
        the complete trusted execution.
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


    def build(self, trace_id: str) -> dict:
        """
        Build the canonical ground-truth execution.
        """

        all_events = self.load_trace(trace_id)

        if len(all_events) == 0:
            raise ValueError(
                f"No events found for trace_id: {trace_id}"
            )

        execution_events = self.extract_execution(all_events)

        dependencies = self.build_dependencies(
            execution_events
        )

        return {
            "trace_id": trace_id,
            "event_count": len(execution_events),
            "events": execution_events,
            "dependencies": dependencies,
        }


    def save(self, ground_truth: dict) -> Path:
        """
        Save an immutable experimental ground-truth
        representation as JSON.
        """

        project_root = Path(__file__).resolve().parent.parent

        output_directory = (
            project_root
            / "data"
            / "ground_truth"
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        output_path = (
            output_directory
            / f"{ground_truth['trace_id']}.json"
        )

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                ground_truth,
                file,
                indent=4
            )

        return output_path


    def close(self) -> None:
        self.db.close()


def main():

    ground_truth_builder = GroundTruth()

    trace_id = input(
        "Enter trace_id: "
    ).strip()

    try:

        ground_truth = ground_truth_builder.build(
            trace_id
        )

        output_path = ground_truth_builder.save(
            ground_truth
        )

        print(
            f"\nGround truth created."
        )

        print(
            f"Events: {ground_truth['event_count']}"
        )

        print(
            f"Dependencies: "
            f"{len(ground_truth['dependencies'])}"
        )

        print(
            f"Saved to: {output_path}"
        )

    finally:
        ground_truth_builder.close()


if __name__ == "__main__":
    main()