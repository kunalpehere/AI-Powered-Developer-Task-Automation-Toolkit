import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys
import uuid

import pytest

from taskmaster.cli import main
from taskmaster.database import Database
from taskmaster.schedules import ScheduledTask, utc
from taskmaster.scheduler import TaskScheduler

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a.log').write_bytes(b'same')
    (source / 'b.log').write_bytes(b'same')
    db = Database(str(tmp_path / 'history.sqlite'))
    return source, db


def job(source, **options):
    return ScheduledTask('review', 'inspect', {'source': str(source)}, NOW.isoformat(), str(source.parent), **options)


def shell(source, code, **options):
    script = source.parent / (str(uuid.uuid4()) + '.py')
    script.write_text(code, encoding='utf-8')
    command = subprocess.list2cmdline([sys.executable, str(script)]) if os.name == 'nt' else __import__('shlex').join([sys.executable, str(script)])
    return ScheduledTask('command', 'subprocess', {'command': command}, NOW.isoformat(), str(source.parent), **options)


def run(scheduler):
    return asyncio.run(scheduler.run_due())


def test_future_next_run_restores_and_does_not_repeat(setup):
    source, db = setup
    clock = [NOW - timedelta(seconds=1)]
    scheduler = TaskScheduler(db, clock=lambda: clock[0])
    task = job(source)
    scheduler.register_task(task)
    assert run(scheduler) == 0
    clock[0] = NOW
    restored = TaskScheduler(Database(db.db_path), clock=lambda: clock[0])
    assert run(restored) == 1
    assert run(restored) == 0
    saved = restored.get_task_status(task.id)
    assert saved['status'] == 'COMPLETED' and saved['run_count'] == 1
    attempt = db.schedule_attempts()[0]
    assert attempt['report']['workflow_report']['steps'][0]['report']['summary']['file_count'] == 2


@pytest.mark.parametrize('recurrence,after,expected', [
    ('minutely', '2026-01-31T12:05:33+00:00', '2026-01-31T12:06:00+00:00'),
    ('hourly', '2026-01-31T13:00:00+00:00', '2026-01-31T14:00:00+00:00'),
    ('daily', '2026-02-02T12:00:00+00:00', '2026-02-03T12:00:00+00:00'),
    ('weekly', '2026-02-07T12:00:00+00:00', '2026-02-14T12:00:00+00:00'),
    ('monthly', '2026-01-31T12:00:00+00:00', '2026-02-28T12:00:00+00:00'),
    ('monthly', '2026-02-28T12:00:00+00:00', '2026-03-31T12:00:00+00:00'),
])
def test_cadence_boundaries_and_month_end(setup, recurrence, after, expected):
    source, _ = setup
    task = job(source, recurrence=recurrence)
    task.schedule_time = '2026-01-31T12:00:00+00:00'
    assert task.validate().following(utc(after)) == expected


def test_timezone_and_bad_schedule_fields(setup):
    source, _ = setup
    task = job(source)
    task.schedule_time = '2026-10-15T17:30:00+05:30'
    assert task.validate().schedule_time == NOW.isoformat()
    with pytest.raises(ValueError, match='offset'):
        utc(datetime(2026, 1, 1))
    for options in ({'max_retries': -1}, {'interval_minutes': 0}, {'timeout_seconds': True}, {'priority': 9}):
        with pytest.raises(ValueError):
            job(source, **options).validate()


def test_retry_budget_backoff_and_logs_survive_restart(setup):
    source, db = setup
    clock = [NOW]
    task = job(source / 'missing', max_retries=2)
    scheduler = TaskScheduler(db, clock=lambda: clock[0])
    scheduler.register_task(task)
    for number, seconds in ((1, 1), (2, 2)):
        assert run(scheduler) == 1
        saved = scheduler.tasks[task.id]
        assert saved.run_count == number and saved.fail_count == number
        assert utc(saved.next_run) == clock[0] + timedelta(seconds=seconds)
        assert run(scheduler) == 0
        clock[0] = utc(saved.next_run)
        scheduler = TaskScheduler(Database(db.db_path), clock=lambda: clock[0])
    assert run(scheduler) == 1
    saved = scheduler.tasks[task.id]
    assert saved.status == 'FAILED' and saved.run_count == 3 and len(saved.error_log) == 3
    assert len(db.schedule_attempts()) == 3


def test_success_resets_occurrence_retry_budget_and_skips_missed_ticks(setup):
    source, db = setup
    clock = [NOW + timedelta(minutes=7, seconds=3)]
    scheduler = TaskScheduler(db, clock=lambda: clock[0])
    review = source / 'generated'
    task = job(review, recurrence='minutely', max_retries=1)
    scheduler.register_task(task)
    assert run(scheduler) == 1
    assert scheduler.tasks[task.id].attempt_count == 1
    clock[0] = utc(scheduler.tasks[task.id].next_run)
    review.mkdir()
    assert run(scheduler) == 1
    saved = scheduler.tasks[task.id]
    assert saved.attempt_count == 0 and saved.fail_count == 1
    assert utc(saved.next_run) == NOW + timedelta(minutes=8)
    assert run(scheduler) == 0
    clock[0] = utc(saved.next_run)
    assert run(scheduler) == 1
    assert len({a['occurrence_time'] for a in db.schedule_attempts()}) == 2


def test_dependencies_block_without_consuming_attempts_and_then_unblock(setup):
    source, db = setup
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    parent = job(source, priority=1)
    child = job(source, dependencies=[parent.id], priority=4)
    scheduler.register_task(parent)
    scheduler.register_task(child)
    assert run(scheduler) == 1
    assert scheduler.tasks[child.id].status == 'BLOCKED' and scheduler.tasks[child.id].run_count == 0
    assert run(scheduler) == 1
    assert scheduler.tasks[child.id].status == 'COMPLETED'


def test_cycles_missing_dependencies_and_callables_rejected(setup):
    source, db = setup
    scheduler = TaskScheduler(db)
    task = job(source, dependencies=['absent'])
    with pytest.raises(ValueError, match='not found'):
        scheduler.register_task(task)
    task.dependencies = [task.id]
    with pytest.raises(ValueError, match='self'):
        scheduler.register_task(task)
    with pytest.raises(ValueError, match='callables'):
        scheduler.register_task(lambda: None)
    first, second = job(source), job(source)
    first.dependencies, second.dependencies = [second.id], [first.id]
    db.add_schedule(first.validate())
    db.add_schedule(second.validate())
    with pytest.raises(ValueError, match='cycle'):
        run(scheduler)
    assert not db.schedule_attempts()


def test_single_owner_and_atomic_claim_prevent_duplicates(setup):
    source, db = setup
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    task = job(source)
    scheduler.register_task(task)
    other = TaskScheduler(Database(db.db_path), clock=lambda: NOW)
    with scheduler.ownership():
        with pytest.raises(RuntimeError, match='owns'):
            run(other)
    assert db.claim_schedule(task.validate(), NOW.isoformat(), 'first')
    assert not db.claim_schedule(job(source), NOW.isoformat(), 'second')
    assert not db.claim_schedule(task, NOW.isoformat(), 'second')
    with pytest.raises(RuntimeError, match='Interrupted'):
        run(other)
    assert len(db.schedule_attempts()) == 1


def test_crash_requires_review_then_explicit_resume(setup):
    source, db = setup
    task = job(source)
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    scheduler.register_task(task)
    assert db.claim_schedule(task.validate(), NOW.isoformat(), 'crashed')
    with pytest.raises(RuntimeError, match='Interrupted'):
        run(scheduler)
    assert scheduler.tasks[task.id].status == 'INTERRUPTED'
    with pytest.raises(ValueError, match='acknowledgement'):
        scheduler.recover_task(task.id)
    scheduler.recover_task(task.id, acknowledged=True)
    assert run(scheduler) == 0
    scheduler.resume_task(task.id)
    assert run(scheduler) == 1
    assert [a['status'] for a in db.schedule_attempts()] == ['INTERRUPTED', 'SUCCESS']


def test_pause_cancel_resume_pending_and_restart(setup):
    source, db = setup
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    task = job(source)
    scheduler.register_task(task)
    scheduler.pause_task(task.id)
    assert run(scheduler) == 0
    scheduler = TaskScheduler(Database(db.db_path), clock=lambda: NOW)
    scheduler.resume_task(task.id)
    scheduler.cancel_task(task.id)
    assert run(scheduler) == 0
    assert scheduler.tasks[task.id].status == 'CANCELLED'


def test_timeout_terminates_child_tree_before_delayed_side_effect(setup):
    source, db = setup
    child = source.parent / 'child.py'
    marker = source.parent / 'late.txt'
    started = source.parent / 'child-started'
    child.write_text('import time\nfrom pathlib import Path\nPath(' + repr(str(started)) + ').write_text("ready")\ntime.sleep(4)\nPath(' + repr(str(marker)) + ').write_text("late")\n')
    code = 'import subprocess,sys,time\nsubprocess.Popen([sys.executable,' + repr(str(child)) + '])\ntime.sleep(20)\n'
    scheduler = TaskScheduler(db, clock=lambda: NOW, poll_interval=0.02,
                              timer=lambda: 10 if started.exists() else 0)
    task = shell(source, code, timeout_seconds=2)
    scheduler.register_task(task)
    async def scenario():
        await asyncio.wait_for(scheduler.run_due(), timeout=30)
        await asyncio.sleep(4.2)
    asyncio.run(scenario())
    assert scheduler.tasks[task.id].status == 'FAILED'
    assert 'timed out' in db.schedule_attempts()[0]['report']['error']
    assert started.exists(), 'Fixture must actually launch a descendant before timeout'
    assert not marker.exists()


def test_active_cancel_and_shutdown_pause_without_dispatching_next_job(setup):
    source, db = setup
    scheduler = TaskScheduler(db, clock=lambda: NOW, poll_interval=0.02)
    first = shell(source, 'import time\ntime.sleep(20)\n', priority=4)
    second = job(source)
    scheduler.register_task(first)
    scheduler.register_task(second)
    async def scenario():
        await scheduler.start()
        for _ in range(300):
            if db.schedule_attempts() and db.schedule_attempts()[0]['pid']:
                break
            await asyncio.sleep(.01)
        await scheduler.stop()
    asyncio.run(scenario())
    assert scheduler.tasks[first.id].status == 'PAUSED'
    assert scheduler.tasks[second.id].run_count == 0
    assert db.schedule_attempts()[0]['status'] == 'CANCELLED'
    assert run(TaskScheduler(db, clock=lambda: NOW)) == 1


def test_subprocess_output_is_bounded_and_credentials_redacted(setup):
    source, db = setup
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    task = shell(source, 'print("x"*10000)\nprint("token=never-echo-this")\n')
    scheduler.register_task(task)
    run(scheduler)
    report = db.schedule_attempts()[0]['report']
    assert report['output_truncated'] and len(report['stdout']) <= 4096
    assert 'never-echo-this' not in json.dumps(report)


def test_mutating_workflow_approval_and_retry_guard(setup):
    source, db = setup
    workflow = {'version': 1, 'name': 'copy', 'steps': [{'id': 'copy', 'operation': 'organize',
        'parameters': {'source': str(source), 'destination': str(source.parent / 'output'),
                       'includes': ['*.log'], 'action': 'copy'}}]}
    task = ScheduledTask('copy', 'workflow', {'workflow': workflow, 'apply': True, 'confirmed': False}, NOW.isoformat(), str(source.parent))
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    with pytest.raises(ValueError, match='approval'):
        scheduler.register_task(task)
    task.parameters['confirmed'], task.max_retries = True, 1
    with pytest.raises(ValueError, match='retries'):
        scheduler.register_task(task)
    task.max_retries = 0
    scheduler.register_task(task)
    assert run(scheduler) == 1
    assert len(list((source.parent / 'output').rglob('*.log'))) == 2
    assert len(Database.read_runs(db.db_path)) == 1


def test_cli_snapshot_is_restored_after_config_removed(setup, capsys):
    source, db = setup
    path = source.parent / 'review.json'
    path.write_text(json.dumps({'version': 1, 'name': 'review', 'steps': [
        {'id': 'inspect', 'operation': 'inspect', 'parameters': {'source': 'source'}}]}))
    prefix = ['--database', db.db_path]
    assert main([*prefix, 'task', 'add', '--name', 'review', '--workflow', str(path),
                 '--schedule', '2020-01-01T00:00:00+00:00', '--format', 'json']) == 0
    task_id = json.loads(capsys.readouterr().out)['task_id']
    path.unlink()
    assert main([*prefix, 'task', 'run-due', '--format', 'json']) == 0
    assert json.loads(capsys.readouterr().out)['dispatched'] == 1
    assert main([*prefix, 'task', 'list', '--format', 'json']) == 0
    assert json.loads(capsys.readouterr().out)['tasks'][0]['id'] == task_id
    assert main([*prefix, 'task', 'attempts', '--format', 'json']) == 0
    assert json.loads(capsys.readouterr().out)['attempts'][0]['status'] == 'SUCCESS'


def test_active_cancel_request_terminates_without_retry(setup):
    source, db = setup
    scheduler = TaskScheduler(db, clock=lambda: NOW, poll_interval=.02)
    task = shell(source, 'import time\ntime.sleep(20)\n')
    scheduler.register_task(task)
    async def scenario():
        await scheduler.start()
        for _ in range(300):
            if db.schedule_attempts() and db.schedule_attempts()[0]['pid']:
                break
            await asyncio.sleep(.01)
        scheduler.cancel_task(task.id)
        for _ in range(300):
            if scheduler.tasks[task.id].status == 'CANCELLED':
                break
            await asyncio.sleep(.01)
        await scheduler.stop()
    asyncio.run(scenario())
    assert scheduler.tasks[task.id].status == 'CANCELLED'
    assert db.schedule_attempts()[0]['status'] == 'CANCELLED'
    assert run(scheduler) == 0


def test_real_monotonic_timeout_reaps_worker(setup):
    source, db = setup
    scheduler = TaskScheduler(db, clock=lambda: NOW, poll_interval=.02)
    task = shell(source, 'import time\ntime.sleep(20)\n', timeout_seconds=1)
    scheduler.register_task(task)
    assert run(scheduler) == 1
    assert scheduler.tasks[task.id].status == 'FAILED'
    assert 'timed out' in db.schedule_attempts()[0]['report']['error']


def test_claim_journal_failure_prevents_subprocess(setup, monkeypatch):
    source, db = setup
    marker = source.parent / 'unwritten'
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    task = shell(source, 'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("bad")\n')
    scheduler.register_task(task)
    def denied(*args):
        raise sqlite3.OperationalError('claim journal denied')
    monkeypatch.setattr(db, 'claim_schedule', denied)
    with pytest.raises(sqlite3.OperationalError):
        run(scheduler)
    assert not marker.exists() and not db.schedule_attempts()


def test_finish_failure_keeps_running_for_recovery_and_actual_output(setup, monkeypatch):
    source, db = setup
    marker = source.parent / 'written'
    scheduler = TaskScheduler(db, clock=lambda: NOW)
    task = shell(source, 'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("done")\n')
    scheduler.register_task(task)
    def denied(*args):
        raise sqlite3.OperationalError('finish journal denied')
    monkeypatch.setattr(db, 'finish_schedule', denied)
    with pytest.raises(sqlite3.OperationalError):
        run(scheduler)
    assert marker.read_text() == 'done'
    assert db.schedule_attempts()[0]['status'] == 'RUNNING'
    with pytest.raises(RuntimeError, match='Interrupted'):
        run(TaskScheduler(Database(db.db_path), clock=lambda: NOW))
    assert marker.read_text() == 'done'


def test_owner_lock_is_enforced_in_another_process(setup):
    _, db = setup
    scheduler = TaskScheduler(db)
    with scheduler.ownership():
        result = subprocess.run([sys.executable, '-m', 'taskmaster', '--database', db.db_path,
                                 'task', 'run-due', '--format', 'json'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and 'owns this database' in json.loads(result.stdout)['error']


def test_legacy_rows_are_preserved_without_inventing_commands(setup):
    _, db = setup
    with db._connection() as conn:
        conn.execute("INSERT INTO tasks(id,name,schedule_time) VALUES ('legacy','legacy','2020-01-01')")
    assert run(TaskScheduler(db)) == 0
    assert db.get_task('legacy')['name'] == 'legacy'
    assert not db.schedule_attempts()
