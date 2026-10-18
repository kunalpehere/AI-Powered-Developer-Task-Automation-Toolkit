"""Internal process boundary for a persisted, validated named workflow attempt."""
import json
from pathlib import Path
import sys
import subprocess

from .config import validate_workflow
from .schedules import ScheduledTask
from .workflows import run_workflow, safe_message


def main():
    try:
        payload = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError('Worker payload exceeds 2 MiB')
        document = json.loads(payload)
        task = ScheduledTask(**document['task']).validate()
        if task.operation == 'subprocess':
            # Parent contains this worker before sending stdin. The shell and all
            # descendants therefore start inside its Job Object/process group.
            return subprocess.run(task.parameters['command'], shell=True, check=False).returncode
        if task.operation == 'workflow':
            workflow = validate_workflow(task.parameters['workflow'])
            apply, confirmed = task.parameters['apply'], task.parameters['confirmed']
        else:
            workflow = validate_workflow({'version': 1, 'name': task.name, 'steps': [
                {'id': 'review', 'operation': task.operation, 'parameters': task.parameters}]})
            apply, confirmed = False, False
        report = run_workflow(workflow, base_dir=Path(task.base_dir), apply=apply,
                              confirmed=confirmed, history_path=Path(document['database']),
                              config_path=Path(task.config_path) if task.config_path else None)
        print(json.dumps(report))
        return 0 if report['complete'] else 1
    except Exception as error:
        print(json.dumps({'complete': False, 'error': safe_message(str(error))}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
