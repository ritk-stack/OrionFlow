import sqlite3
import json
import logging
from typing import List
from orionflow.core.events import Event

logger = logging.getLogger("engine")

class SqliteEventStore:
    def __init__(self, db_path="orionflow.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute('''CREATE TABLE IF NOT EXISTS event_log
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                             workflow_id TEXT,
                             event_type TEXT,
                             payload TEXT,
                             timestamp TEXT,
                             step_name TEXT)''')
            conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_step_event 
                            ON event_log(workflow_id, event_type, step_name) 
                            WHERE step_name IS NOT NULL AND event_type = 'TaskScheduled' ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_event_workflow ON event_log(workflow_id)')
            conn.commit()

    def append(self, event: Event) -> bool:
        try:
            with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                step_name = event.details.get("step_name")
                conn.execute("INSERT INTO event_log (workflow_id, event_type, payload, timestamp, step_name) VALUES (?, ?, ?, ?, ?)",
                             (event.workflow_id, event.event_type, event.model_dump_json(), event.timestamp.isoformat(), step_name))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def get_history(self, workflow_id: str) -> List[Event]:
        events = []
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload FROM event_log WHERE workflow_id = ? ORDER BY id ASC", (workflow_id,))
            for row in cursor.fetchall():
                events.append(Event.model_validate_json(row[0]))
        return events
