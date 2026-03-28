import sqlite3
import time
import datetime as dt
from typing import Optional, List, Dict
from datetime import datetime, timezone
from orionflow.core.models import Task

class SqliteTaskQueue:
    def __init__(self, db_path="orionflow.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute('''CREATE TABLE IF NOT EXISTS queue
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT UNIQUE, payload TEXT, status TEXT, start_time TEXT, end_time TEXT, workflow_id TEXT, step_name TEXT, retries INTEGER DEFAULT 0, next_retry_at TEXT, priority INTEGER DEFAULT 0)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS workers
                            (worker_id TEXT PRIMARY KEY, status TEXT, current_task_id TEXT, last_heartbeat TEXT)''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_queue_polling ON queue(status, priority, next_retry_at)')
            conn.commit()

    def heartbeat(self, worker_id: str, status: str, task_id: Optional[str] = None):
        now = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                conn.execute('''INSERT OR REPLACE INTO workers (worker_id, status, current_task_id, last_heartbeat)
                                VALUES (?, ?, ?, ?)''', (worker_id, status, task_id, now))
                conn.commit()
        except: pass

    def get_workers(self) -> List[Dict]:
        now = datetime.now(timezone.utc)
        workers = []
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT worker_id, status, current_task_id, last_heartbeat FROM workers")
            for row in cursor.fetchall():
                last = datetime.fromisoformat(row[3])
                status = "OFFLINE" if (now - last).total_seconds() > 10 else row[1]
                workers.append({"worker_id": row[0], "status": status, "current_task_id": row[2], "last_heartbeat": row[3]})
        return workers

    def enqueue(self, task: Task) -> bool:
        try:
            with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                conn.execute("INSERT INTO queue (task_id, payload, status, workflow_id, step_name, retries, priority) VALUES (?, ?, 'PENDING', ?, ?, ?, ?)",
                             (task.task_id, task.model_dump_json(), task.workflow_id, task.step_name, task.retries, task.priority))
                conn.commit()
                return True
        except sqlite3.IntegrityError: return False

    def dequeue(self, timeout: int = 0) -> Optional[Task]:
        start = time.time()
        while True:
            try:
                with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("BEGIN IMMEDIATE")
                    now_str = datetime.now(timezone.utc).isoformat()
                    
                    cursor.execute("SELECT id, payload FROM queue WHERE status = 'PENDING' AND (next_retry_at IS NULL OR next_retry_at <= ?) ORDER BY priority DESC, id ASC LIMIT 1", (now_str,))
                    row = cursor.fetchone()
                    if row:
                        cursor.execute("UPDATE queue SET status = 'RUNNING', start_time = ? WHERE id = ?", (now_str, row[0]))
                        conn.commit()
                        task = Task.model_validate_json(row[1])
                        task.status, task.start_time = 'RUNNING', datetime.fromisoformat(now_str)
                        return task
                    conn.rollback()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower():
                    time.sleep(0.01)
                    continue
                raise
            if timeout == 0 or time.time() - start < timeout: time.sleep(0.05)
            else: return None
                
    def complete(self, task_id: str, result: str, status: str = "SUCCESS"):
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload FROM queue WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                t = Task.model_validate_json(row[0])
                t.result, t.status, t.end_time = result, status, datetime.fromisoformat(now_str)
                cursor.execute("UPDATE queue SET status = ?, end_time = ?, payload = ? WHERE task_id = ?", (status, now_str, t.model_dump_json(), task_id))
            conn.commit()

    def schedule_retry(self, task_id: str, retries: int, backoff_seconds: int):
        now = datetime.now(timezone.utc)
        next_retry = (now + dt.timedelta(seconds=backoff_seconds)).isoformat()
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload FROM queue WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                t = Task.model_validate_json(row[0])
                t.retries, t.next_retry_at = retries, datetime.fromisoformat(next_retry)
                cursor.execute("UPDATE queue SET status = 'PENDING', start_time = NULL, retries = ?, next_retry_at = ?, payload = ? WHERE task_id = ?", (retries, next_retry, t.model_dump_json(), task_id))
            conn.commit()

    def recover_stuck_tasks(self, timeout_seconds: int = 300) -> int:
        now = datetime.now(timezone.utc)
        recovered_count = 0
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("SELECT id, task_id, start_time FROM queue WHERE status = 'RUNNING'")
            for row in cursor.fetchall():
                if row[2]:
                    try:
                        if (now - datetime.fromisoformat(row[2])).total_seconds() > timeout_seconds:
                            cursor.execute("UPDATE queue SET status = 'PENDING', start_time = NULL WHERE id = ?", (row[0],))
                            recovered_count += 1
                    except Exception: pass
            conn.commit()
        return recovered_count
