"""Check local wheel/sdist contents without installing or executing the package."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import tarfile
import tomllib
from zipfile import ZipFile

from packaging.requirements import Requirement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('dist'))
    parser.add_argument('--output', type=Path, default=Path('reports/distributions.json'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    wheels = list(args.directory.glob('*.whl'))
    sources = list(args.directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit('Expected exactly one wheel and one source archive; use a fresh build directory')
    modules = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / 'taskmaster').rglob('*.py')}
    with ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        assert {name for name in names if name.endswith('.py')} == set(modules), 'Unexpected wheel modules'
        for name, content in modules.items():
            assert archive.read(name) == content, name
        metadata = BytesParser().parsebytes(archive.read(next(n for n in names if n.endswith('/METADATA'))))
        assert metadata['Name'] == config['name'] and metadata['Version'] == config['version']
        assert metadata['Requires-Python'] == config['requires-python']
        runtime = {Requirement(value) for value in metadata.get_all('Requires-Dist', [])
                   if not Requirement(value).marker}
        assert runtime == {Requirement(value) for value in config['dependencies']}, 'Runtime metadata dependencies differ'
        assert not metadata['License'] and not metadata['License-Expression'], 'Do not invent unresolved project licensing'
        entries = archive.read(next(n for n in names if n.endswith('/entry_points.txt'))).decode()
        assert 'taskmaster = taskmaster.cli:main' in entries and 'tm = taskmaster.cli:main' in entries
        assert not any('/tests/' in name or '/docs/audits/' in name for name in names)
    with tarfile.open(sources[0], 'r:gz') as archive:
        prefix = f"{config['name']}-{config['version']}/"
        files = {member.name.removeprefix(prefix): archive.extractfile(member).read()
                 for member in archive.getmembers() if member.isfile()}
        required = ['README.md', 'ATTRIBUTION.md', 'pyproject.toml', 'requirements/runtime.txt',
                    'requirements/dev.txt', 'scripts/verify_install.py', 'scripts/check_dist.py',
                    'examples/workflows/review-artifacts.json', 'docs/DESIGN.md', 'docs/RELEASE.md']
        required += list(modules)
        required += [p.relative_to(root).as_posix() for p in (root / 'tests').glob('*.py')]
        required += [p.relative_to(root).as_posix() for p in (root / 'docs').glob('*.md')]
        required += [p.relative_to(root).as_posix() for p in (root / 'examples/fixtures/workspace').rglob('*') if p.is_file()]
        for name in required:
            assert files.get(name) == (root / name).read_bytes(), f'Missing/stale source archive file: {name}'
        assert not any('/.venv' in name or '/.install-check/' in name or '/docs/audits/' in name
                       or 'examples/fixtures/organized/' in name for name in files)
    report = {'python_modules': len(modules), 'name': config['name'], 'version': config['version'],
              'artifacts': [{'file': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                            for p in (wheels[0], sources[0])], 'complete': True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
