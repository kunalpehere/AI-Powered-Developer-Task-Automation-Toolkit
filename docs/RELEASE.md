# Development validation and release gates

This is a locally validated development candidate. No package or site has been
published. The inherited version 2.0.1 remains an unreleased baseline identifier.

## Repeat the checks

Install the hashed development baseline and editable project as described in the
[README](../README.md). From the repository root, run:

```text
python -m pip check
python -m ruff check taskmaster tests scripts
python scripts/check_project.py
python -m pytest -q --cov --cov-report=term-missing --cov-report=xml:reports/coverage.xml --cov-report=json:reports/coverage.json --junitxml=reports/tests.xml
python -m build --no-isolation
python scripts/check_dist.py
python scripts/verify_install.py --wheel dist/taskmaster-2.0.1-py3-none-any.whl --editable
python -m pip_audit -r requirements/runtime.txt --require-hashes --disable-pip --progress-spinner off --format json --output reports/runtime-audit.json
python -m pip_audit -r requirements/dev.txt --require-hashes --disable-pip --progress-spinner off --format json --output reports/dev-audit.json
```

Use the virtual environment's interpreter for `python`. Build into a fresh output
directory when verifying a changed version: `check_dist.py` rejects multiple
wheels/archives and compares package modules, metadata, examples, scripts and
tests with the working tree. It reads archives without extracting them. The
source archive includes setup instructions, lockfiles and test fixtures, while
audit snapshots, virtual environments and generated organization output are
excluded. Historical evidence/archives linked by phase reports are repository-only.
Wheels contain the runtime package and required distribution metadata. Run the
full documentation-link check from a checkout containing that historical evidence.

The install verifier creates its own temporary virtual environment, installs the
hashed runtime and local wheel, removes `PYTHONPATH`, and launches CLIs from an
unrelated working directory. It exercises read-only inspection/duplicates,
preview/copy/move, collisions, invalid inputs, stop/continue, direct/workflow
history, legacy read-only queries, both entry points and the safe demo. The demo
check places an existing sentinel file next to its temporary child and verifies
that it survives. The verifier removes only its own temporary tree. Optional
`--wheelhouse PATH` uses cached runtime wheels without network.

Coverage includes branches and subprocess CLI tests. Reports include inherited
plugin/menu paths and platform-specific process code, so a total percentage alone
does not validate scheduling or plugin guarantees. Read missing branches and behavior tests;
do not add assertion-free calls merely to raise a percentage. Coverage is reported
without an arbitrary global threshold in this initial baseline.

## CI and publication

[CI](../.github/workflows/ci.yml) defines Windows/Ubuntu × CPython 3.12–3.14,
hashed installs, lint, branch coverage, wheel/source verification, fresh installed
smoke checks, and a separate dependency-advisory job. Actions use verified commit
SHAs; permissions are read-only and checkout does not persist credentials. Reports
are retained for 14 days. No publish job, deployment token or release credential
is configured. Advisory lookup needs the network; service failure must fail the
job rather than silently treating an unaudited dependency set as clean.

Before publishing retained/adapted code:

1. Obtain the exact upstream repository/revision and actual license/copyright
   notices. Reconcile them with the preserved original snapshot and update
   [attribution](../ATTRIBUTION.md). No LICENSE is fabricated from a README label.
2. Run the hosted matrix in a connected repository and inspect every job's
   results/skips. Local Windows evidence and a YAML file do not prove Linux or
   newer-Python success. Do not add a passing badge until an actual run exists.
3. Rerun dependency audits, assess any findings without ignoring IDs to obtain a
   green result, and retest intentional dependency updates.
4. Review the source diff, known [platform limits](PLATFORMS.md), advertised
   behavior/evidence, notices and final artifacts. Choose a release version and
   build from that reviewed state. Publishing requires a separate explicit action.

Unresolved upstream permission and absent hosted CI evidence remain release
gates. They do not prevent local development/testing; they prevent describing
this candidate as a verified distributable portfolio release. Phase 6 scheduling
is locally implemented and included in the regression and installed checks.
