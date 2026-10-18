"""
TaskMaster - Database Layer
Handles persistence for tasks, file operations, and configuration.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from .models import Task, FileOperation, TaskStatus

class Database:
    """Versioned SQLite persistence; one connection per operation."""

    SCHEMA_VERSION = 2

    def __init__(self, db_path: str = "taskmaster.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > self.SCHEMA_VERSION:
                raise ValueError("Database schema is newer than this application supports")
            # Tasks table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    schedule_time TEXT NOT NULL,
                    recurrence TEXT DEFAULT 'once',
                    interval_minutes INTEGER,
                    priority INTEGER DEFAULT 2,
                    dependencies TEXT DEFAULT '[]',
                    max_retries INTEGER DEFAULT 3,
                    timeout_seconds INTEGER,
                    tags TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_run TEXT,
                    next_run TEXT,
                    run_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    error_log TEXT DEFAULT '[]'
                )
            """)

            # File operations table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_operations (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    destination TEXT,
                    operation TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    size_bytes INTEGER DEFAULT 0,
                    checksum TEXT,
                    error TEXT
                )
            """)

            # File index table (for duplicate detection)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    checksum TEXT NOT NULL,
                    size_bytes INTEGER,
                    modified_time TEXT,
                    indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON tasks(next_run)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_checksum ON file_index(checksum)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_ops_timestamp ON file_operations(timestamp)")
            # Additive compatibility for existing Phase 1 history databases.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(file_operations)")}
            for name, definition in {
                "filesystem_status": "TEXT DEFAULT 'unknown'",
                "destination_created": "INTEGER DEFAULT 0",
                "source_removed": "INTEGER DEFAULT 0",
                "history_status": "TEXT DEFAULT 'unknown'",
                "history_error": "TEXT",
                "run_id": "TEXT",
                "step_id": "TEXT",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE file_operations ADD COLUMN {name} {definition}")
            conn.execute("""CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, workflow_name TEXT NOT NULL, mode TEXT NOT NULL,
                on_failure TEXT NOT NULL, config_sha256 TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                report_json TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS run_steps (
                run_id TEXT NOT NULL, step_id TEXT NOT NULL, position INTEGER NOT NULL,
                operation TEXT NOT NULL, status TEXT NOT NULL, report_json TEXT NOT NULL,
                PRIMARY KEY (run_id, step_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_ops_run ON file_operations(run_id, step_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, next_run TEXT,
                requested_state TEXT, document TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS scheduled_attempts (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, occurrence_time TEXT NOT NULL,
                attempt_number INTEGER NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                status TEXT NOT NULL, pid INTEGER, report_json TEXT,
                UNIQUE(task_id, occurrence_time, attempt_number))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_due ON scheduled_tasks(status, next_run)")
            conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    # Task operations
    def save_task(self, task: Task) -> None:
        """Save or update a task."""
        with self._connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO tasks (
                    id, name, schedule_time, recurrence, interval_minutes,
                    priority, dependencies, max_retries, timeout_seconds,
                    tags, metadata, status, created_at, last_run, next_run,
                    run_count, fail_count, error_log
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.id, task.name, task.schedule_time.isoformat(),
                task.recurrence.value, task.interval_minutes, task.priority.value,
                json.dumps(task.dependencies), task.max_retries, task.timeout_seconds,
                json.dumps(list(task.tags)), json.dumps(task.metadata),
                task.status.name, task.created_at.isoformat(),
                task.last_run.isoformat() if task.last_run else None,
                task.next_run.isoformat() if task.next_run else None,
                task.run_count, task.fail_count, json.dumps(task.error_log)
            ))

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a task by ID."""
        with self._connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Get all pending tasks ordered by priority and schedule time."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM tasks 
                WHERE status IN ('PENDING', 'PAUSED')
                ORDER BY priority DESC, schedule_time ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_due_tasks(self, before: datetime) -> List[Dict[str, Any]]:
        """Get tasks that are due to run."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM tasks 
                WHERE status = 'PENDING' 
                AND next_run <= ?
                ORDER BY priority DESC, schedule_time ASC
            """, (before.isoformat(),))
            return [dict(row) for row in cursor.fetchall()]

    def update_task_status(self, task_id: str, status: TaskStatus, 
                          error: Optional[str] = None) -> None:
        """Update task status and optionally append error."""
        with self._connection() as conn:
            if error:
                # Append error to log
                cursor = conn.execute("SELECT error_log FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                errors = json.loads(row["error_log"]) if row else []
                errors.append(f"{datetime.now().isoformat()}: {error}")
                conn.execute(
                    "UPDATE tasks SET status = ?, error_log = ? WHERE id = ?",
                    (status.name, json.dumps(errors[-10:]), task_id)  # Keep last 10
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status = ? WHERE id = ?",
                    (status.name, task_id)
                )

    def delete_task(self, task_id: str) -> None:
        """Delete a task."""
        with self._connection() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks."""
        with self._connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    # File operations
    def schedules(self):
        from .schedules import ScheduledTask
        with self._connection() as conn:
            return [ScheduledTask(**json.loads(row['document'])) for row in
                    conn.execute('SELECT document FROM scheduled_tasks ORDER BY id')]

    def add_schedule(self, task):
        with self._connection() as conn:
            conn.execute('INSERT INTO scheduled_tasks(id,status,next_run,document) VALUES (?,?,?,?)',
                         (task.id, task.status, task.next_run, json.dumps(task.to_dict())))

    def schedule_request(self, task_id, state):
        if state not in ('PAUSED', 'CANCELLED', 'PENDING'):
            raise ValueError('Invalid requested state')
        with self._connection() as conn:
            row = conn.execute('SELECT document,status FROM scheduled_tasks WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise ValueError('Task was not found')
            if row['status'] == 'INTERRUPTED':
                raise ValueError('Interrupted tasks require explicit recovery acknowledgement')
            document = json.loads(row['document'])
            if row['status'] == 'RUNNING':
                if state == 'PENDING':
                    raise ValueError('Cannot resume a running task')
                conn.execute('UPDATE scheduled_tasks SET requested_state=? WHERE id=?', (state, task_id))
            else:
                if state == 'PENDING' and row['status'] != 'PAUSED':
                    raise ValueError('Only paused tasks can be resumed')
                document['status'] = state
                if state == 'PENDING':
                    document['next_run'] = document.get('next_run') or document['occurrence_time']
                conn.execute('UPDATE scheduled_tasks SET status=?,next_run=?,requested_state=NULL,document=? WHERE id=?',
                             (state, document['next_run'], json.dumps(document), task_id))

    def claim_schedule(self, task, now, attempt_id):
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT status,next_run,requested_state FROM scheduled_tasks WHERE id=?', (task.id,)).fetchone()
            if not row or row['status'] not in ('PENDING', 'BLOCKED') or row['next_run'] > now or row['requested_state']:
                return False
            task.status, task.blocked_reason = 'RUNNING', None
            task.run_count += 1
            task.attempt_count += 1
            conn.execute('UPDATE scheduled_tasks SET status=?,document=? WHERE id=?',
                         (task.status, json.dumps(task.to_dict()), task.id))
            conn.execute('INSERT INTO scheduled_attempts(id,task_id,occurrence_time,attempt_number,started_at,status) VALUES (?,?,?,?,?,?)',
                         (attempt_id, task.id, task.occurrence_time, task.attempt_count, now, 'RUNNING'))
            return True

    def schedule_state(self, task_id):
        with self._connection() as conn:
            row = conn.execute('SELECT requested_state FROM scheduled_tasks WHERE id=?', (task_id,)).fetchone()
            return row['requested_state'] if row else 'CANCELLED'

    def finish_schedule(self, task, attempt_id, report, now):
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT requested_state FROM scheduled_tasks WHERE id=?', (task.id,)).fetchone()
            if row and row['requested_state']:
                task.status = row['requested_state']
            conn.execute('UPDATE scheduled_tasks SET status=?,next_run=?,requested_state=NULL,document=? WHERE id=?',
                         (task.status, task.next_run, json.dumps(task.to_dict()), task.id))
            conn.execute('UPDATE scheduled_attempts SET status=?,finished_at=?,report_json=? WHERE id=?',
                         (report['status'], now, json.dumps(report), attempt_id))

    def block_schedule(self, task):
        with self._connection() as conn:
            # A concurrent pause/cancel wins over this diagnostic update.
            conn.execute("UPDATE scheduled_tasks SET status='BLOCKED',document=? WHERE id=? AND status IN ('PENDING','BLOCKED')",
                         (json.dumps(task.to_dict()), task.id))

    def recover_schedules(self):
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for row in conn.execute("SELECT id,document FROM scheduled_tasks WHERE status='RUNNING'").fetchall():
                document = json.loads(row['document'])
                document['status'] = 'INTERRUPTED'
                document['blocked_reason'] = 'Previous owner exited during an attempt; inspect outputs and child processes before recovery'
                conn.execute("UPDATE scheduled_tasks SET status='INTERRUPTED',document=? WHERE id=?", (json.dumps(document), row['id']))
            conn.execute("UPDATE scheduled_attempts SET status='INTERRUPTED' WHERE status='RUNNING'")

    def acknowledge_schedule(self, task_id):
        with self._connection() as conn:
            row = conn.execute("SELECT document FROM scheduled_tasks WHERE id=? AND status='INTERRUPTED'", (task_id,)).fetchone()
            if not row:
                raise ValueError('Task is not interrupted')
            document = json.loads(row['document'])
            document['status'], document['blocked_reason'] = 'PAUSED', None
            conn.execute("UPDATE scheduled_tasks SET status='PAUSED',requested_state=NULL,document=? WHERE id=?", (json.dumps(document), task_id))

    def schedule_attempts(self, task_id=None):
        with self._connection() as conn:
            rows = conn.execute('SELECT * FROM scheduled_attempts WHERE (? IS NULL OR task_id=?) ORDER BY started_at,task_id,occurrence_time,attempt_number,id',
                                (task_id, task_id)).fetchall()
            return [{**dict(row), 'report': json.loads(row['report_json']) if row['report_json'] else None} for row in rows]

    def log_file_operation(self, op: FileOperation) -> None:
        """Log a file operation."""
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO file_operations 
                (id, source, destination, operation, status, timestamp, size_bytes, checksum, error,
                 filesystem_status, destination_created, source_removed, history_status, history_error, run_id, step_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                op.id, str(op.source), str(op.destination) if op.destination else None,
                op.operation, op.status, op.timestamp.isoformat(),
                op.size_bytes, op.checksum, op.error, op.filesystem_status,
                op.destination_created, op.source_removed, op.history_status, op.history_error, op.run_id, op.step_id
            ))

    def start_run(self, report: dict) -> None:
        with self._connection() as conn:
            conn.execute("""INSERT INTO runs (run_id, workflow_name, mode, on_failure,
                config_sha256, started_at, status, report_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (report["run_id"], report["workflow"]["name"], report["mode"], report["on_failure"],
                 report["workflow"]["config_sha256"], report["started_at"], "running", json.dumps(report)))

    def save_run_step(self, run_id: str, position: int, step: dict) -> None:
        with self._connection() as conn:
            conn.execute("""INSERT OR REPLACE INTO run_steps
                (run_id, step_id, position, operation, status, report_json) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, step["id"], position, step["operation"], step["status"], json.dumps(step)))

    def finish_run(self, report: dict) -> None:
        with self._connection() as conn:
            cursor = conn.execute("UPDATE runs SET finished_at=?, status=?, report_json=? WHERE run_id=?",
                (report["finished_at"], report["status"], json.dumps(report), report["run_id"]))
            if cursor.rowcount != 1:
                raise ValueError("Run journal entry was not found")

    @staticmethod
    def read_runs(db_path: str, *, run_id: str | None = None, limit: int = 20):
        """Read history without initialization, schema changes, or file creation."""
        if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
            raise ValueError("Run ID must be a nonempty string")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("History limit must be an integer from 1 to 1000")
        path = Path(db_path).absolute()
        if not path.exists():
            return None if run_id else []
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] > Database.SCHEMA_VERSION:
                raise ValueError("Database schema is newer than this application supports")
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                return None if run_id else []
            if run_id is None:
                return [dict(row) for row in conn.execute("""SELECT run_id, workflow_name, mode,
                    on_failure, started_at, finished_at, status FROM runs
                    ORDER BY started_at DESC, run_id DESC LIMIT ?""", (limit,))]
            row = conn.execute("SELECT report_json, status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            report = json.loads(row["report_json"])
            if row["status"] == "running":
                saved = {entry["step_id"]: json.loads(entry["report_json"]) for entry in conn.execute(
                    "SELECT step_id, report_json FROM run_steps WHERE run_id=? ORDER BY position", (run_id,))}
                report["steps"] = [saved.get(step["id"], step) for step in report["steps"]]
                report["summary"] = {
                    "successful_steps": sum(step["status"] == "success" for step in report["steps"]),
                    "failed_steps": sum(step["status"] == "failed" for step in report["steps"]),
                    "running_steps": sum(step["status"] == "running" for step in report["steps"]),
                    "not_run_steps": sum(step["status"] == "not_run" for step in report["steps"]),
                    "history_failures": len(report["history"]["errors"]),
                }
            return report
        finally:
            conn.close()

    def get_file_operations(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent file operations."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM file_operations 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # File index for duplicate detection
    def index_file(self, path: Path, checksum: str, size: int) -> None:
        """Add file to index."""
        with self._connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO file_index 
                (path, checksum, size_bytes, modified_time)
                VALUES (?, ?, ?, ?)
            """, (str(path), checksum, size, datetime.now().isoformat()))

    def find_duplicates(self) -> List[Dict[str, Any]]:
        """Find files with duplicate checksums."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT checksum, path, size_bytes, COUNT(*) as count
                FROM file_index
                GROUP BY checksum
                HAVING count > 1
                ORDER BY size_bytes DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        with self._connection() as conn:
            stats = {}
            cursor = conn.execute("SELECT COUNT(*) as count FROM tasks")
            stats["total_tasks"] = cursor.fetchone()["count"]

            cursor = conn.execute("SELECT COUNT(*) as count FROM tasks WHERE status = 'PENDING'")
            stats["pending_tasks"] = cursor.fetchone()["count"]

            cursor = conn.execute("SELECT COUNT(*) as count FROM tasks WHERE status = 'COMPLETED'")
            stats["completed_tasks"] = cursor.fetchone()["count"]

            cursor = conn.execute("SELECT COUNT(*) as count FROM tasks WHERE status = 'FAILED'")
            stats["failed_tasks"] = cursor.fetchone()["count"]

            cursor = conn.execute("SELECT COUNT(*) as count FROM file_operations")
            stats["file_operations"] = cursor.fetchone()["count"]

            cursor = conn.execute("SELECT COUNT(*) as count FROM file_index")
            stats["indexed_files"] = cursor.fetchone()["count"]

            return stats
