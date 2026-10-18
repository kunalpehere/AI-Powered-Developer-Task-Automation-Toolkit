"""Check dependency pins, documentation links, and CI structure locally.

This validates configuration and installed metadata; it does not execute hosted CI.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import tomllib

from packaging.requirements import Requirement
import yaml


def pins(path):
    requirements = {}
    block = ''
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        block += line.removesuffix('\\') + ' '
        if line.endswith('\\'):
            continue
        name, *hashes = block.split()
        requirement = Requirement(name)
        assert str(requirement.specifier).startswith('==') and '*' not in str(requirement.specifier), name
        assert hashes and all(re.fullmatch(r'--hash=sha256:[a-f0-9]{64}', item) for item in hashes), name
        requirements[requirement.name] = str(requirement.specifier)[2:]
        block = ''
    assert not block and requirements
    return requirements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('reports/project.json'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    runtime = pins(root / 'requirements/runtime.txt')
    dev = pins(root / 'requirements/dev.txt')
    assert runtime.items() <= dev.items(), 'Runtime/dev pins disagree'
    for dependency in [*project['dependencies'], *project['optional-dependencies']['dev']]:
        requirement = Requirement(dependency)
        locked = next((version for name, version in dev.items() if name.lower() == requirement.name.lower()), None)
        assert locked is not None and locked in requirement.specifier, dependency
    inventory = []
    for name, version in sorted(dev.items()):
        distribution = metadata.distribution(name)
        assert distribution.version == version, f'{name}: installed {distribution.version}, locked {version}'
        inventory.append({'name': name, 'version': version,
                          'runtime': name in runtime,
                          'license_expression': distribution.metadata.get('License-Expression'),
                          'license_metadata': distribution.metadata.get('License'),
                          'license_classifiers': [v for v in distribution.metadata.get_all('Classifier', [])
                                                  if v.startswith('License ::')],
                          'notice_files': [str(p) for p in distribution.files or ()
                                           if re.search(r'(?i)(?:^|/)(?:licen[cs]e[^/]*|notice[^/]*)$', str(p))]})
    workflow = yaml.load((root / '.github/workflows/ci.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    assert workflow['permissions'] == {'contents': 'read'}
    assert set(workflow['on']) == {'push', 'pull_request', 'workflow_dispatch'}
    matrix = workflow['jobs']['test']['strategy']['matrix']
    assert set(matrix['os']) == {'windows-latest', 'ubuntu-latest'}
    assert matrix['python'] == ['3.12', '3.13', '3.14']
    actions = {}
    for job in workflow['jobs'].values():
        for step in job['steps']:
            if 'uses' in step:
                name, sha = step['uses'].split('@')
                assert re.fullmatch('[a-f0-9]{40}', sha), 'Action must use an immutable SHA'
                actions[name] = sha
    checked_links = 0
    docs = [root / name for name in ('README.md', 'ATTRIBUTION.md', 'DEVELOPMENT_PLAN.md', 'requirements/README.md')]
    docs += list((root / 'docs').glob('*.md'))
    for path in docs:
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8-sig')):
            if '://' in link or link.startswith('#'):
                continue
            target = (path.parent / link.split('#')[0]).resolve()
            # Documentation may link to the report this invocation creates.
            assert target.exists() or target == args.output.resolve(), f'{path.name}: missing {link}'
            checked_links += 1
    report = {'complete': True, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'runtime_pins': len(runtime), 'development_pins': len(dev),
              'checked_local_links': checked_links, 'ci_actions': actions,
              'hosted_ci_executed': False, 'dependency_inventory': inventory}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{len(dev)} installed dependency pins and {checked_links} local links checked; CI YAML parsed.')


if __name__ == '__main__':
    main()
