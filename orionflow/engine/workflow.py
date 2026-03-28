import logging
from typing import Dict, Any, List
from orionflow.core.models import Task
from orionflow.storage.queue import SqliteTaskQueue
from orionflow.core.events import Event
from orionflow.storage.event_store import SqliteEventStore

logger = logging.getLogger("engine")

class WorkflowEngine:
    def __init__(self, queue: SqliteTaskQueue, event_store: SqliteEventStore):
        self.queue = queue
        self.event_store = event_store

    def evaluate(self, workflow_id: str):
        history = self.event_store.get_history(workflow_id)
        if not history:
            return "NOT_FOUND"
            
        start_event = history[0]
        if start_event.event_type != "WorkflowStarted":
            return "INVALID"
            
        dag = start_event.details.get("dag")
        if not dag:
            return self._evaluate_checkout(workflow_id, history)
            
        return self._evaluate_dag(workflow_id, dag, history)

    def _evaluate_dag(self, workflow_id: str, dag: Dict[str, dict], history: List[Event]):
        completed = set()
        failed = set()
        scheduled = set()
        
        for event in history:
            step = event.details.get("step_name")
            if event.event_type == "TaskCompleted":
                completed.add(step)
            elif event.event_type == "TaskFailed":
                failed.add(step)
            elif event.event_type == "TaskScheduled":
                scheduled.add(step)
                
        if failed:
            logger.info(f"Workflow {workflow_id} FAILED permanently because task(s) failed: {failed}")
            return "FAILED"
            
        if len(completed) == len(dag):
            logger.info(f"DAG Workflow {workflow_id} fully COMPLETED gracefully!")
            return "COMPLETED"
            
        # O(N) evaluation over the localized DAG definition limits
        for node_name, node_info in dag.items():
            if node_name in scheduled:
                continue 
                
            depends_on = node_info.get("depends_on", [])
            eligible = all(dep in completed for dep in depends_on)
            
            if eligible:
                priority = node_info.get("priority", 0)
                task_type = node_info.get("task_type", "unknown")
                
                event = Event(workflow_id=workflow_id, event_type="TaskScheduled", details={"step_name": node_name})
                if self.event_store.append(event):
                    task = Task(
                        task_id=f"{workflow_id}-{node_name}",
                        task_type=task_type,
                        payload={},
                        workflow_id=workflow_id,
                        step_name=node_name,
                        priority=priority
                    )
                    self.queue.enqueue(task)
                    logger.info(f"DAG Engine globally scheduled node {node_name} (Priority {priority}) for workflow {workflow_id}")
        
        return "RUNNING"
        
    def _evaluate_checkout(self, workflow_id: str, history: List[Event]):
        results = {}
        scheduled = set()
        
        for event in history:
            step_name = event.details.get("step_name")
            if event.event_type == "TaskScheduled":
                scheduled.add(step_name)
            elif event.event_type == "TaskCompleted":
                results[step_name] = "SUCCESS"
            elif event.event_type == "TaskFailed":
                results[step_name] = "FAILED"

        if "ReserveInventory" not in scheduled:
            self._schedule(workflow_id, "ReserveInventory", "reserve_action", {})
            return "RUNNING"
        if "ReserveInventory" not in results: return "RUNNING"
        if results["ReserveInventory"] != "SUCCESS": return "FAILED"

        if "ChargeCreditCard" not in scheduled:
            self._schedule(workflow_id, "ChargeCreditCard", "charge_action", {})
            return "RUNNING"
        if "ChargeCreditCard" not in results: return "RUNNING"

        if results["ChargeCreditCard"] == "SUCCESS":
            if "ShipOrder" not in scheduled:
                self._schedule(workflow_id, "ShipOrder", "ship_action", {})
                return "RUNNING"
            if "ShipOrder" in results: return "COMPLETED"
            return "RUNNING"
        else:
            if "CancelOrder" not in scheduled:
                self._schedule(workflow_id, "CancelOrder", "cancel_action", {})
                return "RUNNING"
            if "CancelOrder" in results: return "COMPLETED_WITH_CANCELLATION"
            return "RUNNING"

    def _schedule(self, workflow_id: str, step_name: str, task_type: str, payload: dict):
        event = Event(workflow_id=workflow_id, event_type="TaskScheduled", details={"step_name": step_name})
        if not self.event_store.append(event): return
        task = Task(task_id=f"{workflow_id}-{step_name}", task_type=task_type, payload=payload, workflow_id=workflow_id, step_name=step_name)
        self.queue.enqueue(task)
