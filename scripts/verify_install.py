"""Verify an installed wheel in a fresh environment and disposable fixture tree.

Run with a development interpreter containing pip. All application commands use
the fresh interpreter/entry points, from a directory outside the checkout.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('reports/installed.json'))
    parser.add_argument('--wheelhouse', type=Path, help='Use only cached runtime wheels from this directory')
    parser.add_argument('--editable', action='store_true', help='Also verify the calling editable installation')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    wheel = args.wheel.resolve(strict=True)
    output = args.output.resolve()
    environment = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'COVERAGE_PROCESS_START', 'COV_CORE_SOURCE',
                'COV_CORE_CONFIG', 'COV_CORE_DATAFILE'):
        environment.pop(key, None)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
                       PIP_DISABLE_PIP_VERSION_CHECK='1')
    results = []
    with TemporaryDirectory(prefix='taskmaster-installed-') as temporary:
        base = Path(temporary).resolve()
        cwd = base / 'other-cwd'
        cwd.mkdir()

        def check(label, command, expected=0, as_json=False, env=None):
            result = subprocess.run([str(arg) for arg in command], cwd=cwd,
                                    env=env or environment, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=120)
            results.append({'check': label, 'expected_exit': expected, 'exit_code': result.returncode,
                            'stdout': result.stdout, 'stderr': result.stderr})
            if result.returncode != expected:
                raise RuntimeError(f'{label}: exit {result.returncode}, expected {expected}\n'
                                   f'{result.stdout}\n{result.stderr}')
            print(f'{len(results)}: {label} passed', flush=True)
            return json.loads(result.stdout) if as_json else result.stdout

        target = base / 'venv'
        venv.EnvBuilder(with_pip=False).create(target)
        scripts = target / ('Scripts' if os.name == 'nt' else 'bin')
        python = scripts / ('python.exe' if os.name == 'nt' else 'python')
        pip = [sys.executable, '-m', 'pip', '--python', python]
        index = ['--no-index', '--find-links', args.wheelhouse.resolve()] if args.wheelhouse else ['--index-url', 'https://pypi.org/simple']
        check('hashed runtime installation', [*pip, 'install', *index, '--require-hashes',
                                             '-r', root / 'requirements/runtime.txt'])
        check('wheel installation', [*pip, 'install', '--no-index', '--no-deps', wheel])
        check('dependency consistency', [*pip, 'check'])
        check('wheel import origin and optional extras absent', [python, '-I', '-c',
              "import taskmaster,taskmaster.config,taskmaster.workflows,importlib.util,sys; "
              "from pathlib import Path; assert Path(taskmaster.__file__).is_relative_to(Path(sys.argv[1])); "
              "assert importlib.util.find_spec('PIL') is None; assert importlib.util.find_spec('PyPDF2') is None; "
              "print(taskmaster.__file__)", target])
        check('wheel module entry point', [python, '-I', '-m', 'taskmaster', '--help'])
        for entry in ('taskmaster', 'tm'):
            check(entry + ' console entry point', [scripts / (entry + ('.exe' if os.name == 'nt' else '')), '--help'])
        if args.editable:
            check('editable import outside checkout', [sys.executable, '-I', '-c',
                  "import taskmaster,sys; from pathlib import Path; "
                  "assert Path(taskmaster.__file__).resolve()==Path(sys.argv[1]).resolve(); print(taskmaster.__file__)",
                  root / 'taskmaster/__init__.py'])
            check('editable module entry point', [sys.executable, '-I', '-m', 'taskmaster', '--help'])
        (cwd / 'keep.txt').write_bytes(b'demo must preserve this file')
        before_demo = {p.name for p in cwd.iterdir()}
        check('safe disposable demo', [python, '-I', '-m', 'taskmaster.demo', '--directory', cwd])
        assert {p.name for p in cwd.iterdir()} == before_demo
        assert (cwd / 'keep.txt').read_bytes() == b'demo must preserve this file'
        check('invalid demo directory', [python, '-I', '-m', 'taskmaster.demo', '--directory', base / 'missing'], 2)
        shutil.copytree(root / 'examples', base / 'examples', ignore=shutil.ignore_patterns('organized', '__pycache__'))
        config = base / 'examples/workflows/review-artifacts.json'
        source = base / 'examples/fixtures/workspace'
        destination = base / 'examples/fixtures/organized'
        history = base / 'history.sqlite'
        original = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        tm = scripts / ('tm.exe' if os.name == 'nt' else 'tm')

        def cli(label, *options, expected=0, database=history, json_output=True):
            return check(label, [tm, '--database', database, *options,
                                *(['--format', 'json'] if json_output else [])], expected, json_output)

        inspected = cli('inspection JSON', 'inspect', '--source', source, '--top', '3')
        assert inspected['summary']['file_count'] == 4 and inspected['complete']
        assert cli('deterministic inspection', 'inspect', '--source', source, '--top', '3') == inspected
        cli('inspection text', 'inspect', '--source', source, json_output=False)
        selected = cli('inspection exclusion', 'inspect', '--source', source, '--exclude', 'logs/')
        assert selected['summary']['file_count'] == 2
        duplicates = cli('full duplicate JSON', 'duplicates', '--dir', source)
        assert duplicates['summary']['duplicate_groups'] == 1 and duplicates['summary']['hashed_files'] == 2
        cli('duplicate text', 'duplicates', '--dir', source, json_output=False)
        cli('automatic deletion refused', 'duplicates', '--dir', source, '--delete', expected=2, json_output=False)
        cli('missing source fails', 'inspect', '--source', base / 'absent', expected=1)
        cli('invalid glob fails', 'inspect', '--source', source, '--exclude', '../escape', expected=1)
        validated = cli('workflow validation', 'workflow', 'validate', config)
        assert validated['complete']
        preview = cli('config-relative workflow preview', 'workflow', 'run', config)
        assert preview['complete'] and len(preview['steps']) == 3
        assert not history.exists() and not destination.exists()
        applied = cli('workflow apply copy', 'workflow', 'run', config, '--apply')
        assert applied['complete'] and applied['steps'][2]['report']['summary']['successful'] == 3
        assert original == {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        assert cli('run history show', 'history', 'show', applied['run_id'])['run'] == applied
        assert cli('run history list', 'history', 'list')['runs'][0]['run_id'] == applied['run_id']
        cli('readable run history', 'history', 'show', applied['run_id'], json_output=False)
        again = cli('repeat workflow conflict skips', 'workflow', 'run', config, '--apply')
        assert again['complete'] and again['run_id'] != applied['run_id']
        assert again['steps'][2]['report']['summary']['skipped'] == 3
        with closing(sqlite3.connect(history)) as connection:
            rows = connection.execute('select run_id,step_id from file_operations').fetchall()
            assert len(rows) == 6 and all(row[1] == 'copy_artifacts' for row in rows)
        for policy in ('stop', 'continue'):
            document = {'version': 1, 'name': policy, 'on_failure': policy, 'steps': [
                {'id': 'missing', 'operation': 'inspect', 'parameters': {'source': 'absent'}},
                {'id': 'valid', 'operation': 'inspect', 'parameters': {'source': str(source)}}]}
            path = base / (policy + '.json')
            path.write_text(json.dumps(document), encoding='utf-8')
            failed = cli(policy + ' policy after runtime failure', 'workflow', 'run', path, '--apply', expected=1)
            assert failed['steps'][1]['status'] == ('not_run' if policy == 'stop' else 'success')
        broken = base / 'broken.json'
        broken.write_text('{"password":"never-echo-this",', encoding='utf-8')
        error = cli('invalid config without secret echo', 'workflow', 'validate', broken, expected=1)
        assert 'never-echo-this' not in json.dumps(error)
        absent_db = base / 'absent.sqlite'
        assert cli('missing history read-only', 'history', 'list', database=absent_db)['runs'] == []
        cli('unknown run fails', 'history', 'show', 'unknown', expected=1, database=absent_db)
        assert not absent_db.exists()
        legacy = base / 'legacy.sqlite'
        with closing(sqlite3.connect(legacy)) as connection:
            connection.execute('create table old_data(value text)')
            connection.execute("insert into old_data values ('preserved')")
            connection.commit()
        before = legacy.read_bytes()
        cli('legacy history read does not migrate', 'history', 'list', database=legacy)
        assert legacy.read_bytes() == before
        flags = ['organize', '--source', source, '--include', '*.log', '--action', 'copy',
                 '--destination', base / 'direct']
        cli('direct captured preview', *flags)
        direct = cli('direct apply tracked', *flags, '--apply')
        assert direct['complete'] and direct['summary']['successful'] == 2
        assert cli('direct run history', 'history', 'show', direct['run_id'])['run']['workflow']['name'] == 'direct-organize'
        conflict = cli('conflict error preserves files', *flags, '--apply', expected=1)
        assert conflict['summary']['failed'] == 2
        cli('explicit source selection required', 'organize', '--source', source, '--destination', base / 'unselected',
            expected=2, json_output=False)
        cli('traversal template refused', *flags, '--template', '../escape', expected=1)
        cli('size sorting preview', *flags, '--strategy', 'size')
        move_source = base / 'move-source'
        move_source.mkdir()
        (move_source / 'one.log').write_bytes(b'move this disposable fixture')
        flags = ['organize', '--source', move_source, '--destination', base / 'moved', '--include', '*.log']
        cli('move approval required', *flags, '--apply', expected=1, database=absent_db)
        assert not absent_db.exists() and (move_source / 'one.log').exists()
        assert cli('approved direct move', *flags, '--apply', '--yes')['complete']
        assert not (move_source / 'one.log').exists()
        review = base / 'examples/workflows/scheduled-project-review.json'
        scheduled = cli('register durable project review', 'task', 'add', '--name', 'Scheduled review',
                        '--workflow', review, '--schedule', '2020-01-01T00:00:00+00:00',
                        '--recurrence', 'minutely', '--max-retries', '1')
        task_id = scheduled['task_id']
        review.unlink()  # Registration must keep the validated snapshot.
        saved = cli('restore schedule in another process', 'task', 'list')['tasks'][0]
        assert saved['id'] == task_id and saved['run_count'] == 0
        due = cli('dispatch saved review without original config', 'task', 'run-due')
        assert due['complete'] and due['dispatched'] == 1
        attempts = cli('durable attempt history', 'task', 'attempts')['attempts']
        assert attempts[0]['status'] == 'SUCCESS'
        assert attempts[0]['report']['workflow_report']['steps'][0]['report']['summary']['file_count'] == 4
        cli('pause durable task', 'task', 'pause', task_id)
        cli('resume durable task', 'task', 'resume', task_id)
        cli('cancel durable task', 'task', 'cancel', task_id)
        assert cli('cancelled task persists', 'task', 'list')['tasks'][0]['status'] == 'CANCELLED'
        assert cli('cancelled task not dispatched', 'task', 'run-due')['dispatched'] == 0
        cli('unknown scheduled dependency rejected', 'task', 'add', '--name', 'bad dependency',
            '--operation', 'inspect', '--source', source, '--schedule', '2020-01-01T00:00:00+00:00',
            '--depends-on', 'missing', expected=1)
        check('installed runtime inventory', [python, '-I', '-c',
              "import importlib.metadata,json; print(json.dumps(sorted((d.metadata['Name'],d.version) "
              "for d in importlib.metadata.distributions())))"])
        report = {'complete': True, 'platform': platform.platform(), 'python': sys.version,
                  'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  'runtime_lock_sha256': hashlib.sha256((root / 'requirements/runtime.txt').read_bytes()).hexdigest(),
                  'checks': results}
    assert not base.exists(), 'Disposable fixture cleanup did not finish'
    report['disposable_tree_removed'] = True
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{len(results)} installed-package checks passed; disposable fixtures removed.')


if __name__ == '__main__':
    main()
