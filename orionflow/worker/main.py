import time
import logging
import os
import json
import random
import threading
import uuid
import datetime as dt
from orionflow.storage.queue import SqliteTaskQueue
from orionflow.storage.event_store import SqliteEventStore
from orionflow.core.models import Task
from orionflow.engine.workflow import WorkflowEngine
from orionflow.core.events import Event
from orionflow.utils.metrics import SqliteMetricsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("worker")

SIMULATE_FAILURE = False
CHAOS_MODE = os.environ.get("CHAOS_MODE") == "true"

WORKER_ID = f"worker-{uuid.uuid4().hex[:6]}"
CURRENT_TASK = None
IS_BUSY = False

def heartbeat_loop(queue: SqliteTaskQueue):
    while True:
        try:
            status = "BUSY" if IS_BUSY else "IDLE"
            queue.heartbeat(WORKER_ID, status, CURRENT_TASK)
        except Exception: pass
        time.sleep(1)

def recovery_sweeper(queue: SqliteTaskQueue):
    while True:
        try:
            recovered = queue.recover_stuck_tasks(timeout_seconds=5)
            if recovered > 0: logger.warning(f"SWEEPER: Recovered {recovered} crashed tasks actively trapped in RUNNING!")
        except Exception: pass
        time.sleep(5)

def execute_task(task: Task, queue: SqliteTaskQueue, event_store: SqliteEventStore, metrics_store: SqliteMetricsStore):
    global CURRENT_TASK, IS_BUSY
    CURRENT_TASK = task.task_id
    IS_BUSY = True

    try:
        logger.info(f"[{WORKER_ID}] Executing {task.task_id} (Type: {task.task_type}, Priority: {task.priority})")
        status, result = "SUCCESS", "ok"

        if CHAOS_MODE:
            time.sleep(random.uniform(0.1, 1.5))
            r = random.random()
            if r < 0.2: raise Exception("Chaos Network Drop Timeout")
            if r < 0.3: raise Exception("Intermittent DB Fault")
            if r < 0.4: os._exit(1)

        if task.task_type == "charge_action" and SIMULATE_FAILURE: status = "FAILED"
        time.sleep(0.2) # Baseline Work
        
        queue.complete(task.task_id, str(result), status)
        
        now = dt.datetime.now(dt.timezone.utc)
        wait_time = (task.start_time - task.enqueued_at).total_seconds() * 1000 if (task.enqueued_at and task.start_time) else 0.0
        exec_time = (now - task.start_time).total_seconds() * 1000 if task.start_time else 0.0
        metrics_store.record(task.task_id, task.task_type, wait_time, exec_time, task.retries, status)
        
        if task.workflow_id:
            event_type = "TaskCompleted" if status == "SUCCESS" else "TaskFailed"
            event_store.append(Event(workflow_id=task.workflow_id, event_type=event_type, details={"step_name": task.step_name, "result": result}))
            WorkflowEngine(queue, event_store).evaluate(task.workflow_id)
            
    finally:
        CURRENT_TASK = None
        IS_BUSY = False
        
def start_worker():
    queue = SqliteTaskQueue()
    event_store = SqliteEventStore()
    metrics_store = SqliteMetricsStore()
    
    threading.Thread(target=recovery_sweeper, args=(queue,), daemon=True).start()
    threading.Thread(target=heartbeat_loop, args=(queue,), daemon=True).start()
    
    logger.info(f"[{WORKER_ID}] Worker startup complete. Mapping explicit cluster heartbeat integrations natively.")
    while True:
        try:
            task = queue.dequeue(timeout=0)
            if task:
                try:
                    execute_task(task, queue, event_store, metrics_store)
                except Exception as e:
                    logger.error(f"Task {task.task_id} logically caught bounded fault: {e}")
                    CURRENT_TASK = None; IS_BUSY = False
                    if task.retries < getattr(task, 'max_retries', 3):
                        task.retries += 1
                        queue.schedule_retry(task.task_id, task.retries, 2)
                    else:
                        queue.complete(task.task_id, str(e), "FAILED")
                        metrics_store.record(task.task_id, task.task_type, 0.0, 0.0, task.retries, "FAILED")
                        if task.workflow_id:
                             event_store.append(Event(workflow_id=task.workflow_id, event_type="TaskFailed", details={"step_name": task.step_name, "error": str(e)}))
                             WorkflowEngine(queue, event_store).evaluate(task.workflow_id)
        except KeyboardInterrupt: break
        except Exception: time.sleep(1)

if __name__ == "__main__":
    start_worker()
