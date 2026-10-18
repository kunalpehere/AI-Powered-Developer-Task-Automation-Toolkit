# Phase 5 — Documentation, testing and release readiness

Date: 15 October 2026 (Asia/Calcutta)

Status: local implementation complete. A distributable release still requires
hosted CI results and verified upstream reuse terms. Phase 6 has not started.

## Changes

- Added hashed runtime/development dependency baselines and documented regeneration.
  Runtime remains the same four-package closure. Development adds lint, branch
  coverage, build, dependency auditing and configuration-validation tools.
- Added Windows/Ubuntu × CPython 3.12/3.13/3.14 CI, with read-only permissions,
  immutable action SHAs, coverage/JUnit artifacts and independent runtime/dev audits.
  No publishing or credentials are configured.
- Added distribution-content validation and a portable fresh-wheel installation
  verifier that runs CLI fixtures outside the checkout. Source packages include
  tests, examples, lockfiles and development guides; generated state and historical
  audit archives remain outside distributions.
- Added [design notes](DESIGN.md), [platform notes](PLATFORMS.md),
  [feature-to-evidence mapping](FEATURE_EVIDENCE.md),
  [dependency review](DEPENDENCIES.md), and a [release guide](RELEASE.md).
- Removed 23 unused imports identified by Ruff. No scheduler, plugin or filesystem
  behavior was intentionally changed. Historical reports/archives are retained.

## Local verification

The complete suite passed **195 tests**, with **one file-symlink privilege skip**
(WinError 1314). Real Windows junction fixtures passed. Python was 3.12.4 on Windows.
Permission/write/journal failures are primarily injected for repeatability.

Branch and subprocess coverage report **74.47%** across the whole runtime package.
This includes inherited experimental code: scheduler 17.65%, plugin prototype
51.06% and the CLI's unsupported/menu paths. Configuration is 97.20%, operations
97.04%, workflows 96.88%, scanning 98.57%, execution 93.38%, and planning 86.79%.
These are combined line/branch coverage percentages, not proof that every
failure/race is handled. The first baseline reports coverage without forcing an
arbitrary global threshold or hiding experimental modules.

Commands used for the coverage run:

```powershell
$env:TEMP = (Resolve-Path .install-check\tmp).Path
$env:TMP = $env:TEMP
.\.venv-phase5-clean\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=.test-tmp --cov --cov-report=term-missing --cov-report=xml:docs/audits/phase5-coverage.xml --cov-report=json:docs/audits/phase5-coverage.json --junitxml=docs/audits/phase5-test-results.xml
```

The final fresh-setup run took 49.97 seconds. Evidence: [JUnit](audits/phase5-test-results.xml),
[coverage XML](audits/phase5-coverage.xml), [coverage JSON](audits/phase5-coverage.json).
Ruff checks correctness rules (`E9`, `F`) over application, tests and scripts;
historical audit helpers are excluded to preserve their snapshots. No broad style
rewrite or coverage-only tests were added.

## Dependencies and packaging

The pinned baseline includes **4 runtime / 43 development packages**. Pip-audit
2.10.1 queried PyPI advisories for both requirements files: **no known
vulnerabilities found**, with no ignored IDs. Results:
[runtime audit](audits/phase5-runtime-audit.json),
[development audit](audits/phase5-dev-audit.json). Audit lookup is metadata-only;
download hashes are checked during installation. This is a point-in-time check,
not a source security audit, malware scan or legal approval.

Pip-tools generated exact pins and download hashes. `--allow-unsafe` includes
pip/setuptools in the development lock rather than leaving the build toolchain
unpinned. The initial resolution took time hashing the many platform wheels;
verbose output confirmed progress. The same lock was then used for a fresh
offline setup from hash-verified downloaded wheels, followed by editable install.

The normal wheel verifier creates its own virtual environment without global
site-packages, installs only hashed runtime packages and the built wheel, and
removes `PYTHONPATH` before subprocess checks. It verifies the demo's preservation
of an existing neighboring sentinel and removes only its disposable fixtures.
Its [results](audits/phase5-install-results.json) cover entry points/import origin,
text/JSON inspection and duplicates, invalid inputs, selected copy/move,
conflicts/approval, workflow policies and run history. Optional image/PDF extras
are absent. The [distribution report](audits/phase5-distributions.json) records
artifact hashes and content checks; the [project report](audits/phase5-project.json)
records installed pins, third-party notice metadata, local links and parsed CI.
All **43 installed-package checks passed**, including verified cleanup.

The first installed run passed its application checks but failed Windows cleanup:
SQLite's connection context manager commits/rolls back without closing the
connection. The verifier now explicitly closes its fixture connections and writes
success evidence only after its temporary directory has been removed. That failed
run is not counted as successful final verification.

The final source/wheel build uses pinned tooling with `--no-isolation`; the wheel
is built from the source archive. Package version remains the unreleased baseline
2.0.1. No package, repository or release was published.

## Provenance and remaining release gates

[Attribution](../ATTRIBUTION.md) distinguishes inherited/adapted components from
new work and preserves the pre-Phase-5 snapshot in
[phase5-reference.zip](audits/phase5-reference.zip). The supplied source still
lacks an upstream URL/revision, actual license file and copyright notices. The
original README's MIT label is recorded, not treated as verified permission. No
license identifier, author or copyright holder is fabricated.

This folder has no Git repository/remote, so the hosted workflow has not run.
WSL has no installed Linux distribution; no local Linux result is claimed.
Newer Python versions and Ubuntu are CI targets, not verified results. Publishing
requires the actual green hosted matrix and resolved upstream terms. See
[release gates](RELEASE.md). The implementation cannot supply missing historical
notices or invent CI passes.

Before/after review evidence:
[source diff](audits/phase5-source.diff),
[SHA-256 manifest](audits/phase5-change-manifest.json), and
[verification summary](audits/phase5-verification.json). Earlier phase reports
describe historical states and remain unchanged.
