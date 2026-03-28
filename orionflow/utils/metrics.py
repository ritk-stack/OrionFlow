import sqlite3
import datetime as dt
from typing import Dict, Any

class SqliteMetricsStore:
    def __init__(self, db_path="orionflow.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute('''CREATE TABLE IF NOT EXISTS metrics
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                             task_id TEXT UNIQUE,
                             task_type TEXT,
                             queue_wait_time_ms REAL,
                             execution_time_ms REAL,
                             retries INTEGER,
                             status TEXT,
                             timestamp TEXT)''')
            conn.commit()

    def record(self, task_id: str, task_type: str, wait_time: float, exec_time: float, retries: int, status: str):
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                conn.execute(
                    "INSERT INTO metrics (task_id, task_type, queue_wait_time_ms, execution_time_ms, retries, status, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (task_id, task_type, wait_time, exec_time, retries, status, now)
                )
                conn.commit()
        except sqlite3.IntegrityError:
            pass

    def get_summary(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*),
                    AVG(queue_wait_time_ms),
                    AVG(execution_time_ms),
                    SUM(retries),
                    SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END)
                FROM metrics
            """)
            row = cursor.fetchone()
            total = row[0] or 0
            if total == 0:
                return {"total_tasks": 0}
            
            return {
                "total_tasks": total,
                "avg_queue_wait_time_ms": round(row[1], 2) if row[1] else 0.0,
                "avg_execution_time_ms": round(row[2], 2) if row[2] else 0.0,
                "total_retries": int(row[3]) if row[3] else 0,
                "success_rate": round((row[4] / total) * 100, 2) if row[4] else 0.0
            }
