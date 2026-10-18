"""Single-owner durable scheduler for named, isolated process attempts."""
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import sys
import time
import uuid

from .planning import reject_links
from .processes import run_process
from .schedules import ScheduledTask, utc, utcnow
from .workflows import safe_message, clean_diagnostics

logger = logging.getLogger(__name__)


class SchedulerLock:
    def __init__(self, database):
        self.path = Path(str(Path(database).absolute()) + '.scheduler.lock')
        self.stream = None

    def acquire(self):
        reject_links(self.path)
        stream = self.path.open('a+b')
        try:
            if self.path.stat().st_size == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise RuntimeError('Another scheduler owns this database') from error
        self.stream = stream

    def release(self):
        if self.stream:
            self.stream.close()
            self.stream = None


class TaskScheduler:
    """One active attempt per database; atomic claims and explicit crash review."""
    def __init__(self, db, max_workers=1, *, clock=utcnow, poll_interval=0.25, timer=time.monotonic):
        if max_workers != 1:
            raise ValueError('Exactly one worker is supported to prevent overlapping attempts')
        if db.db_path == ':memory:':
            raise ValueError('Scheduling requires file-backed SQLite')
        reject_links(Path(db.db_path).absolute())
        if Path(db.db_path).stat().st_nlink != 1:
            raise ValueError('Scheduler databases must not have filesystem hard-link aliases')
        if not isinstance(poll_interval, (int, float)) or not .01 <= poll_interval <= 60:
            raise ValueError('poll_interval must be between 0.01 and 60 seconds')
        self.db, self.clock, self.poll_interval = db, clock, poll_interval
        self.timer = timer
        self.lock = SchedulerLock(db.db_path)
        self._running, self._loop_task, self._stopping = False, None, False

    @property
    def tasks(self):
        return {task.id: task for task in self.db.schedules()}

    def _validate_graph(self, tasks):
        visiting, done = set(), set()

        def visit(task_id):
            if task_id in visiting:
                raise ValueError('Scheduled task dependencies contain a cycle')
            if task_id not in tasks:
                raise ValueError('Dependency task was not found')
            if task_id in done:
                return
            visiting.add(task_id)
            for dependency in tasks[task_id].dependencies:
                visit(dependency)
            visiting.remove(task_id)
            done.add(task_id)
        for task_id in tasks:
            visit(task_id)

    def register_task(self, task):
        if not isinstance(task, ScheduledTask):
            raise ValueError('Persist a ScheduledTask with a named operation; Python callables cannot be restored')
        task = ScheduledTask(**task.to_dict()).validate()
        if task.status != 'PENDING' or task.run_count or task.fail_count or task.attempt_count or task.last_success:
            raise ValueError('New schedules must have clean pending state')
        if len(json.dumps(task.to_dict()).encode('utf-8')) > 1024 * 1024:
            raise ValueError('Scheduled task exceeds the 1 MiB limit')
        tasks = self.tasks
        if task.id in tasks:
            raise ValueError('Task ID already exists')
        tasks[task.id] = task
        self._validate_graph(tasks)
        self.db.add_schedule(task)
        return task.id

    def _restore(self):
        self.db.recover_schedules()
        tasks = self.tasks
        for task in tasks.values():
            task.validate()
        self._validate_graph(tasks)
        if any(task.status == 'INTERRUPTED' for task in tasks.values()):
            raise RuntimeError('Interrupted attempts require task recover --acknowledge before dispatch')

    @contextmanager
    def ownership(self):
        self.lock.acquire()
        try:
            yield
        finally:
            self.lock.release()

    def recover_task(self, task_id, *, acknowledged=False):
        if acknowledged is not True:
            raise ValueError('Recovery requires acknowledgement after checking outputs and child processes')
        with self.ownership():
            self.db.recover_schedules()
            self.db.acknowledge_schedule(task_id)

    async def _execute(self, task):
        attempt_id = str(uuid.uuid4())
        if not self.db.claim_schedule(task, utc(self.clock()).isoformat(), attempt_id):
            return False
        report, running = {'status': 'FAILED', 'complete': False}, None
        try:
            def record_pid(pid):
                with self.db._connection() as conn:
                    conn.execute('UPDATE scheduled_attempts SET pid=? WHERE id=?', (pid, attempt_id))
            payload = json.dumps({'task': task.to_dict(), 'database': str(Path(self.db.db_path).absolute())}).encode()
            command = run_process(argv=[sys.executable, '-m', 'taskmaster.scheduled_worker'],
                                  cwd=task.base_dir, payload=payload, on_pid=record_pid,
                                  output_limit=4096 if task.operation == 'subprocess' else None)
            running = asyncio.create_task(command)
            deadline = self.timer() + task.timeout_seconds
            while not running.done():
                if self.db.schedule_state(task.id):
                    raise asyncio.CancelledError
                if self.timer() >= deadline:
                    raise TimeoutError('Scheduled attempt timed out; process tree terminated')
                await asyncio.wait({running}, timeout=min(self.poll_interval, 0.25))
            result = await running
            report = {'status': 'SUCCESS' if result['returncode'] == 0 else 'FAILED',
                      'complete': result['returncode'] == 0, **result}
            if task.operation != 'subprocess':
                if result['output_truncated']:
                    raise ValueError('Workflow report exceeded 4 MiB; inspect workflow history before retrying')
                report['workflow_report'] = json.loads(result['stdout'])
                report['complete'] = report['complete'] and report['workflow_report']['complete']
                report['status'] = 'SUCCESS' if report['complete'] else 'FAILED'
                del report['stdout']
            else:
                report['stdout'], report['stderr'] = safe_message(report['stdout']), safe_message(report['stderr'])
        except asyncio.CancelledError:
            report = {'status': 'CANCELLED', 'complete': False, 'error': 'Attempt cancelled; inspect partial outputs before resuming'}
            task.status = self.db.schedule_state(task.id) or 'PAUSED'
        except Exception as error:
            report = {'status': 'FAILED', 'complete': False, 'error': safe_message(str(error))}
        finally:
            if running and not running.done():
                running.cancel()
                try:
                    await running
                except asyncio.CancelledError:
                    pass
            now = utc(self.clock())
            if report['status'] == 'CANCELLED':
                pass
            elif report['complete']:
                task.last_success = now.isoformat()
                task.next_run = task.following(now)
                task.occurrence_time = task.next_run or task.occurrence_time
                task.attempt_count = 0
                task.status = 'PENDING' if task.next_run else 'COMPLETED'
            else:
                task.fail_count += 1
                error = safe_message(report.get('error') or report.get('stderr') or 'Operation reported failure; inspect attempt report')
                task.error_log = [*task.error_log, f'{now.isoformat()}: {error}'][-10:]
                if task.attempt_count <= task.max_retries:
                    delay = min(task.retry_delay_seconds * 2 ** (task.attempt_count - 1), 300)
                    task.next_run, task.status = (now + timedelta(seconds=delay)).isoformat(), 'PENDING'
                else:
                    task.status, task.next_run = 'FAILED', None
            # A failed final transaction deliberately leaves RUNNING for recovery.
            self.db.finish_schedule(task, attempt_id, clean_diagnostics(report), now.isoformat())
            logger.info('task=%s attempt=%s status=%s', task.id, attempt_id, task.status)
        return True

    async def _dispatch(self):
        tasks = self.tasks
        self._validate_graph(tasks)
        count = 0
        for task in sorted(tasks.values(), key=lambda t: (-t.priority, t.next_run or '', t.id)):
            if self._stopping:
                break
            task.validate()
            if task.status not in ('PENDING', 'BLOCKED') or utc(task.next_run) > utc(self.clock()):
                continue
            current = self.tasks
            blocked = [dep for dep in task.dependencies if not current[dep].last_success
                       or utc(current[dep].last_success) < utc(task.occurrence_time)]
            if blocked:
                task.status, task.blocked_reason = 'BLOCKED', 'Waiting for successful dependency occurrence'
                self.db.block_schedule(task)
                continue
            if await self._execute(task):
                count += 1
        return count

    async def run_due(self):
        if self._running:
            raise RuntimeError('Scheduler is already running')
        with self.ownership():
            self._stopping = False
            self._restore()
            return await self._dispatch()

    async def _loop(self):
        try:
            while self._running:
                await self._dispatch()
                await asyncio.sleep(self.poll_interval)
        finally:
            self._running = False
            self.lock.release()

    async def start(self):
        if self._running:
            return
        self.lock.acquire()
        try:
            self._restore()
            self._running = True
            self._stopping = False
            self._loop_task = asyncio.create_task(self._loop())
        except BaseException:
            self.lock.release()
            raise

    async def stop(self):
        self._stopping = True
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        self.lock.release()

    def close(self):
        if self._running:
            raise RuntimeError('Await scheduler.stop() before closing')
        self.lock.release()

    def pause_task(self, task_id):
        self.db.schedule_request(task_id, 'PAUSED')
        return True

    def cancel_task(self, task_id):
        self.db.schedule_request(task_id, 'CANCELLED')
        return True

    def resume_task(self, task_id):
        self.db.schedule_request(task_id, 'PENDING')
        return True

    def get_task_status(self, task_id):
        task = self.tasks.get(task_id)
        return task.to_dict() if task else None
