from pydantic import BaseModel, Field
import uuid
from typing import Any, Dict, Optional
from datetime import datetime, timezone

class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    event_type: str # WorkflowStarted, TaskScheduled, TaskCompleted, TaskFailed
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = Field(default_factory=dict)
