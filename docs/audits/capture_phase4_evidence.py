"""Capture the Phase 4 source diff and verify source/wheel/install consistency."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/audits'
with ZipFile(OUT / 'phase4-reference.zip') as archive:
    before = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
paths = set(before)
paths.update(path.relative_to(ROOT).as_posix() for folder in ('taskmaster', 'tests', 'examples')
             for path in (ROOT / folder).rglob('*')
             if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'
             and 'organized' not in path.parts)
paths.update(('docs/PHASE_4.md', 'docs/audits/verify_phase4_install.py',
              'docs/audits/capture_phase4_evidence.py'))
manifest = {}
diff = []
sha = lambda data: hashlib.sha256(data).hexdigest() if data is not None else None
for name in sorted(paths):
    old = before.get(name)
    path = ROOT / name
    new = path.read_bytes() if path.is_file() else None
    manifest[name] = {'before_sha256': sha(old), 'after_sha256': sha(new)}
    if old != new:
        diff.extend(difflib.unified_diff([line + '\n' for line in (old or b'').decode('utf-8-sig').splitlines()],
                    [line + '\n' for line in (new or b'').decode('utf-8-sig').splitlines()],
                    fromfile='before/' + name if old is not None else '/dev/null',
                    tofile='after/' + name if new is not None else '/dev/null'))
(OUT / 'phase4-source.diff').write_text(''.join(diff), encoding='utf-8')
(OUT / 'phase4-change-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

modules = {path.relative_to(ROOT).as_posix(): path for path in (ROOT / 'taskmaster').rglob('*.py')}
for path in [*modules.values(), *(ROOT / 'tests').glob('*.py')]:
    ast.parse(path.read_text(encoding='utf-8-sig'))
wheel = ROOT / '.install-check/phase4-wheels/taskmaster-2.0.1-py3-none-any.whl'
with ZipFile(wheel) as archive:
    assert {name for name in archive.namelist() if name.endswith('.py')} == set(modules)
    for name, path in modules.items():
        assert archive.read(name) == path.read_bytes(), name
        assert (ROOT / '.venv-phase4/Lib/site-packages' / name).read_bytes() == path.read_bytes(), name
assert before['taskmaster/plugins/__init__.py'] == (ROOT / 'taskmaster/plugins/__init__.py').read_bytes()
assert before['taskmaster/execution.py'] == (ROOT / 'taskmaster/execution.py').read_bytes()
assert before['taskmaster/scheduler.py'].decode('utf-8-sig').replace('\r\n', '\n').replace(
    'logging.basicConfig(level=logging.INFO)\n', '') == (ROOT / 'taskmaster/scheduler.py').read_text(encoding='utf-8-sig')
suite = ET.parse(OUT / 'phase4-test-results.xml').getroot().find('testsuite')
assert (suite.get('tests'), suite.get('failures'), suite.get('errors'), suite.get('skipped')) == ('196', '0', '0', '1')
installed = json.loads((OUT / 'phase4-install-results.json').read_text(encoding='utf-8'))
assert len(installed['checks']) == 32
verification = {'source_modules': len(modules), 'manifest_files': len(manifest),
                  'changed_files': sum(item['before_sha256'] != item['after_sha256'] for item in manifest.values()),
                  'wheel_sha256': sha(wheel.read_bytes()), 'tests_passed': 195,
                  'tests_skipped': 1, 'installed_checks': 32}
(OUT / 'phase4-verification.json').write_text(json.dumps(verification, indent=2) + '\n', encoding='utf-8')
for name in ('README.md', 'DEVELOPMENT_PLAN.md', 'docs/PHASE_4.md'):
    path = ROOT / name
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
        if '://' not in target and not target.startswith('#'):
            assert (path.parent / target.split('#')[0]).exists(), (name, target)
print(json.dumps(verification, indent=2))
