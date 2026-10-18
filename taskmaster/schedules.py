"""Serializable UTC schedules; no persisted Python callables."""
import calendar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

from .config import validate_workflow
from .operations import normalize_parameters


def utcnow():
    return datetime.now(timezone.utc)


def utc(value):
    date = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(date, datetime) or date.tzinfo is None or date.utcoffset() is None:
        raise ValueError('Schedule times require an explicit UTC offset')
    return date.astimezone(timezone.utc)


@dataclass
class ScheduledTask:
    name: str
    operation: str
    parameters: dict
    schedule_time: str
    base_dir: str
    recurrence: str = 'once'
    interval_minutes: int = 1
    priority: int = 2
    dependencies: list[str] = field(default_factory=list)
    max_retries: int = 0
    retry_delay_seconds: int = 1
    timeout_seconds: int = 300
    retry_safe: bool = False
    config_path: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = 'PENDING'
    next_run: str | None = None
    occurrence_time: str | None = None
    run_count: int = 0
    fail_count: int = 0
    attempt_count: int = 0
    last_success: str | None = None
    error_log: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    def to_dict(self):
        return json.loads(json.dumps(asdict(self)))

    def validate(self):
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 256:
            raise ValueError('Task name must contain 1–256 characters')
        if not isinstance(self.id, str) or not self.id or len(self.id) > 64:
            raise ValueError('Invalid task ID')
        self.schedule_time = utc(self.schedule_time).isoformat()
        self.base_dir = str(Path(self.base_dir).expanduser().absolute())
        if self.config_path is not None:
            self.config_path = str(Path(self.config_path).expanduser().absolute())
        for name, low, high in [('interval_minutes', 1, 525600), ('priority', 1, 4),
                                ('max_retries', 0, 10), ('retry_delay_seconds', 1, 300),
                                ('timeout_seconds', 1, 86400)]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} must be an integer from {low} to {high}')
        if self.recurrence not in ('once', 'minutely', 'hourly', 'daily', 'weekly', 'monthly', 'custom'):
            raise ValueError('Unsupported recurrence')
        if (type(self.dependencies) is not list or any(not isinstance(d, str) or not d for d in self.dependencies)
                or len(set(self.dependencies)) != len(self.dependencies) or self.id in self.dependencies):
            raise ValueError('Dependencies must be distinct task IDs without self references')
        if type(self.retry_safe) is not bool:
            raise ValueError('retry_safe must be a boolean')
        mutating = False
        if self.operation == 'workflow':
            if type(self.parameters) is not dict or set(self.parameters) != {'workflow', 'apply', 'confirmed'}:
                raise ValueError('Workflow task requires workflow, apply and confirmed parameters')
            workflow = validate_workflow(self.parameters['workflow'])
            if type(self.parameters['apply']) is not bool or type(self.parameters['confirmed']) is not bool:
                raise ValueError('Workflow apply/confirmed flags must be booleans')
            mutating = self.parameters['apply'] and any(s.operation == 'organize' for s in workflow.steps)
            if mutating and not self.parameters['confirmed']:
                raise ValueError('Scheduled organization requires persistent explicit approval')
            self.parameters = {**self.parameters, 'workflow': workflow.to_dict()}
        elif self.operation == 'subprocess':
            if (type(self.parameters) is not dict or set(self.parameters) != {'command'}
                    or not isinstance(self.parameters['command'], str) or not self.parameters['command'].strip()
                    or '\0' in self.parameters['command']):
                raise ValueError('Subprocess task requires a nonempty shell command')
            if self.max_retries and not self.retry_safe:
                raise ValueError('Subprocess retries require explicit retry_safe acknowledgement')
        elif self.operation in ('inspect', 'duplicates'):
            self.parameters = normalize_parameters(self.operation, self.parameters)
        else:
            raise ValueError('Scheduled operations are inspect, duplicates, workflow or subprocess')
        if mutating and self.max_retries:
            raise ValueError('Automatic retries of file-changing workflows are disabled')
        self.next_run = utc(self.next_run or self.schedule_time).isoformat()
        self.occurrence_time = utc(self.occurrence_time or self.schedule_time).isoformat()
        if self.last_success is not None:
            self.last_success = utc(self.last_success).isoformat()
        return self

    def following(self, after):
        """Fixed UTC cadence, skip missed ticks; monthly retains original day anchor."""
        if self.recurrence == 'once':
            return None
        after = utc(after)
        anchor = utc(self.schedule_time)
        if self.recurrence == 'monthly':
            months = max(1, (after.year - anchor.year) * 12 + after.month - anchor.month)
            while True:
                year, month = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
                month += 1
                candidate = anchor.replace(year=year, month=month,
                                           day=min(anchor.day, calendar.monthrange(year, month)[1]))
                if candidate > after:
                    return candidate.isoformat()
                months += 1
        seconds = {'minutely': self.interval_minutes * 60, 'custom': self.interval_minutes * 60,
                   'hourly': 3600, 'daily': 86400, 'weekly': 604800}[self.recurrence]
        ticks = max(1, int((after - anchor).total_seconds() // seconds) + 1)
        return (anchor + timedelta(seconds=ticks * seconds)).isoformat()
