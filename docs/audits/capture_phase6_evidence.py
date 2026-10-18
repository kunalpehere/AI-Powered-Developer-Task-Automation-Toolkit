"""Capture the Phase 6 review diff and verify final test/install evidence."""
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/audits'
with ZipFile(OUT / 'phase6-reference.zip') as archive:
    before = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
paths = set(before)
for folder in ('taskmaster', 'tests', 'scripts', 'examples', 'requirements', '.github'):
    paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc' and 'organized' not in p.parts)
paths.update(['docs/PHASE_6.md', 'docs/audits/capture_phase6_evidence.py'])
sha = lambda data: hashlib.sha256(data).hexdigest() if data is not None else None
manifest, diff = {}, []
for name in sorted(paths):
    path = ROOT / name
    old, new = before.get(name), path.read_bytes() if path.is_file() else None
    manifest[name] = {'before_sha256': sha(old), 'after_sha256': sha(new)}
    if old != new:
        diff.extend(difflib.unified_diff([v + '\n' for v in (old or b'').decode('utf-8-sig').splitlines()],
                    [v + '\n' for v in (new or b'').decode('utf-8-sig').splitlines()],
                    fromfile='before/' + name if old is not None else '/dev/null',
                    tofile='after/' + name if new is not None else '/dev/null'))
(OUT / 'phase6-source.diff').write_text(''.join(diff), encoding='utf-8')
(OUT / 'phase6-change-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
suite = ET.parse(OUT / 'phase6-test-results.xml').getroot().find('testsuite')
assert suite.get('failures') == suite.get('errors') == '0'
installed = json.loads((OUT / 'phase6-install-results.json').read_text(encoding='utf-8'))
assert installed['complete'] and installed['disposable_tree_removed']
assert all(c['exit_code'] == c['expected_exit'] for c in installed['checks'])
wheel = ROOT / 'dist/taskmaster-2.0.1-py3-none-any.whl'
assert installed['wheel_sha256'] == sha(wheel.read_bytes())
assert installed['runtime_lock_sha256'] == sha((ROOT / 'requirements/runtime.txt').read_bytes())
assert before['requirements/runtime.txt'] == (ROOT / 'requirements/runtime.txt').read_bytes()
assert before['requirements/dev.txt'] == (ROOT / 'requirements/dev.txt').read_bytes()
coverage = json.loads((OUT / 'phase6-coverage.json').read_text(encoding='utf-8'))
summary = {'tests_passed': int(suite.get('tests')) - int(suite.get('skipped')),
           'tests_skipped': int(suite.get('skipped')), 'installed_checks': len(installed['checks']),
           'coverage_percent': coverage['totals']['percent_covered'],
           'wheel_sha256': installed['wheel_sha256'], 'dependencies_unchanged': True,
           'installed_check_execution': 'Windows host process-control access; the restricted-sandbox run timed out',
           'hosted_ci_executed': False, 'release_published': False}
(OUT / 'phase6-verification.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, indent=2))
