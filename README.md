# 🌌 OrionFlow

**A fault-tolerant, event-sourced workflow orchestration engine built from first principles in Python.**

Inspired by **Uber Cadence** and **Temporal.io**, OrionFlow is a distributed orchestrator that executes complex DAG workflows while guaranteeing durable execution, automatic failure recovery, and zero data loss — all backed by a single SQLite database.

---

## 🤔 Why this project?

Most backend systems process tasks sequentially — "do step A, then step B, then step C." But what happens when:

- A server crashes **mid-task**?  
- Two workers grab the **same job**?  
- A network call **times out** and you retry, causing **duplicate charges**?

These are real distributed systems problems. Traditional `cron`-jobs and task queues (Celery, RQ) don't solve them. Systems like Temporal and Cadence do — but they're massive, complex pieces of infrastructure.

**OrionFlow strips that architecture down to its essence** and rebuilds it from scratch in clean Python, so you can see exactly how durable workflow orchestration works under the hood.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        OrionFlow                             │
│                                                              │
│   ┌─────────┐     ┌──────────────┐     ┌────────────────┐   │
│   │  REST    │────▶│  Workflow     │────▶│  Task Queue    │   │
│   │  API     │     │  Engine (DAG) │     │  (SQLite+WAL)  │   │
│   └─────────┘     └──────────────┘     └───────┬────────┘   │
│        │                │                      │             │
│        │          ┌─────▼──────┐         ┌─────▼──────┐      │
│        │          │ Event Store │         │  Worker 1  │      │
│        │          │ (append-   │         │  Worker 2  │      │
│        │          │  only log) │         │  Worker 3  │      │
│        │          └────────────┘         │  Worker N  │      │
│        │                                 └────────────┘      │
│        │          ┌────────────┐         ┌────────────┐      │
│        └─────────▶│  Metrics   │         │  Sweeper   │      │
│                   │  Collector │         │  (recovery)│      │
│                   └────────────┘         └────────────┘      │
└──────────────────────────────────────────────────────────────┘
```

### How each component works:

| Component | What it does | Why it matters |
|-----------|-------------|----------------|
| **REST API** | Accepts workflow submissions via HTTP | Decouples submission from execution |
| **Workflow Engine** | Reads the event log → decides which task to schedule next | Stateless evaluation. Can crash and restart with no data loss |
| **Event Store** | Append-only log of `WorkflowStarted`, `TaskScheduled`, `TaskCompleted`, `TaskFailed` | Single source of truth. Enables replay, debugging, and time-travel |
| **Task Queue** | SQLite table with priority ordering and WAL mode for concurrent reads/writes | Workers can poll safely without lock collisions |
| **Workers** | Stateless daemons that pull tasks, execute them, and emit results | Horizontally scalable — run as many as you want |
| **Sweeper** | Background thread that detects tasks stuck in `RUNNING` state | Recovers from worker crashes automatically |
| **Metrics** | Records latency, wait time, retry counts per task | Powers the live dashboard |

---

## 🔑 Key Design Decisions

### 1. Event Sourcing (not state mutation)
Instead of `UPDATE tasks SET status = 'DONE'`, we **append** an event: `TaskCompleted`. The current state is always reconstructed by replaying the event history. This means:
- Perfect audit trail  
- Deterministic replay for debugging  
- No race conditions from concurrent state updates

### 2. Optimistic Concurrency Control
A `UNIQUE(workflow_id, event_type, step_name)` index on the event log means if two workers try to schedule the same task simultaneously, exactly one succeeds and the other gracefully backs off. No distributed locks needed.

### 3. Priority-based DAG Scheduling
When a DAG step completes, the engine evaluates all downstream dependencies. If multiple tasks become eligible, they're enqueued with their assigned priority. Workers always pick up the highest-priority task first via `ORDER BY priority DESC`.

### 4. Chaos Engineering Built In
Workers support a `CHAOS_MODE` flag that randomly injects: network delays (0.1-1.5s), connection drops (20% chance), and full process kills (10% chance). The sweeper daemon + idempotent retries guarantee zero data loss even under this abuse.

---

## ⚡ Features

- **DAG Workflows** — Define arbitrary dependency graphs via JSON
- **Priority Scheduling** — High-priority tasks jump the queue  
- **Retry with Exponential Backoff** — Failed tasks retry with `2^n` second delays
- **Idempotency** — Duplicate task submissions are safely rejected
- **Crash Recovery** — Sweeper daemon resurrects stuck tasks
- **Chaos Mode** — Built-in failure injection for resilience testing
- **Live Dashboard** — Real-time worker status, queue pressure charts, failure analysis
- **Workflow Visualizer** — Animated DAG replay powered by Mermaid.js
- **Metrics API** — Track latency, throughput, success rates

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| API | Python, FastAPI |
| Persistence | SQLite (WAL mode + B-tree indexes) |
| Data Models | Pydantic v2 |
| Visualization | Mermaid.js, Chart.js, TailwindCSS |
| Testing | Custom chaos simulation scripts |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- pip

### Installation
```bash
git clone https://github.com/YOUR_USERNAME/orionflow.git
cd orionflow
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 1. Start the API Server
```bash
uvicorn orionflow.api.main:app --host 0.0.0.0 --port 8000
```

### 2. Start Worker(s)
Open a new terminal:
```bash
source venv/bin/activate
python -m orionflow.worker.main
```
> **Tip:** Run this command multiple times in separate terminals (or background with `&`) to create a multi-worker cluster!

### 3. Open the UI
Go to **http://localhost:8000** in your browser. You'll see the Control Center where you can:
- Click **"🚀 Trigger DAG & Auto-Visualize"** to instantly launch a workflow and watch it animate
- Click **"📊 Open Live Cluster Dashboard"** to see real-time worker heartbeats, queue pressure, and failure analysis

### 4. Fire a Custom DAG (via curl)
```bash
curl -s -X POST http://localhost:8000/api/v1/workflows/dag \
  -H "Content-Type: application/json" \
  -d '{
    "dag": {
      "Extract": {"task_type": "extract", "priority": 5, "depends_on": []},
      "Transform_A": {"task_type": "transform", "priority": 100, "depends_on": ["Extract"]},
      "Transform_B": {"task_type": "transform", "priority": 10,  "depends_on": ["Extract"]},
      "Load": {"task_type": "load", "priority": 50, "depends_on": ["Transform_A", "Transform_B"]}
    }
  }'
```

---

## 🧪 Testing & Demos

### Run the 1000-Job Stress Test
With the API and workers already running:
```bash
python demo_1000.py
```
This injects 250 DAG workflows (1,000 total tasks) and prints a live progress bar. Watch the dashboard at the same time for maximum effect.

### Enable Chaos Mode
Start a destructive worker that randomly kills itself, drops connections, and injects latency:
```bash
CHAOS_MODE=true python -m orionflow.worker.main
```
The system will automatically recover every failed task via the sweeper daemon with zero data loss.

---

## 📊 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Control Center UI |
| `GET` | `/dashboard` | Live Analytics Dashboard |
| `POST` | `/api/v1/workflows/dag` | Submit a DAG workflow |
| `POST` | `/api/v1/workflows/checkout` | Submit a checkout workflow |
| `POST` | `/api/v1/tasks` | Submit a standalone task |
| `GET` | `/api/v1/workflows/{id}/visualize` | Animated workflow replay |
| `GET` | `/api/v1/workflows/{id}/events` | Raw event log for a workflow |
| `GET` | `/api/v1/metrics` | Aggregated system metrics |
| `GET` | `/api/v1/dashboard/data` | Live dashboard JSON data |
| `GET` | `/health` | Health check |

---

## 📁 Project Structure

```
orionflow/
├── orionflow/
│   ├── api/
│   │   ├── main.py            # FastAPI routes + dashboard serving
│   │   ├── dashboard.html     # Live analytics UI
│   │   ├── visualizer.html    # Animated DAG replay UI
│   │   └── index.html         # Control center landing page
│   ├── core/
│   │   ├── models.py          # Pydantic data models (Task, DAGNode)
│   │   └── events.py          # Event model definition
│   ├── engine/
│   │   └── workflow.py        # DAG evaluation + event-sourced orchestrator
│   ├── storage/
│   │   ├── queue.py           # SQLite task queue + worker heartbeats
│   │   └── event_store.py     # Append-only event log
│   ├── utils/
│   │   └── metrics.py         # Metrics collector
│   └── worker/
│       └── main.py            # Stateless worker daemon
├── demo_1000.py               # 1000-job stress test script
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 🎓 What I Learned Building This

- How **Event Sourcing** eliminates race conditions by treating state as a derived view
- How **Optimistic Concurrency Control** replaces distributed locks with database constraints
- How **Write-Ahead Logging** in SQLite enables concurrent multi-process access
- How **Chaos Engineering** proves system resilience through deliberate failure injection
- How real orchestration systems like Temporal achieve **durable execution** guarantees
