#!/bin/bash

set -euo pipefail


# ============================================================
# Configuration
# ============================================================

PYTHON="${PYTHON:-python3}"

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

DATA_DIR="$PROJECT_ROOT/data"

DB_PATH="$DATA_DIR/events.db"

GROUND_TRUTH_SCRIPT="$PROJECT_ROOT/src/GroundTruth.py"

ABLATION_SCRIPT="$PROJECT_ROOT/src/EvidenceAblation.py"

RECONSTRUCTION_SCRIPT="$PROJECT_ROOT/src/ReconstructionEngine.py"

METRICS_SCRIPT="$PROJECT_ROOT/src/Metrics.py"

LOG_DIR="$DATA_DIR/experiment_logs"

mkdir -p "$LOG_DIR"


# ============================================================
# Find Agent Script
# ============================================================

if [ -f "$PROJECT_ROOT/main.py" ]; then
    AGENT_SCRIPT="$PROJECT_ROOT/main.py"

elif [ -f "$PROJECT_ROOT/src/main.py" ]; then
    AGENT_SCRIPT="$PROJECT_ROOT/src/main.py"

else
    echo "ERROR: Could not find main.py"
    exit 1
fi


echo ""
echo "============================================"
echo "AGENTTRACE EXPERIMENT"
echo "============================================"
echo ""

echo "Project:"
echo "$PROJECT_ROOT"

echo ""


# ============================================================
# Step 1 - Run Agent
# ============================================================

echo "============================================"
echo "STEP 1 - RUNNING AGENT"
echo "============================================"
echo ""

"$PYTHON" "$AGENT_SCRIPT" | tee "$LOG_DIR/latest_agent_run.log"


# ============================================================
# Step 2 - Find Latest Completed Trace ID
# ============================================================

echo ""
echo "============================================"
echo "STEP 2 - FINDING TRACE ID"
echo "============================================"
echo ""


if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: Database does not exist:"
    echo "$DB_PATH"
    exit 1
fi


TRACE_ID=$(
    "$PYTHON" - "$DB_PATH" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]

db = sqlite3.connect(db_path)

cursor = db.execute(
    """
    SELECT trace_id
    FROM events
    WHERE event_type = 'TRACE_END'
    ORDER BY event_id DESC
    LIMIT 1
    """
)

row = cursor.fetchone()

db.close()

if row is None:
    sys.exit(1)

print(row[0])
PY
)


if [ -z "$TRACE_ID" ]; then
    echo "ERROR: Could not determine trace ID."
    exit 1
fi


echo "Trace ID:"
echo "$TRACE_ID"


# ============================================================
# Step 3 - Create Ground Truth
# ============================================================

echo ""
echo "============================================"
echo "STEP 3 - CREATING GROUND TRUTH"
echo "============================================"
echo ""


printf "%s\n" "$TRACE_ID" | \
    "$PYTHON" "$GROUND_TRUTH_SCRIPT"


GROUND_TRUTH_PATH="$DATA_DIR/ground_truth/$TRACE_ID.json"


if [ ! -f "$GROUND_TRUTH_PATH" ]; then
    echo "ERROR: Ground truth was not created."
    exit 1
fi


# ============================================================
# Step 4 - Create Ablations
# ============================================================

echo ""
echo "============================================"
echo "STEP 4 - CREATING ABLATIONS"
echo "============================================"
echo ""


printf "%s\n" "$TRACE_ID" | \
    "$PYTHON" "$ABLATION_SCRIPT"


ABLATION_DIR="$DATA_DIR/ablated/$TRACE_ID"


if [ ! -d "$ABLATION_DIR" ]; then
    echo "ERROR: Ablation directory was not created."
    exit 1
fi


# ============================================================
# Step 5 - Reconstruct Every Ablated Trace
# ============================================================

echo ""
echo "============================================"
echo "STEP 5 - RECONSTRUCTING ABLATED TRACES"
echo "============================================"
echo ""


FOUND_ABLATION=false


for JSON_FILE in "$ABLATION_DIR"/*.json
do

    if [ ! -e "$JSON_FILE" ]; then
        continue
    fi

    FOUND_ABLATION=true

    FILE_NAME="$(basename "$JSON_FILE")"

    echo ""
    echo "--------------------------------------------"
    echo "Reconstructing: $FILE_NAME"
    echo "--------------------------------------------"


    printf "2\n%s\n" "$JSON_FILE" | \
        "$PYTHON" "$RECONSTRUCTION_SCRIPT"

done


if [ "$FOUND_ABLATION" = false ]; then
    echo "ERROR: No ablation JSON files found."
    exit 1
fi


# ============================================================
# Step 6 - Run Metrics on Every Reconstruction
# ============================================================

echo ""
echo "============================================"
echo "STEP 6 - CALCULATING METRICS"
echo "============================================"
echo ""


RECONSTRUCTION_DIR="$DATA_DIR/reconstructions/$TRACE_ID"


if [ ! -d "$RECONSTRUCTION_DIR" ]; then
    echo "ERROR: Reconstruction directory was not created."
    exit 1
fi


FOUND_RECONSTRUCTION=false


for JSON_FILE in "$RECONSTRUCTION_DIR"/*.json
do

    if [ ! -e "$JSON_FILE" ]; then
        continue
    fi

    FOUND_RECONSTRUCTION=true

    FILE_NAME="$(basename "$JSON_FILE")"

    echo ""
    echo "--------------------------------------------"
    echo "Metrics: $FILE_NAME"
    echo "--------------------------------------------"


    printf "%s\n%s\n" \
        "$TRACE_ID" \
        "$FILE_NAME" | \
        "$PYTHON" "$METRICS_SCRIPT"

done


if [ "$FOUND_RECONSTRUCTION" = false ]; then
    echo "ERROR: No reconstruction JSON files found."
    exit 1
fi


# ============================================================
# Step 7 - Create Summary CSV
# ============================================================

echo ""
echo "============================================"
echo "STEP 7 - CREATING SUMMARY"
echo "============================================"
echo ""


METRICS_DIR="$DATA_DIR/metrics/$TRACE_ID"

SUMMARY_PATH="$METRICS_DIR/summary.csv"


"$PYTHON" - "$METRICS_DIR" "$SUMMARY_PATH" <<'PY'
from pathlib import Path
import csv
import json
import sys


metrics_dir = Path(sys.argv[1])
summary_path = Path(sys.argv[2])


rows = []


for path in sorted(metrics_dir.glob("*.json")):

    if path.name == "summary.json":
        continue

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)


    rows.append({
        "experiment":
            path.stem,

        "overall_score":
            round(
                data.get(
                    "overall_score_percent",
                    0
                ),
                2
            ),

        "structural_score":
            round(
                data.get(
                    "structural_score_percent",
                    0
                ),
                2
            ),

        "event_completeness":
            round(
                data.get(
                    "event_completeness",
                    {}
                ).get(
                    "score",
                    0
                ) * 100,
                2
            ),

        "ordering_fidelity":
            round(
                data.get(
                    "ordering_fidelity",
                    {}
                ).get(
                    "score",
                    0
                ) * 100,
                2
            ),

        "dependency_precision":
            round(
                data.get(
                    "dependency_fidelity",
                    {}
                ).get(
                    "precision",
                    0
                ) * 100,
                2
            ),

        "dependency_recall":
            round(
                data.get(
                    "dependency_fidelity",
                    {}
                ).get(
                    "recall",
                    0
                ) * 100,
                2
            ),

        "dependency_f1":
            round(
                data.get(
                    "dependency_fidelity",
                    {}
                ).get(
                    "f1",
                    0
                ) * 100,
                2
            ),

        "payload_event_fidelity":
            round(
                data.get(
                    "payload_event_fidelity",
                    {}
                ).get(
                    "score",
                    0
                ) * 100,
                2
            ),

        "payload_field_fidelity":
            round(
                data.get(
                    "payload_field_fidelity",
                    {}
                ).get(
                    "score",
                    0
                ) * 100,
                2
            ),

        "metadata_fidelity":
            round(
                data.get(
                    "metadata_fidelity",
                    {}
                ).get(
                    "score",
                    0
                ) * 100,
                2
            ),

        "semantic_success":
            data.get(
                "semantic_reconstruction_success",
                False
            ),

        "exact_trace_success":
            data.get(
                "exact_trace_reproduction_success",
                False
            ),
    })


fieldnames = [
    "experiment",
    "overall_score",
    "structural_score",
    "event_completeness",
    "ordering_fidelity",
    "dependency_precision",
    "dependency_recall",
    "dependency_f1",
    "payload_event_fidelity",
    "payload_field_fidelity",
    "metadata_fidelity",
    "semantic_success",
    "exact_trace_success",
]


with open(
    summary_path,
    "w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.DictWriter(
        file,
        fieldnames=fieldnames
    )

    writer.writeheader()

    writer.writerows(rows)


print(f"Summary created: {summary_path}")
PY


# ============================================================
# Finished
# ============================================================

echo ""
echo "============================================"
echo "EXPERIMENT COMPLETE"
echo "============================================"
echo ""

echo "Trace ID:"
echo "$TRACE_ID"

echo ""

echo "Ground Truth:"
echo "$GROUND_TRUTH_PATH"

echo ""

echo "Ablations:"
echo "$ABLATION_DIR"

echo ""

echo "Reconstructions:"
echo "$RECONSTRUCTION_DIR"

echo ""

echo "Metrics:"
echo "$METRICS_DIR"

echo ""

echo "Summary:"
echo "$SUMMARY_PATH"

echo ""