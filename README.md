# AgentReconstruct

**Runtime evidence collection, execution reconstruction, and evidence-ablation analysis for tool-using LLM agents.**

AgentReconstruct is a research prototype for studying a simple but important question:

> **What is the minimum runtime evidence required to faithfully reconstruct the execution of a tool-using LLM agent?**

Modern LLM agents interact with language models, external tools, MCP servers, databases, memory systems, and other services. When something goes wrong, the final response alone is often not enough to explain what happened. AgentReconstruct captures observable runtime interactions at trusted boundaries, stores them as a persistent execution trace, reconstructs the execution offline, and then systematically removes pieces of evidence to measure what is actually necessary for accurate reconstruction.

---

## Why This Project Exists

Most agent observability systems focus on collecting rich traces, while replay systems focus on reproducing a recorded run. AgentReconstruct focuses on a different question:

**How much of that trace is actually necessary?**

The project evaluates whether an execution can still be reconstructed after removing evidence such as:

- timestamps
- source and destination fields
- JSON-RPC correlation IDs
- tool arguments
- tool results
- LLM response content
- complete tool-response events
- complete LLM-response events

The long-term goal is to identify a **minimum sufficient runtime evidence set**, or **trace contract**, for forensic reconstruction of LLM-agent executions.

---

## Architecture

```text
                              ┌─────────────────────┐
                              │   Event Recorder    │
                              │      SQLite         │
                              │   Hash-linked log   │
                              └──────▲──────▲──────▲┘
                                     │      │      │
                                  Host   LLM GW   MCP GW
                                  events    │        │
                                     │      │        │
                                     ▼      ▼        ▼
                               ┌──────────┐  LLM    MCP Server
                               │Agent Host│         │
                               └──────────┘      ┌──┼──┐
                                               Tool Tool
```

The system observes three parts of an execution.

### Agent Host

The Agent Host runs the LangChain agent and records host-level lifecycle events:

```text
TRACE_START
USER_INPUT
FINAL_RESPONSE
TRACE_END
```

### LLM Gateway

All model traffic is routed through a trusted LLM gateway:

```text
Agent Host
    ↓
LLM Gateway
    ↓
Ollama
```

The gateway records:

```text
LLM_REQUEST
LLM_RESPONSE
```

### MCP Gateway

Tool traffic is routed through a trusted MCP gateway:

```text
Agent Host
    ↓
MCP Gateway
    ↓
MCP Server
    ↓
Tool
```

The gateway records events including:

```text
MCP_INITIALIZE_REQUEST
MCP_INITIALIZE_RESPONSE
TOOL_LIST_REQUEST
TOOL_LIST_RESPONSE
TOOL_REQUEST
TOOL_RESPONSE
```

### Event Recorder

The Event Recorder stores events persistently in SQLite.

Each event includes:

```text
event_id
trace_id
timestamp
event_type
source
destination
payload
previous_hash
event_hash
```

The Recorder assigns global ordering metadata and links events through a SHA-256 hash chain.

---

## Example Execution

A simple tool-using execution may look like:

```text
TRACE_START
    ↓
USER_INPUT
    ↓
LLM_REQUEST
    ↓
LLM_RESPONSE
    │
    │ requests add(47, 81)
    ↓
TOOL_REQUEST
    ↓
TOOL_RESPONSE = 128
    ↓
LLM_REQUEST
    ↓
LLM_RESPONSE
    ↓
FINAL_RESPONSE
    ↓
TRACE_END
```

AgentReconstruct converts the raw event log into both a chronological execution timeline and a dependency graph.

For example:

```text
LLM_RESPONSE
    ↓ requested_tool
TOOL_REQUEST
    ↓ produced_tool_result
TOOL_RESPONSE
    ↓ tool_result_consumed_by
LLM_REQUEST
```

The system reconstructs **observable execution behavior**. It does not attempt to recover hidden chain-of-thought.

---

## Evidence Ablation

After a complete execution is recorded, AgentReconstruct creates controlled copies of the trace with selected evidence removed.

Current ablation experiments include:

```text
full_evidence
no_timestamps
no_source_destination
no_rpc_ids
no_tool_arguments
no_tool_results
no_llm_content
no_tool_payloads
no_tool_response_events
no_llm_response_events
```

Each ablated trace is reconstructed independently and compared against the complete ground-truth execution.

This allows the project to ask questions such as:

- Are timestamps needed if trusted event ordering already exists?
- Are source and destination fields redundant with event semantics?
- Are JSON-RPC IDs necessary to pair tool requests and responses?
- Are tool arguments required to associate an LLM decision with the correct tool invocation?
- Can the execution chain still be recovered if tool results are missing?
- How much reconstruction quality is lost when an entire LLM response is unavailable?

---

## Reconstruction Metrics

AgentReconstruct evaluates each reconstructed execution against the ground truth using several metrics.

### Event Completeness

Measures how many expected events were recovered.

```text
recovered events / ground-truth events
```

### Ordering Fidelity

Measures whether recovered events preserve the same relative order as the ground-truth execution.

### Dependency Fidelity

Measures whether the correct relationships between events were reconstructed.

The implementation reports:

- precision
- recall
- F1 score

### Payload Fidelity

Measures how much semantic event content was preserved, including:

- user input
- LLM output
- tool name
- tool arguments
- tool result
- RPC identifiers

Both event-level and field-level payload fidelity are measured.

### Metadata Fidelity

Tracks whether fields such as timestamps, source, and destination were reproduced.

Metadata is reported separately because some metadata may not be required to reconstruct agent behavior.

---

## Project Structure

```text
AgentReconstruct/
│
├── main.py
├── run_experiment.sh
├── requirements.txt
│
├── src/
│   ├── Agent.py
│   ├── EventRecorder.py
│   ├── LlmGateway.py
│   ├── McpGateway.py
│   ├── GroundTruth.py
│   ├── EvidenceAblation.py
│   ├── ReconstructionEngine.py
│   ├── Metrics.py
│   │
│   └── tools/
│       └── toolServer.py
│
└── data/
    ├── events.db
    │
    ├── ground_truth/
    │   └── <trace_id>.json
    │
    ├── ablated/
    │   └── <trace_id>/
    │       ├── full_evidence.json
    │       ├── no_rpc_ids.json
    │       └── ...
    │
    ├── reconstructions/
    │   └── <trace_id>/
    │       ├── full_evidence.json
    │       ├── no_rpc_ids.json
    │       └── ...
    │
    ├── metrics/
    │   └── <trace_id>/
    │       ├── full_evidence.json
    │       ├── no_rpc_ids.json
    │       └── summary.csv
    │
    └── experiment_logs/
        └── latest_agent_run.log
```

> Update the tree above if your local filenames use different capitalization.

---

# Running the Project

## 1. Prerequisites

The project requires:

- Python
- Ollama running locally
- a local Ollama model
- Python packages listed in `requirements.txt`

The current prototype routes model traffic to Ollama on:

```text
http://127.0.0.1:11434
```

and uses:

```text
minicpm-v4.5:latest
```

The current MCP integration uses MCP 1.x:

```text
mcp>=1.24.0,<2.0.0
```

---

## 2. Create a Virtual Environment

```bash
python3 -m venv myenv
source myenv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

---

## 3. Start Ollama

Make sure Ollama is running:

```bash
ollama serve
```

Verify that the configured model exists:

```bash
ollama list
```

If needed:

```bash
ollama pull minicpm-v4.5:latest
```

---

## 4. Run a Single Agent Execution

Run:

```bash
python3 main.py
```

The current entry point starts the local components used by the prototype, including:

- Event Recorder
- MCP Tool Server
- MCP Gateway
- LLM Gateway
- Agent Host

A successful execution writes runtime evidence to:

```text
data/events.db
```

---

# Full Experiment Pipeline

The easiest way to run the complete experiment is:

```bash
chmod +x run_experiment.sh
./run_experiment.sh
```

The script automates:

```text
1. Run Agent
2. Detect the newly completed trace_id
3. Create Ground Truth
4. Generate Evidence Ablations
5. Reconstruct every ablated trace
6. Compare each reconstruction with Ground Truth
7. Save reconstruction metrics
8. Generate a summary CSV
```

Results are stored under:

```text
data/ground_truth/<trace_id>.json
data/ablated/<trace_id>/
data/reconstructions/<trace_id>/
data/metrics/<trace_id>/
```

The primary summary is:

```text
data/metrics/<trace_id>/summary.csv
```

---

# Running Individual Components

The full shell script is recommended, but each stage can also be run independently.

## Ground Truth

```bash
python3 src/GroundTruth.py
```

Enter the target `trace_id`.

Output:

```text
data/ground_truth/<trace_id>.json
```

## Evidence Ablation

```bash
python3 src/EvidenceAblation.py
```

Enter the same `trace_id`.

Output:

```text
data/ablated/<trace_id>/
```

## Reconstruction

```bash
python3 src/ReconstructionEngine.py
```

The engine supports:

```text
1. Reconstruct from SQLite
2. Reconstruct ablated JSON
```

Outputs are stored under:

```text
data/reconstructions/<trace_id>/
```

## Metrics

```bash
python3 src/Metrics.py
```

Provide:

1. the `trace_id`
2. the reconstruction filename, such as `no_rpc_ids.json`

Outputs are stored under:

```text
data/metrics/<trace_id>/
```

---

## Current Research Status

- [x] LLM gateway observation
- [x] MCP gateway observation
- [x] host-level lifecycle events
- [x] persistent SQLite event storage
- [x] global event ordering
- [x] hash-linked event chain
- [x] execution reconstruction
- [x] dependency reconstruction
- [x] ground-truth generation
- [x] evidence ablation
- [x] reconstruction metrics
- [x] automated experiment pipeline
- [ ] broader benchmark workloads
- [ ] multi-tool execution scenarios
- [ ] repeated same-tool calls
- [ ] tool failures and malformed responses
- [ ] larger-scale evidence subset search
- [ ] minimum trace-contract evaluation across workloads

---

## Research Direction

The current implementation uses a controlled tool workflow to validate the architecture and experimental pipeline.

The next stage is to evaluate more complex executions, including:

- multiple tools
- repeated calls to the same tool
- longer LLM-tool interaction loops
- failed tool calls
- missing or malformed tool outputs
- different workload structures
- larger combinations of removed evidence

The final research objective is to determine which event classes and fields are **necessary and sufficient** for faithful reconstruction across a representative set of LLM-agent executions.

---

## Threat Model

The current research prototype assumes that:

- the LLM and agent behavior may be untrusted
- user input may be malicious
- tool or retrieved content may be malicious
- the LLM Gateway is trusted
- the MCP Gateway is trusted
- the Event Recorder is trusted
- the persistent event store is trusted during recording

The current hash chain supports integrity and ordering verification under this model. It is not intended to defend against an attacker with unrestricted write access to the Recorder and all stored evidence.

---

## Technology Stack

- **Python**
- **FastAPI**
- **HTTPX**
- **LangChain**
- **LangChain Ollama**
- **Ollama**
- **Model Context Protocol (MCP)**
- **SQLite**
- **Uvicorn**

---

## Research Use

AgentReconstruct is currently a research prototype rather than a production observability platform.

The project may be relevant to work involving:

- agentic AI security
- LLM observability
- AI forensics
- agent provenance
- runtime assurance
- MCP security
- agent replay
- trustworthy autonomous systems

---

## License

Add the license you intend to use before publishing the repository. Common choices for research software include MIT, Apache 2.0, and BSD 3-Clause.

---

## Citation

A paper describing AgentReconstruct and its evidence-ablation methodology is currently in development.

A citation entry will be added once the work is publicly available.
