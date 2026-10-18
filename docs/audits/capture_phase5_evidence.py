"""Capture local Phase 5 changes and check preserved runtime semantics/evidence.

Writes review evidence; hosted CI and missing upstream notices cannot be inferred.
Run after final build, audits, fresh install and regression verification.
"""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/audits'
with ZipFile(OUT / 'phase5-reference.zip') as archive:
    before = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
paths = set(before)
for folder in ('scripts', 'requirements', '.github'):
    paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts)
paths.update(['MANIFEST.in', 'docs/PHASE_5.md', 'docs/DESIGN.md', 'docs/RELEASE.md',
              'docs/DEPENDENCIES.md', 'docs/PLATFORMS.md', 'docs/FEATURE_EVIDENCE.md',
              'docs/audits/capture_phase5_evidence.py'])
sha = lambda value: hashlib.sha256(value).hexdigest() if value is not None else None
manifest, diff = {}, []


class WithoutImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None


for name in sorted(paths):
    old = before.get(name)
    path = ROOT / name
    new = path.read_bytes() if path.exists() else None
    manifest[name] = {'before_sha256': sha(old), 'after_sha256': sha(new)}
    if name.startswith('taskmaster/') and name.endswith('.py'):
        old_ast = WithoutImports().visit(ast.parse(old.decode('utf-8-sig')))
        new_ast = WithoutImports().visit(ast.parse(new.decode('utf-8-sig')))
        assert ast.dump(old_ast) == ast.dump(new_ast), f'Unexpected behavioral change in {name}'
    if old != new:
        diff.extend(difflib.unified_diff([line + '\n' for line in (old or b'').decode('utf-8-sig').splitlines()],
                    [line + '\n' for line in (new or b'').decode('utf-8-sig').splitlines()],
                    fromfile='before/' + name if old is not None else '/dev/null',
                    tofile='after/' + name if new is not None else '/dev/null'))
(OUT / 'phase5-source.diff').write_text(''.join(diff), encoding='utf-8')
(OUT / 'phase5-change-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
suite = ET.parse(OUT / 'phase5-test-results.xml').getroot().find('testsuite')
assert (suite.get('tests'), suite.get('failures'), suite.get('errors'), suite.get('skipped')) == ('196', '0', '0', '1')
coverage = json.loads((OUT / 'phase5-coverage.json').read_text(encoding='utf-8'))
assert coverage['meta']['branch_coverage']
audits = {}
for kind in ('runtime', 'dev'):
    report = json.loads((OUT / f'phase5-{kind}-audit.json').read_text(encoding='utf-8'))
    assert all(not item.get('vulns') and 'skip_reason' not in item for item in report['dependencies'])
    audits[kind] = len(report['dependencies'])
installed = json.loads((OUT / 'phase5-install-results.json').read_text(encoding='utf-8'))
assert installed['complete'] and installed['disposable_tree_removed']
assert all(item['exit_code'] == item['expected_exit'] for item in installed['checks'])
wheel = ROOT / 'dist/taskmaster-2.0.1-py3-none-any.whl'
assert installed['wheel_sha256'] == sha(wheel.read_bytes()), 'Fresh-install evidence must match the final wheel'
assert installed['runtime_lock_sha256'] == sha((ROOT / 'requirements/runtime.txt').read_bytes())
summary = {'tests_passed': 195, 'tests_skipped': 1,
           'coverage_percent': coverage['totals']['percent_covered'],
           'covered_branches': coverage['totals']['covered_branches'],
           'total_branches': coverage['totals']['num_branches'],
           'audited_dependencies': audits, 'installed_checks': len(installed['checks']),
           'wheel_sha256': installed['wheel_sha256'],
           'runtime_ast_unchanged_except_imports': True,
           'hosted_ci_executed': False, 'upstream_provenance_verified': False,
           'release_published': False}
(OUT / 'phase5-verification.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, indent=2))
