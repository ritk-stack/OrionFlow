from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, Any
import uuid
import sqlite3
import logging
import json
import time
import datetime as dt
from orionflow.core.models import TaskRequest, Task, DAGWorkflowRequest
from orionflow.storage.queue import SqliteTaskQueue
from orionflow.engine.workflow import WorkflowEngine
from orionflow.storage.event_store import SqliteEventStore
from orionflow.core.events import Event
from orionflow.utils.metrics import SqliteMetricsStore
import uvicorn
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="OrionFlow API")
queue = SqliteTaskQueue()
event_store = SqliteEventStore()
metrics_store = SqliteMetricsStore()
engine = WorkflowEngine(queue, event_store)

@app.post("/api/v1/tasks", response_model=Dict[str, Any])
def submit_task(request: TaskRequest):
    task_id = request.task_id or str(uuid.uuid4())
    task = Task(task_id=task_id, task_type=request.task_type, payload=request.payload, workflow_id=request.workflow_id, step_name=request.step_name)
    enqueued = queue.enqueue(task)
    if not enqueued: return {"status": "ignored", "message": f"Task {task.task_id} already exists."}
    return {"status": "success", "task": task}

@app.post("/api/v1/workflows/checkout")
def start_checkout_workflow():
    workflow_id = f"checkout-{str(uuid.uuid4())[:8]}"
    event_store.append(Event(workflow_id=workflow_id, event_type="WorkflowStarted", details={"checkout": True}))
    engine.evaluate(workflow_id)
    return {"status": "started", "workflow_id": workflow_id}

@app.post("/api/v1/workflows/dag")
def start_dag_workflow(request: DAGWorkflowRequest):
    workflow_id = f"dag-{str(uuid.uuid4())[:8]}"
    event_store.append(Event(workflow_id=workflow_id, event_type="WorkflowStarted", details={"dag": request.model_dump()["dag"]}))
    engine.evaluate(workflow_id)
    return {"status": "started", "workflow_id": workflow_id}

@app.get("/health")
def health_check(): return {"status": "ok"}

@app.get("/api/v1/metrics")
def query_system_metrics():
    return metrics_store.get_summary()

@app.get("/", response_class=HTMLResponse)
def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    return FileResponse(os.path.join(os.path.dirname(__file__), "dashboard.html"))

@app.get("/api/v1/workflows/{workflow_id}/visualize", response_class=HTMLResponse)
def serve_visualizer(workflow_id: str):
    return FileResponse(os.path.join(os.path.dirname(__file__), "visualizer.html"))

@app.get("/api/v1/workflows/{workflow_id}/events")
def get_workflow_events(workflow_id: str):
    history = event_store.get_history(workflow_id)
    return [e.model_dump() for e in history]

@app.get("/api/v1/dashboard/data")
def get_dashboard_data():
    summary = metrics_store.get_summary()
    workers = queue.get_workers()
    
    with sqlite3.connect(queue.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM queue WHERE status = 'PENDING'")
        queued = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM queue WHERE status = 'RUNNING'")
        running = cursor.fetchone()[0]
        
    counts = {
        "queued": queued,
        "running": running,
        "completed": summary.get("total_tasks", 0),
        "failed": 0
    }
    
    failures = []
    with sqlite3.connect(metrics_store.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM metrics WHERE status = 'FAILED'")
        row = cursor.fetchone()
        if row: counts["failed"] = row[0]
        
        cursor.execute("SELECT task_type, COUNT(*), MAX(timestamp) FROM metrics WHERE status = 'FAILED' GROUP BY task_type")
        for row in cursor.fetchall():
            failures.append({"task_type": row[0], "count": row[1], "last_occurrence": row[2]})
            
    timeseries = []
    with sqlite3.connect(metrics_store.db_path) as conn:
        cursor = conn.cursor()
        # Group metrics cleanly by exactly 10-second intervals for real-time visualization Heatmaps!
        cursor.execute("SELECT substr(timestamp, 1, 15) || '0', COUNT(*), AVG(queue_wait_time_ms) FROM metrics GROUP BY 1 ORDER BY 1 DESC LIMIT 30")
        for row in cursor.fetchall():
            timeseries.append({"time": row[0], "completed": row[1], "avg_wait": row[2] or 0})
            
    return {"counts": counts, "workers": workers, "failures": failures, "timeseries": timeseries[::-1]}

if __name__ == "__main__":
    uvicorn.run("orionflow.api.main:app", host="0.0.0.0", port=8000, reload=True)
