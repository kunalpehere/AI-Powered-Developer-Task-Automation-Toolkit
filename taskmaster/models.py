"""
TaskMaster - Advanced Task Scheduler & File Organizer
Configuration and Data Models
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List, Set
import uuid

class TaskStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    PAUSED = auto()

class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

class RecurrenceType(Enum):
    ONCE = "once"
    MINUTELY = "minutely"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"

@dataclass
class Task:
    """Represents a scheduled task with full metadata."""
    name: str
    command: Callable
    schedule_time: datetime
    recurrence: RecurrenceType = RecurrenceType.ONCE
    interval_minutes: Optional[int] = None
    priority: TaskPriority = TaskPriority.NORMAL
    dependencies: List[str] = field(default_factory=list)
    max_retries: int = 3
    timeout_seconds: Optional[int] = None
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Runtime fields (not for serialization)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    fail_count: int = 0
    error_log: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize task to dictionary (excluding callable)."""
        return {
            "id": self.id,
            "name": self.name,
            "schedule_time": self.schedule_time.isoformat(),
            "recurrence": self.recurrence.value,
            "interval_minutes": self.interval_minutes,
            "priority": self.priority.value,
            "dependencies": self.dependencies,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "fail_count": self.fail_count,
            "error_log": self.error_log,
        }

    def calculate_next_run(self) -> Optional[datetime]:
        """Calculate next execution time based on recurrence pattern."""
        if self.recurrence == RecurrenceType.ONCE:
            return None

        base = self.last_run or self.schedule_time

        if self.recurrence == RecurrenceType.MINUTELY:
            interval = self.interval_minutes or 1
            return base + timedelta(minutes=interval)
        elif self.recurrence == RecurrenceType.HOURLY:
            return base + timedelta(hours=1)
        elif self.recurrence == RecurrenceType.DAILY:
            return base + timedelta(days=1)
        elif self.recurrence == RecurrenceType.WEEKLY:
            return base + timedelta(weeks=1)
        elif self.recurrence == RecurrenceType.MONTHLY:
            # Approximate monthly
            return base + timedelta(days=30)
        elif self.recurrence == RecurrenceType.CUSTOM and self.interval_minutes:
            return base + timedelta(minutes=self.interval_minutes)

        return None

@dataclass
class FileRule:
    """Rule for organizing files."""
    name: str
    source_pattern: str  # glob pattern
    destination_template: str  # can use {ext}, {date}, {name}, {type}
    condition: Optional[Callable[[Path], bool]] = None
    action: str = "move"  # move, copy, rename, delete
    enabled: bool = True
    priority: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source_pattern": self.source_pattern,
            "destination_template": self.destination_template,
            "action": self.action,
            "enabled": self.enabled,
            "priority": self.priority,
        }

@dataclass
class FileOperation:
    """Record of a file operation."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: Path = field(default_factory=Path)
    destination: Optional[Path] = None
    operation: str = ""
    status: str = "pending"
    timestamp: datetime = field(default_factory=datetime.now)
    size_bytes: int = 0
    checksum: Optional[str] = None
    error: Optional[str] = None
    filesystem_status: str = "unchanged"
    destination_created: bool = False
    source_removed: bool = False
    history_status: str = "not_requested"
    history_error: Optional[str] = None
    run_id: Optional[str] = None
    step_id: Optional[str] = None


@dataclass(frozen=True)
class SourceState:
    """Identity, metadata, and full-content fingerprint captured during planning."""
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    sha256: str


@dataclass(frozen=True)
class PlannedOperation:
    source: Path
    destination: Optional[Path]
    action: str
    source_state: Optional[SourceState]
    conflict_policy: str = "error"
    validation_error: Optional[str] = None
    skipped_reason: Optional[str] = None


@dataclass(frozen=True)
class OperationPlan:
    source_root: Path
    destination_root: Path
    operations: tuple[PlannedOperation, ...]
    created_at: datetime = field(default_factory=datetime.now)
    includes: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    all_files: bool = False

    @property
    def requires_confirmation(self) -> bool:
        return any(op.action in {"move", "rename", "delete"}
                   and not op.validation_error and not op.skipped_reason
                   for op in self.operations)
