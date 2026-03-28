from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List
import uuid
from datetime import datetime, timezone

class TaskRequest(BaseModel):
    task_id: Optional[str] = None
    task_type: str
    payload: Dict[str, Any]
    workflow_id: Optional[str] = None
    step_name: Optional[str] = None

class DAGNode(BaseModel):
    task_type: str
    priority: int = 0
    depends_on: List[str] = []

class DAGWorkflowRequest(BaseModel):
    dag: Dict[str, DAGNode]

class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str
    payload: Dict[str, Any]
    status: str = "PENDING"
    result: Optional[Any] = None
    enqueued_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    workflow_id: Optional[str] = None
    step_name: Optional[str] = None
    retries: int = 0
    max_retries: int = 3
    next_retry_at: Optional[datetime] = None
    priority: int = 0
