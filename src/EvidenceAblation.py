from copy import deepcopy
from pathlib import Path
import random
import json


class EvidenceAblation:

    def copy_events(self, events: list[dict]) -> list[dict]:
        """
        Create a copy of the events so the original
        ground truth is never modified.
        """

        return deepcopy(events)


    def remove_event_types(
        self,
        events: list[dict],
        event_types: list[str]
    ) -> list[dict]:
        """
        Remove complete event types.
        """

        ablated = self.copy_events(events)

        return [
            event
            for event in ablated
            if event.get("event_type") not in event_types
        ]


    def remove_fields(
        self,
        events: list[dict],
        fields: list[str]
    ) -> list[dict]:
        """
        Remove top-level event fields.
        """

        ablated = self.copy_events(events)

        for event in ablated:

            for field in fields:

                if field in event:
                    del event[field]

        return ablated


    def remove_payloads(
        self,
        events: list[dict],
        event_types: list[str] | None = None
    ) -> list[dict]:
        """
        Remove payload contents from selected events.
        """

        ablated = self.copy_events(events)

        for event in ablated:

            if (
                event_types is None
                or
                event.get("event_type") in event_types
            ):
                event["payload"] = {}

        return ablated


    def remove_rpc_ids(
        self,
        events: list[dict]
    ) -> list[dict]:
        """
        Remove JSON-RPC IDs used to pair requests
        and responses.
        """

        ablated = self.copy_events(events)

        for event in ablated:

            if event.get("event_type") not in (
                "TOOL_REQUEST",
                "TOOL_RESPONSE",
            ):
                continue

            payload = event.get("payload", {})

            if "id" in payload:
                del payload["id"]

        return ablated


    def remove_tool_arguments(
        self,
        events: list[dict]
    ) -> list[dict]:
        """
        Remove tool arguments from LLM tool calls
        and TOOL_REQUEST events.
        """

        ablated = self.copy_events(events)

        for event in ablated:

            event_type = event.get("event_type")

            if event_type == "LLM_RESPONSE":

                payload = event.get("payload", {})
                message = payload.get("message", {})
                tool_calls = message.get("tool_calls", [])

                for tool_call in tool_calls:

                    function = tool_call.get(
                        "function",
                        {}
                    )

                    if "arguments" in function:
                        del function["arguments"]


            elif event_type == "TOOL_REQUEST":

                payload = event.get("payload", {})
                params = payload.get("params", {})

                if "arguments" in params:
                    del params["arguments"]

        return ablated


    def remove_tool_results(
        self,
        events: list[dict]
    ) -> list[dict]:
        """
        Keep TOOL_RESPONSE events but remove
        the returned tool result.
        """

        ablated = self.copy_events(events)

        for event in ablated:

            if event.get("event_type") != "TOOL_RESPONSE":
                continue

            payload = event.get("payload", {})
            result = payload.get("result", {})

            if "content" in result:
                del result["content"]

            if "structuredContent" in result:
                del result["structuredContent"]

        return ablated


    def remove_llm_contents(
        self,
        events: list[dict]
    ) -> list[dict]:
        """
        Remove textual content from LLM responses.
        """

        ablated = self.copy_events(events)

        for event in ablated:

            if event.get("event_type") != "LLM_RESPONSE":
                continue

            payload = event.get("payload", {})
            message = payload.get("message", {})

            if "content" in message:
                del message["content"]

        return ablated


    def shuffle_events(
        self,
        events: list[dict],
        seed: int = 42
    ) -> list[dict]:
        """
        Randomize event ordering.
        """

        ablated = self.copy_events(events)

        random_generator = random.Random(seed)

        random_generator.shuffle(ablated)

        return ablated


    def create_default_ablations(
        self,
        events: list[dict]
    ) -> dict[str, list[dict]]:
        """
        Create the initial evidence-ablation experiments.
        """

        return {
            "full_evidence":
                self.copy_events(events),

            "no_timestamps":
                self.remove_fields(
                    events,
                    ["timestamp"]
                ),

            "no_source_destination":
                self.remove_fields(
                    events,
                    ["source", "destination"]
                ),

            "no_tool_response_events":
                self.remove_event_types(
                    events,
                    ["TOOL_RESPONSE"]
                ),

            "no_llm_response_events":
                self.remove_event_types(
                    events,
                    ["LLM_RESPONSE"]
                ),

            "no_rpc_ids":
                self.remove_rpc_ids(
                    events
                ),

            "no_tool_arguments":
                self.remove_tool_arguments(
                    events
                ),

            "no_tool_results":
                self.remove_tool_results(
                    events
                ),

            "no_llm_content":
                self.remove_llm_contents(
                    events
                ),

            "no_tool_payloads":
                self.remove_payloads(
                    events,
                    [
                        "TOOL_REQUEST",
                        "TOOL_RESPONSE"
                    ]
                ),
        }


    def save_ablation(
        self,
        trace_id: str,
        experiment_name: str,
        events: list[dict]
    ) -> Path:
        """
        Save an ablated execution to JSON.
        """

        project_root = Path(__file__).resolve().parent.parent

        output_directory = (
            project_root
            / "data"
            / "ablated"
            / trace_id
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        output_path = (
            output_directory
            / f"{experiment_name}.json"
        )

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                events,
                file,
                indent=4
            )

        return output_path


def main():

    project_root = Path(__file__).resolve().parent.parent

    trace_id = input(
        "Enter trace_id: "
    ).strip()

    ground_truth_path = (
        project_root
        / "data"
        / "ground_truth"
        / f"{trace_id}.json"
    )

    if not ground_truth_path.exists():
        print(
            f"\nGround truth not found: "
            f"{ground_truth_path}"
        )

        print(
            "Run GroundTruth.py first."
        )

        return


    # Load ground truth
    with open(
        ground_truth_path,
        "r",
        encoding="utf-8"
    ) as file:

        ground_truth = json.load(file)


    events = ground_truth["events"]

    print(
        f"\nGround truth loaded."
    )

    print(
        f"Events: {len(events)}"
    )


    # Create ablation experiments
    ablator = EvidenceAblation()

    experiments = ablator.create_default_ablations(
        events
    )


    print(
        f"\nCreating "
        f"{len(experiments)} ablation experiments...\n"
    )


    # Save every experiment
    for experiment_name, ablated_events in experiments.items():

        output_path = ablator.save_ablation(
            trace_id,
            experiment_name,
            ablated_events
        )

        print(
            f"{experiment_name}"
        )

        print(
            f"    Events: "
            f"{len(ablated_events)}"
        )

        print(
            f"    Saved: "
            f"{output_path}"
        )


    print(
        "\nEvidence ablation complete."
    )


if __name__ == "__main__":
    main()