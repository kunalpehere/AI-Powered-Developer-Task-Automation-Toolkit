# Phase 4 — Validated workflows and execution history

Date: 15 October 2026 (Asia/Calcutta)

Status: complete. Phase 5 has not started.

Phase 4 adds versioned JSON workflows, sequential named operations, and durable
run/step history to the existing file planning/execution contract. The
[README](../README.md#validated-workflows-and-run-history) documents commands,
parameters, defaults, and a runnable [example](../examples/workflows/review-artifacts.json).

## Implementation

| Component | Responsibility |
| --- | --- |
| `config.py` | Strict version-1 JSON schema, immutable validated steps, canonical serialization and SHA-256 fingerprint |
| `operations.py` | Closed inspect/duplicates/organize registry, parameter normalization shared with direct commands, prepare/run adapters |
| `workflows.py` | Sequential execution, stop/continue policy, UUID run IDs, UTC times, structured diagnostics and journaling |
| `database.py` | Transactional version-1 schema initialization/migration, run/step records, linked file outcomes, read-only history queries |
| CLI/reporting | Validate/run/history commands, tracked direct and interactive organization, readable and JSON reports, useful exit codes |

The whole configuration is validated before execution. Unknown fields and
operations, duplicate keys, nonfinite numbers, wrong types, invalid patterns or
template syntax, duplicate step IDs and unsupported versions fail before any step
runs. Source existence and destination containment are checked when each step is
prepared against the current filesystem. Configurations contain 1–100 steps, use UTF-8 with optional BOM, and have a
1 MiB file limit. No eval, shell execution, dynamic imports, credentials or
environment mutation are exposed by the workflow registry. The inherited task
scheduler remains a separate prototype.

Relative operation paths resolve against the configuration's parent; home paths
expand before resolving relative paths. Database paths belong to execution
context and resolve against the shell's current directory. Names, IDs and paths
are public metadata stored in reports. Validation errors omit unknown values;
diagnostic text redacts common credential assignments and URL userinfo. This is
not a universal secret detector: do not put secrets in names or paths. Logging
uses standard-library loggers and run/step context; importing modules no longer
configures the root logger through the scheduler.

Preview reads current inputs without creating a database or outputs. It does not
simulate earlier copies for later steps. Apply prepares steps just before their
execution, permitting later steps to consume actual earlier outputs. Workflows
that contain a move require `--apply --yes` before journaling or execution; copy
workflows require `--apply`. Direct and interactive organization still execute
the exact captured plan shown for approval, now within a tracked single-step run.

Stop/continue policy operates between steps. Organization continues reporting
individual file outcomes within a step. Any incomplete operation or journal
failure produces exit 1; explicit conflict skips remain nonfailures. Successful
files are retained when other files/steps fail. There is no rollback or retry.

## Persistence contract

Writable initialization uses an explicit SQLite transaction and `user_version=1`.
It preserves legacy task/file/index rows, including historical outcome fields,
while adding runs, ordered steps and nullable run/step links to file operations.
New file-operation IDs use full UUIDs; old IDs are not rewritten. Unsupported
newer schemas are rejected without downgrade. History uses file-backed SQLite;
the inherited per-operation connection design does not support persistent
`:memory:` databases.

Run creation commits before any step executes; step start commits before its
operation. Failure to write either start record blocks the corresponding action.
File results keep filesystem and history outcomes separate. Failure to save a
completed step/run cannot undo completed file changes and returns an incomplete
report. An interruption or final-journal failure may leave a durable run marked
`running`; history merges saved step states without inventing completion. There
is no automatic recovery, resume, timeout reconciliation or concurrent runner.

History list/show use read-only connections without creating missing databases
or migrating legacy ones. A missing file lists zero runs; an unknown ID fails.
The journal and its SQLite sidecars must be outside selected inputs and the
destination root. Apply creates the journal before preparing workflow steps, so
selecting an entire project that contains the journal will fail protection checks;
use explicit artifact includes or place history elsewhere. The workflow config
cannot itself be selected or replaced.

Low-level `FileOrganizer.apply` remains available without run journaling; use
`run_workflow` or the CLI for tracked execution. The filesystem and SQLite are
separate transactions. Existing race, link, metadata and copy/unlink limits from
[Phase 2](PHASE_2.md) and [Phase 3](PHASE_3.md) still apply.

## Verification

On Python 3.12.4 / Windows, the final full suite passed **195 tests**, with **one
skip** for unavailable file-symlink creation privileges (WinError 1314). Actual
Windows junction tests passed. Permission and journal failures are primarily
injected, rather than claiming broad real ACL coverage.

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=.test-tmp --junitxml=docs\audits\phase4-test-results.xml
```

The final run took 49.80 seconds. Evidence:
[JUnit XML](audits/phase4-test-results.xml). Existing Phase 1–3 regressions remain,
with new schema/round-trip, direct-validation parity, path resolution, source
preservation, preview, copy/move approval, mixed file outcomes, stop/continue,
dependent-step, interrupted-run, migration, read-only history and diagnostic
redaction checks. Start/file/step/final journal failures are tested independently
to verify both actual filesystem outcomes and persisted run states.

A normal wheel was built with existing setuptools and installed offline from
cached runtime wheels into a new `.venv-phase4`, without global site-packages:

```powershell
# Set TEMP and TMP to the writable .install-check\tmp directory first.
python -m pip wheel --no-deps --no-build-isolation --wheel-dir .install-check\phase4-wheels .
python -m venv --without-pip .venv-phase4
.\.venv\Scripts\python.exe -m pip --python .venv-phase4\Scripts\python.exe install --no-index --find-links .install-check\wheels .install-check\phase4-wheels\taskmaster-2.0.1-py3-none-any.whl
.\.venv\Scripts\python.exe -B docs\audits\verify_phase4_install.py
```

The [verification helper](audits/verify_phase4_install.py) uses a new disposable
fixture on every run, removes `PYTHONPATH`, and launches both wheel and editable
entry points outside the source tree. All **32 installed-package checks passed**.
It checks workflow validation/preview/apply,
config-relative paths, conflict skips, failure policies, move approval before
journal creation, linked full UUID history, unknown/legacy history, direct-command
tracking, invalid configurations, read-only deterministic commands and installed
dependency consistency. Results are in
[installed-package evidence](audits/phase4-install-results.json).

Sample reports: [validation](audits/phase4-sample-validation.json),
[preview](audits/phase4-sample-preview.json), [apply](audits/phase4-sample-run.json),
and [history](audits/phase4-sample-history.json). Fixture paths and timestamps in
these artifacts are examples from the recorded run.

The package retains the unreleased baseline version 2.0.1 and its existing
dependencies. No release was published. Before/after evidence is preserved in
[reference archive](audits/phase4-reference.zip),
[source diff](audits/phase4-source.diff), and
[SHA-256 manifest](audits/phase4-change-manifest.json). Earlier phase reports
describe historical snapshots; their earlier deferral statements remain intact.
The [consistency checks](audits/phase4-verification.json) compare all 19 Python
modules in the source, wheel and fresh installation, parse source/tests, check
local documentation links, and confirm that execution and plugins are unchanged.
The final wheel SHA-256 is
`55570eb2ee992d2192d231014568163f58204cbb8001794a3e47aee896b67f40`.

## Phase boundary

Phase 4 acceptance is covered by shared validation, accurate file/run outcomes,
explicit failure policy, versioned history and contextual diagnostics. Phase 5
CI, coverage reporting, dependency auditing/locking, broader platform validation,
release/provenance work remain pending. Scheduler correctness, plugin execution,
image/PDF features, automatic duplicate deletion, recovery/resume and distributed
execution are outside this implementation.
