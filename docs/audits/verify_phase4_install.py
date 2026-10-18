"""Exercise wheel and editable Phase 4 CLIs outside the source checkout.

Requires a wheel installed into .venv-phase4. Uses only newly created fixtures;
retains results under .install-check and replaces this phase's JSON evidence.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
scratch = ROOT / '.install-check/phase4-outside'
scratch.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix='verified-', dir=scratch))
cwd = work / 'other-cwd'
cwd.mkdir()
shutil.copytree(ROOT / 'examples', work / 'examples')
config = work / 'examples/workflows/review-artifacts.json'
source = work / 'examples/fixtures/workspace'
destination = work / 'examples/fixtures/organized'
history = work / 'history.sqlite'
clean = ROOT / '.venv-phase4/Scripts'
editable = ROOT / '.venv/Scripts'
environment = dict(os.environ)
environment.pop('PYTHONPATH', None)
environment['PYTHONDONTWRITEBYTECODE'] = '1'
results = []


def check(label, args, expected=0, as_json=False):
    args = [str(arg) for arg in args]
    result = subprocess.run(args, cwd=cwd, env=environment, capture_output=True,
                            text=True, timeout=30)
    results.append(dict(check=label, argv=args, exit_code=result.returncode,
                        stdout=result.stdout, stderr=result.stderr))
    assert result.returncode == expected, (label, result.stdout, result.stderr)
    print(f'{len(results)}: {label} passed', flush=True)
    return json.loads(result.stdout) if as_json else result.stdout


def cli(label, *args, expected=0, database=history, as_json=True):
    return check(label, [clean / 'tm.exe', '--database', database, *args,
                        *(['--format', 'json'] if as_json else [])], expected, as_json)


def save_config(name, document):
    path = work / (name + '.json')
    path.write_text(json.dumps(document), encoding='utf-8')
    return path


for prefix, label in ((clean, 'wheel'), (editable, 'editable')):
    check(label + ' module help', [prefix / 'python.exe', '-B', '-m', 'taskmaster', '--help'])
    for entry in ('tm.exe', 'taskmaster.exe'):
        check(label + ' ' + entry, [prefix / entry, '--help'])
check('wheel imports without optional processors', [clean / 'python.exe', '-I', '-c',
      "import taskmaster, taskmaster.config, taskmaster.operations, taskmaster.workflows, importlib.util; "
      "print(taskmaster.__file__); assert '.venv-phase4' in taskmaster.__file__; "
      "assert importlib.util.find_spec('PIL') is None; assert importlib.util.find_spec('PyPDF2') is None"])
validated = cli('canonical configuration', 'workflow', 'validate', config)
assert validated['complete']
preview = cli('read-only example preview from other cwd', 'workflow', 'run', config)
assert preview['complete'] and len(preview['steps']) == 3
assert not history.exists() and not destination.exists()
applied = cli('apply copy example', 'workflow', 'run', config, '--apply')
assert applied['complete'] and applied['history']['status'] == 'recorded'
assert applied['steps'][2]['report']['summary']['successful'] == 3
assert (source / 'src/app.py').exists() and len(list(destination.rglob('*.log'))) == 2
listed = cli('history list', 'history', 'list')
shown = cli('history exact run', 'history', 'show', applied['run_id'])['run']
assert shown == applied
check('history rows link run and step', [clean / 'python.exe', '-I', '-c',
      "import sqlite3,uuid,sys; c=sqlite3.connect(sys.argv[1]); "
      "assert c.execute('pragma user_version').fetchone()[0]==1; "
      "rows=c.execute('select id,run_id,step_id from file_operations').fetchall(); "
      "assert len(rows)==3; assert all(str(uuid.UUID(r[0]))==r[0] and r[1]==sys.argv[2] "
      "and r[2]=='copy_artifacts' for r in rows)", history, applied['run_id']])
repeated = cli('repeat copy skips conflicts', 'workflow', 'run', config, '--apply')
assert repeated['complete'] and repeated['run_id'] != applied['run_id']
assert repeated['steps'][2]['report']['summary']['skipped'] == 3
cli('text workflow preview', 'workflow', 'run', config, as_json=False)
cli('text history', 'history', 'show', applied['run_id'], as_json=False)
for policy in ('stop', 'continue'):
    path = save_config(policy, {'version': 1, 'name': policy, 'on_failure': policy, 'steps': [
        {'id': 'missing', 'operation': 'inspect', 'parameters': {'source': 'absent'}},
        {'id': 'valid', 'operation': 'inspect', 'parameters': {'source': str(source)}}]})
    report = cli(policy + ' after runtime failure', 'workflow', 'run', path, '--apply', expected=1)
    assert report['steps'][0]['status'] == 'failed'
    assert report['steps'][1]['status'] == ('not_run' if policy == 'stop' else 'success')
move_source = work / 'move-source'
move_source.mkdir()
(move_source / 'one.log').write_text('move fixture', encoding='utf-8')
move = save_config('move', {'version': 1, 'name': 'move', 'steps': [
    {'id': 'move', 'operation': 'organize', 'parameters': {'source': str(move_source),
     'destination': str(work / 'moved'), 'includes': ['*.log'], 'action': 'move'}}]})
move_db = work / 'move.sqlite'
cli('move requires approval before journal', 'workflow', 'run', move, '--apply', expected=1, database=move_db)
assert not move_db.exists() and (move_source / 'one.log').exists()
assert cli('approved move', 'workflow', 'run', move, '--apply', '--yes', database=move_db)['complete']
assert not (move_source / 'one.log').exists()
bad = save_config('invalid', {'version': 1, 'name': 'invalid', 'steps': [
    {'id': 'bad', 'operation': 'inspect', 'parameters': {'source': str(source), 'password': 'never-echo-this'}}]})
rejected = cli('unknown secret parameter rejected without echo', 'workflow', 'validate', bad, expected=1)
assert 'never-echo-this' not in json.dumps(rejected)
bad.write_text('{broken', encoding='utf-8')
cli('malformed JSON rejected', 'workflow', 'validate', bad, expected=1)
bad.write_text('{"version":99,"name":"bad","steps":[]}', encoding='utf-8')
cli('unsupported version rejected', 'workflow', 'validate', bad, expected=1)
absent_db = work / 'absent.sqlite'
cli('missing history listing is read-only', 'history', 'list', database=absent_db)
cli('unknown run returns failure', 'history', 'show', 'unknown', expected=1, database=absent_db)
assert not absent_db.exists()
inspection = cli('direct inspection', 'inspect', '--source', source, database=absent_db)
assert cli('direct inspection deterministic', 'inspect', '--source', source, database=absent_db) == inspection
cli('direct duplicates', 'duplicates', '--dir', source, database=absent_db)
assert not absent_db.exists()
direct = cli('direct organization gets run history', 'organize', '--source', source,
             '--destination', work / 'direct-copy', '--include', '*.log', '--action', 'copy', '--apply')
assert direct['complete'] and direct['run_id']
direct_run = cli('direct history association', 'history', 'show', direct['run_id'])['run']
assert direct_run['workflow']['name'] == 'direct-organize'
legacy = work / 'legacy.sqlite'
with sqlite3.connect(legacy) as connection:
    connection.execute('create table old_data(value text)')
    connection.execute("insert into old_data values ('preserved')")
before = legacy.read_bytes()
cli('legacy history read does not migrate', 'history', 'list', database=legacy)
assert legacy.read_bytes() == before
check('clean dependency consistency', [editable / 'python.exe', '-m', 'pip', '--python', clean / 'python.exe', 'check'])
output = ROOT / 'docs/audits'
for name, report in (('phase4-install-results.json', {'cwd': str(cwd), 'checks': results}),
                     ('phase4-sample-preview.json', preview), ('phase4-sample-run.json', applied),
                     ('phase4-sample-history.json', shown), ('phase4-sample-validation.json', validated)):
    (output / name).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(f'{len(results)} installed-package checks passed; evidence saved.')
