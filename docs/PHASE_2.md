# Phase 2 implementation record

Date: 15 October 2026 (Asia/Calcutta)  
Status: complete within the tested guarantees below. Phase 3 has not started.

## Result

Organization now builds and validates a captured plan before execution. The CLI
previews by default and requires an explicit destination root and `--apply`.
Move operations require `--yes` in noninteractive use or approval after display
in a terminal. The interactive wizard applies the same plan it displayed.
Copy application requires `--apply` but does not require destructive approval.

The [root README](../README.md) describes current commands and the Python API.
The original scheduler and plugin implementations were not expanded in this
phase. Automatic duplicate deletion remains disabled.

## Changes and rationale

| Area | Implemented behavior |
| --- | --- |
| `models.py` | Frozen source-state, planned-operation, and plan dataclasses; result fields separate filesystem and history outcomes |
| `planning.py` | Read-only scanning, action/policy/template/root validation, complete source fingerprints, fixed destination expansion, conflict/condition reporting, duplicate-target/source detection |
| `execution.py` | Preview without I/O; explicit destructive approval; repeated source/path validation; exclusive file creation; verified copy before source removal; per-file continuation; independent history callback |
| `errors.py` | Shared plan-validation and confirmation errors with actionable CLI handling |
| `organizer.py` | Shared plan/preview/apply API and compatibility adapters; duplicate reports read-only by default; explicit legacy indexing opt-in |
| `database.py` | Additive file-outcome columns for old databases and persistence of new results |
| `cli.py` | Explicit roots, preview/apply modes, error/skip conflicts, copy/move selection, templates, approval, detailed file/history results, lazy persistence |
| Demo/tests/docs | Read-only disposable demo; updated regressions; new failure-scenario tests and current usage documentation |

Planning records file identity, size, nanosecond metadata, and full SHA-256.
Apply revalidates paths and state before opening files and before removing moved
sources. It verifies copied bytes before unlinking. Templates are resolved once
at planning time; changing rules, adding files, or crossing a date boundary does
not silently change a captured plan. The CLI rebuilds a plan for each independent
invocation; saving/loading plans is not implemented.

Roots must be specific, nonoverlapping directories rather than filesystem/home
roots. Parent links, symlinks, Windows junctions, and reparse points are rejected.
Destination paths must stay inside the declared root. Portable component checks
reject traversal, alternate-stream syntax, reserved names, and trailing-dot/space
aliases before Windows normalization. Error and skip are the only conflict
policies; neither permits replacement.

Known history database paths are required to stay outside both roots so the
organizer cannot move its own persistence file. The CLI supplies that location
without opening SQLite. Python callers supplying arbitrary callbacks are
responsible for the callback's own storage location and side effects.

Preview and default duplicate reporting never call the history/index writers,
create an output directory, or initialize SQLite. Existing database content is
preserved. Explicit Python `record_index=True` requires a supplied Database.
Organization no longer updates the duplicate index as an implicit post-file step.

Results retain overall status, filesystem outcome, whether a destination was
created/source removed, file error, history status, and history error. Successful
file changes followed by persistence failure use `completed_with_errors`;
summaries count the completed file operation and separately report history
failure, and CLI exit status is 1. A failed unlink reports a completed copy with
the source retained. Partial writes report a newly created partial destination.
Failed/skipped items do not hide other items' success, and no retry is automatic.

Existing Phase 1 SQLite files receive missing outcome columns using additive,
idempotent initialization. Old records retain their data and receive `unknown`
for outcomes that were not originally captured. A general versioned migration
system and workflow/run history remain Phase 4 work.

The legacy direct adapters now require `destination_root=...`; move/rename/delete
execution additionally requires `confirmed=True`. Every plan, even a delete-only
plan, declares separate roots. Unplanned empty-directory cleanup and interactive
scheduled file organization are explicitly unavailable because they bypass
preview/approval. Their restrictions are documented rather than silently removed.

## Verification actually run

Environment: Windows, Python 3.12.4, pytest 9.1.1. Development tests use the existing
isolated editable `.venv`; the normal wheel was installed in a newly created
`.venv-phase2` without global site-packages. No runtime dependency was added.
The package remains the unreleased baseline version 2.0.1; no release was made.

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=.test-tmp --junitxml=docs\audits\phase2-test-results.xml
```

**82 passed, 1 skipped in 6.50 seconds.** The final suite ran with approval outside
the sandbox so it could create disposable Windows junctions. Both real junction
tests passed: a source-tree junction was rejected, and a destination parent
junction introduced after planning was rejected without writing to its target.
The skipped test requires real file-symlink creation, unavailable to this Windows
account (`WinError 1314`). Source reparse-point replacement is also tested by
injection. No real-file-symlink execution guarantee is claimed from that skipped
case. The earlier sandbox run reported 80 passed and 3 skipped due to link creation
restrictions.

The 83 collected cases include the updated Phase 1 regressions and new tests for:

- Complete read-only preview/reporting against both absent and existing databases.
- Immutable plans, full fingerprints, stale/missing/changed files, and changes
  made after CLI confirmation display or during copy.
- Root overlap, source escape, traversal, invalid templates, nonportable names,
  duplicate targets, existing destinations, and late-created conflicts.
- Error/skip policies, conditions, exact-plan reuse, and destructive confirmation
  before any file mutation or history recording.
- Read/metadata/write/unlink failures, retained partial destinations, mixed batch
  results, successful file changes with failed history, and simultaneous file
  and persistence errors.
- Existing-schema compatibility and persisted filesystem outcome fields.
- Default preview, rejected/declined application, history location protection,
  plugin import regression, module help, and disposable demo.

[JUnit evidence](audits/phase2-test-results.xml) records the final test cases and
skip reason. Initial test failures exposed two implementation issues that were
corrected before the final run: Windows path/fstat creation-time semantics differ
in Python 3.12, and absolute-path normalization can strip trailing dots before
validation. Handle checks now compare identity/size/mtime while path-to-path
checks retain ctime and full content; invalid destination aliases are rejected
before normalization. One CLI assertion was corrected to tolerate terminal line
wrapping without weakening its error-message check.

The normal package was built and installed offline using the already available
runtime dependency wheels:

```powershell
# TEMP and TMP pointed to the existing writable .install-check\tmp directory.
python -m pip wheel --no-deps --no-build-isolation --wheel-dir .install-check\phase2-wheels .
python -m venv --without-pip .venv-phase2
.\.venv\Scripts\python.exe -m pip --python .venv-phase2\Scripts\python.exe install --no-index --find-links .install-check\wheels .install-check\phase2-wheels\taskmaster-2.0.1-py3-none-any.whl
```

**22 installed-package checks passed** from `.install-check/phase2-outside`,
outside the source tree. These covered editable/normal-wheel module help and both
console entry points, all new-module imports resolved from `.venv-phase2`, absence
of optional Pillow/PyPDF2, disposable demo, default preview and duplicates without
database creation, refusal of an unapproved move, missing destination arguments,
approved movement, existing-destination preservation, skip conflicts, traversal
rejection, disabled duplicate deletion, missing source, retained task dispatch
and listing, installed plan-state revalidation, and runtime dependency consistency.
See [commands, outputs, and exit codes](audits/phase2-install-results.json).

## Review and practical limits

The pre-change application/test Python files and selected root docs/metadata are
preserved in [phase2-reference.zip](audits/phase2-reference.zip).
The [source comparison](audits/phase2-source.diff) includes new Python modules and
modified source/tests/docs against that archive. Earlier audit artifacts remain
historical; scheduler/plugin implementations remain unchanged in this phase.
No Git repository/commits or upstream attribution was invented.

Path checks do not eliminate filesystem races. Other processes can replace a
component between validation and an OS operation; this is not a security sandbox
for hostile or actively modified trees. Reading may update access times. Move
and rename use copy-plus-unlink, not an atomic rename, and do not guarantee ACL or
alternate-stream preservation. Partial files/new directories are retained on
failure for inspection; no automatic rollback deletion is attempted. SQLite and
filesystem changes are independent transactions, and history can fail after the
file change. Callbacks and rule conditions are trusted Python; conditions must
avoid side effects.

Planning and apply perform multiple full-content reads, prioritizing correctness
over throughput. Large-tree optimization is unmeasured. The scanner still reads
all selected-tree files and retains the inherited default rule for unmatched
files; project exclusions and developer-specific selections belong to Phase 3.
Scheduling, automatic duplicate deletion, JSON workflows, release CI, dependency
audit/locking, other operating systems/Python versions, and upstream license
verification remain outside the verified Phase 2 scope.

Phase 2 acceptance is met within these limits: plans describe intended operations,
preview has no intentional filesystem/persistence writes, existing destinations
are preserved, and mixed filesystem/history outcomes are reported accurately.
Phase 3 requires separate authorization and has not started.
