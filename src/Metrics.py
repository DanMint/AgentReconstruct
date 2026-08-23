from pathlib import Path
from typing import Any
import json


class Metrics:

    def __init__(self):

        self.project_root = Path(__file__).resolve().parent.parent


    def load_json(self, path: str | Path) -> dict:

        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(
                f"JSON file not found: {path}"
            )

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)


    def normalize_ground_truth_event(
        self,
        event: dict
    ) -> dict:
        """
        Convert a raw ground-truth event into the same
        semantic format used by ReconstructionEngine.
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


    def normalize_ground_truth(
        self,
        ground_truth: dict
    ) -> list[dict]:

        return [
            self.normalize_ground_truth_event(event)
            for event in ground_truth["events"]
        ]


    def get_event_map(
        self,
        events: list[dict]
    ) -> dict:

        event_map = {}

        for event in events:

            event_id = event.get("event_id")

            if event_id is not None:
                event_map[event_id] = event

        return event_map


    def event_completeness(
        self,
        ground_truth_events: list[dict],
        reconstructed_events: list[dict]
    ) -> dict:
        """
        Measure how many expected events were recovered.
        """

        ground_truth_map = self.get_event_map(
            ground_truth_events
        )

        reconstruction_map = self.get_event_map(
            reconstructed_events
        )

        recovered = []
        missing = []
        wrong_type = []

        for event_id, expected in ground_truth_map.items():

            actual = reconstruction_map.get(event_id)

            if actual is None:
                missing.append(event_id)
                continue

            if (
                actual.get("event_type")
                != expected.get("event_type")
            ):
                wrong_type.append(event_id)
                continue

            recovered.append(event_id)

        total = len(ground_truth_map)

        if total == 0:
            score = 1.0
        else:
            score = len(recovered) / total

        return {
            "score": score,
            "recovered": len(recovered),
            "expected": total,
            "missing_events": missing,
            "wrong_event_type": wrong_type,
        }


    def ordering_fidelity(
        self,
        ground_truth_events: list[dict],
        reconstructed_events: list[dict]
    ) -> dict:
        """
        Compare relative ordering of events that exist
        in both executions.

        Every pair of common events is checked.
        """

        ground_truth_order = [
            event.get("event_id")
            for event in ground_truth_events
            if event.get("event_id") is not None
        ]

        reconstructed_order = [
            event.get("event_id")
            for event in reconstructed_events
            if event.get("event_id") is not None
        ]

        reconstructed_position = {
            event_id: index
            for index, event_id
            in enumerate(reconstructed_order)
        }

        common_events = [
            event_id
            for event_id in ground_truth_order
            if event_id in reconstructed_position
        ]

        correct_pairs = 0
        total_pairs = 0

        for first_index in range(len(common_events)):

            for second_index in range(
                first_index + 1,
                len(common_events)
            ):

                first_event = common_events[first_index]
                second_event = common_events[second_index]

                total_pairs += 1

                if (
                    reconstructed_position[first_event]
                    <
                    reconstructed_position[second_event]
                ):
                    correct_pairs += 1

        if total_pairs == 0:
            score = 1.0
        else:
            score = correct_pairs / total_pairs

        return {
            "score": score,
            "correct_pairs": correct_pairs,
            "total_pairs": total_pairs,
        }


    def dependency_fidelity(
        self,
        ground_truth_dependencies: list[dict],
        reconstructed_dependencies: list[dict]
    ) -> dict:
        """
        Measure dependency precision, recall and F1.
        """

        expected = {
            (
                dependency.get("from_event"),
                dependency.get("to_event"),
                dependency.get("relationship"),
            )
            for dependency in ground_truth_dependencies
        }

        actual = {
            (
                dependency.get("from_event"),
                dependency.get("to_event"),
                dependency.get("relationship"),
            )
            for dependency in reconstructed_dependencies
        }

        correct = expected.intersection(actual)

        missing = expected - actual
        extra = actual - expected

        if len(actual) == 0:

            if len(expected) == 0:
                precision = 1.0
            else:
                precision = 0.0

        else:
            precision = len(correct) / len(actual)


        if len(expected) == 0:
            recall = 1.0
        else:
            recall = len(correct) / len(expected)


        if precision + recall == 0:
            f1 = 0.0
        else:
            f1 = (
                2
                * precision
                * recall
                / (precision + recall)
            )

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "correct_dependencies": len(correct),
            "expected_dependencies": len(expected),
            "reconstructed_dependencies": len(actual),
            "missing_dependencies": [
                {
                    "from_event": item[0],
                    "to_event": item[1],
                    "relationship": item[2],
                }
                for item in sorted(missing)
            ],
            "extra_dependencies": [
                {
                    "from_event": item[0],
                    "to_event": item[1],
                    "relationship": item[2],
                }
                for item in sorted(extra)
            ],
        }


    def payload_event_fidelity(
        self,
        ground_truth_events: list[dict],
        reconstructed_events: list[dict]
    ) -> dict:
        """
        Measure how many reconstructed events have
        exactly the correct semantic content.
        """

        ground_truth_map = self.get_event_map(
            ground_truth_events
        )

        reconstruction_map = self.get_event_map(
            reconstructed_events
        )

        compared = 0
        correct = 0
        mismatched = []

        for event_id, expected in ground_truth_map.items():

            expected_details = expected.get(
                "details",
                {}
            )

            if not expected_details:
                continue

            compared += 1

            actual = reconstruction_map.get(event_id)

            if actual is None:

                mismatched.append({
                    "event_id": event_id,
                    "reason": "EVENT_MISSING",
                })

                continue

            actual_details = actual.get(
                "details",
                {}
            )

            if expected_details == actual_details:
                correct += 1

            else:
                mismatched.append({
                    "event_id": event_id,
                    "event_type": expected.get(
                        "event_type"
                    ),
                    "expected": expected_details,
                    "actual": actual_details,
                })

        if compared == 0:
            score = 1.0
        else:
            score = correct / compared

        return {
            "score": score,
            "correct_events": correct,
            "compared_events": compared,
            "mismatches": mismatched,
        }


    def flatten(
        self,
        value: Any,
        prefix: str = ""
    ) -> dict:
        """
        Convert nested dictionaries and lists into
        individual field paths.
        """

        flattened = {}

        if isinstance(value, dict):

            for key, item in value.items():

                path = (
                    f"{prefix}.{key}"
                    if prefix
                    else key
                )

                flattened.update(
                    self.flatten(
                        item,
                        path
                    )
                )


        elif isinstance(value, list):

            for index, item in enumerate(value):

                path = f"{prefix}[{index}]"

                flattened.update(
                    self.flatten(
                        item,
                        path
                    )
                )


        else:

            flattened[prefix] = value

        return flattened


    def payload_field_fidelity(
        self,
        ground_truth_events: list[dict],
        reconstructed_events: list[dict]
    ) -> dict:
        """
        Compare individual semantic payload fields.

        This is less strict than payload_event_fidelity.
        """

        ground_truth_map = self.get_event_map(
            ground_truth_events
        )

        reconstruction_map = self.get_event_map(
            reconstructed_events
        )

        expected_fields = 0
        correct_fields = 0
        missing_fields = []

        sentinel = object()

        for event_id, expected in ground_truth_map.items():

            expected_details = self.flatten(
                expected.get(
                    "details",
                    {}
                )
            )

            if len(expected_details) == 0:
                continue

            actual = reconstruction_map.get(event_id)

            if actual is None:

                for path in expected_details:

                    expected_fields += 1

                    missing_fields.append({
                        "event_id": event_id,
                        "field": path,
                        "reason": "EVENT_MISSING",
                    })

                continue

            actual_details = self.flatten(
                actual.get(
                    "details",
                    {}
                )
            )

            for path, expected_value in expected_details.items():

                expected_fields += 1

                actual_value = actual_details.get(
                    path,
                    sentinel
                )

                if (
                    actual_value is not sentinel
                    and
                    actual_value == expected_value
                ):
                    correct_fields += 1

                else:
                    missing_fields.append({
                        "event_id": event_id,
                        "field": path,
                        "expected": expected_value,
                        "actual": (
                            None
                            if actual_value is sentinel
                            else actual_value
                        ),
                    })

        if expected_fields == 0:
            score = 1.0
        else:
            score = correct_fields / expected_fields

        return {
            "score": score,
            "correct_fields": correct_fields,
            "expected_fields": expected_fields,
            "field_mismatches": missing_fields,
        }


    def metadata_fidelity(
        self,
        ground_truth_events: list[dict],
        reconstructed_events: list[dict]
    ) -> dict:
        """
        Compare source, destination and timestamp.

        This is reported separately because these fields
        may not be required for semantic reconstruction.
        """

        ground_truth_map = self.get_event_map(
            ground_truth_events
        )

        reconstruction_map = self.get_event_map(
            reconstructed_events
        )

        fields = [
            "source",
            "destination",
            "timestamp",
        ]

        correct = 0
        total = 0
        mismatches = []

        for event_id, expected in ground_truth_map.items():

            actual = reconstruction_map.get(event_id)

            for field in fields:

                total += 1

                expected_value = expected.get(field)

                if actual is None:
                    actual_value = None
                else:
                    actual_value = actual.get(field)

                if expected_value == actual_value:
                    correct += 1

                else:
                    mismatches.append({
                        "event_id": event_id,
                        "field": field,
                        "expected": expected_value,
                        "actual": actual_value,
                    })

        if total == 0:
            score = 1.0
        else:
            score = correct / total

        return {
            "score": score,
            "correct_fields": correct,
            "expected_fields": total,
            "mismatches": mismatches,
        }


    def compare(
        self,
        ground_truth: dict,
        reconstruction: dict
    ) -> dict:
        """
        Compare one reconstructed execution against
        the canonical ground truth.
        """

        ground_truth_events = (
            self.normalize_ground_truth(
                ground_truth
            )
        )

        reconstructed_events = reconstruction.get(
            "timeline",
            []
        )

        events = self.event_completeness(
            ground_truth_events,
            reconstructed_events
        )

        ordering = self.ordering_fidelity(
            ground_truth_events,
            reconstructed_events
        )

        dependencies = self.dependency_fidelity(
            ground_truth.get(
                "dependencies",
                []
            ),
            reconstruction.get(
                "dependencies",
                []
            )
        )

        payload_events = self.payload_event_fidelity(
            ground_truth_events,
            reconstructed_events
        )

        payload_fields = self.payload_field_fidelity(
            ground_truth_events,
            reconstructed_events
        )

        metadata = self.metadata_fidelity(
            ground_truth_events,
            reconstructed_events
        )


        # Main semantic reconstruction score.
        overall_score = (
            events["score"]
            + ordering["score"]
            + dependencies["f1"]
            + payload_events["score"]
        ) / 4


        structural_score = (
            events["score"]
            + ordering["score"]
            + dependencies["f1"]
        ) / 3


        semantic_success = (
            events["score"] == 1.0
            and
            ordering["score"] == 1.0
            and
            dependencies["f1"] == 1.0
            and
            payload_events["score"] == 1.0
        )


        exact_trace_success = (
            semantic_success
            and
            metadata["score"] == 1.0
        )


        return {
            "trace_id": ground_truth.get("trace_id"),

            "overall_score": overall_score,
            "overall_score_percent": overall_score * 100,

            "structural_score": structural_score,
            "structural_score_percent": structural_score * 100,

            "semantic_reconstruction_success":
                semantic_success,

            "exact_trace_reproduction_success":
                exact_trace_success,

            "event_completeness": events,

            "ordering_fidelity": ordering,

            "dependency_fidelity": dependencies,

            "payload_event_fidelity": payload_events,

            "payload_field_fidelity": payload_fields,

            "metadata_fidelity": metadata,
        }


    def save_results(
        self,
        results: dict,
        reconstruction_path: str | Path
    ) -> Path:

        reconstruction_path = Path(
            reconstruction_path
        )

        trace_id = results.get(
            "trace_id",
            "unknown_trace"
        )

        output_directory = (
            self.project_root
            / "data"
            / "metrics"
            / trace_id
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        output_path = (
            output_directory
            / reconstruction_path.name
        )

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                results,
                file,
                indent=4
            )

        return output_path


    def print_results(
        self,
        results: dict
    ) -> None:

        print("\n================================")
        print("RECONSTRUCTION METRICS")
        print("================================")

        print(
            f"\nOverall Score: "
            f"{results['overall_score_percent']:.2f}%"
        )

        print(
            f"Structural Score: "
            f"{results['structural_score_percent']:.2f}%"
        )

        print(
            "\nEvent Completeness:",
            f"{results['event_completeness']['score'] * 100:.2f}%"
        )

        print(
            "Ordering Fidelity:",
            f"{results['ordering_fidelity']['score'] * 100:.2f}%"
        )

        print(
            "Dependency Precision:",
            f"{results['dependency_fidelity']['precision'] * 100:.2f}%"
        )

        print(
            "Dependency Recall:",
            f"{results['dependency_fidelity']['recall'] * 100:.2f}%"
        )

        print(
            "Dependency F1:",
            f"{results['dependency_fidelity']['f1'] * 100:.2f}%"
        )

        print(
            "Payload Event Fidelity:",
            f"{results['payload_event_fidelity']['score'] * 100:.2f}%"
        )

        print(
            "Payload Field Fidelity:",
            f"{results['payload_field_fidelity']['score'] * 100:.2f}%"
        )

        print(
            "Metadata Fidelity:",
            f"{results['metadata_fidelity']['score'] * 100:.2f}%"
        )

        print(
            "\nSemantic Reconstruction Success:",
            results[
                "semantic_reconstruction_success"
            ]
        )

        print(
            "Exact Trace Reproduction Success:",
            results[
                "exact_trace_reproduction_success"
            ]
        )


def main():

    metrics = Metrics()

    trace_id = input(
        "Enter trace_id: "
    ).strip()

    reconstruction_name = input(
        "Enter reconstruction file name: "
    ).strip()

    if not reconstruction_name.endswith(".json"):
        reconstruction_name = (
            f"{reconstruction_name}.json"
        )

    ground_truth_path = (
        metrics.project_root
        / "data"
        / "ground_truth"
        / f"{trace_id}.json"
    )

    reconstruction_path = (
        metrics.project_root
        / "data"
        / "reconstructions"
        / trace_id
        / reconstruction_name
    )

    ground_truth = metrics.load_json(
        ground_truth_path
    )

    reconstruction = metrics.load_json(
        reconstruction_path
    )

    results = metrics.compare(
        ground_truth,
        reconstruction
    )

    metrics.print_results(
        results
    )

    output_path = metrics.save_results(
        results,
        reconstruction_path
    )

    print(
        f"\nMetrics saved to: "
        f"{output_path}"
    )


if __name__ == "__main__":
    main()