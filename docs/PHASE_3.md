# Phase 3 — Developer-focused MVP

Date: 15 October 2026 (Asia/Calcutta)

Status: complete; Phase 4 has not started.

This phase adds workspace inspection, size-first verified duplicate reporting,
and explicit artifact selection to the Phase 2 planning/execution contract.
The [README](../README.md) is the authoritative usage guide. No Phase 4 workflow
configuration or expanded run-history system has been implemented.

## Product behavior

| Workflow | Behavior |
| --- | --- |
| `inspect --source ...` | Counts regular files/bytes, final extensions and extension bytes, and largest files with deterministic tie ordering |
| `duplicates --dir ...` | Groups by file size first, hashes only candidate sizes using complete SHA-256, and reports all verified group members |
| `organize --source ... --destination ... --include ...` | Captures and previews selected artifacts; apply uses the same scoped plan with Phase 2 confirmation/revalidation |

All three support readable text and `--format json`, shared exclusions, optional
nonrecursive scanning, and explicit error/exit semantics. Inspect and duplicates
also allow optional include filters. Organization requires include patterns or
an explicit all-files choice. No directory organization selects the entire tree
implicitly, and unmatched rules now produce skips rather than fallback moves.

The shared scanner prunes `.git`, `.venv*`, `venv`, `__pycache__`, `node_modules`,
`.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, and `.nox` by default.
Callers can append exclusions or explicitly disable defaults. Root-relative
patterns, basename patterns, recursive `**`, and trailing-slash directory scopes
have documented case-sensitive semantics on every platform. Excluded entries
are pruned before access/link checks. Include/exclude path traversal is rejected.

Inspection uses metadata rather than opening contents. Extensionless and Unicode
paths work; largest files sort by descending size and relative path. Duplicate
hashing is sequential and uses bounded reads. Unique-size files are not read for
contents. Included access/link/state errors produce an incomplete scan report and
exit 1. Other verified duplicate groups remain visible. Organization refuses an
incomplete scan before execution rather than organizing a misleading subset.

Type, date, and size strategies are available. Size categories are small below
1 MiB, medium from 1 MiB to below 100 MiB, and large from 100 MiB. Date uses
planning time. Default templates preserve relative subdirectories and complete
filenames, including extensionless names. This prevents ordinary nested artifact
names from collapsing onto one destination. Explicit flattening templates still
use the Phase 2 collision checks. New fields are `{size_category}` and
`{relative_dir}`; their behavior and thresholds are documented in the README.

JSON is emitted directly as one unwrapped stdout document, with no Rich markup,
prompts, random result IDs, or runtime report timestamps. Runtime failures after
successful parsing also produce JSON. Usage/required-argument errors remain
argparse stderr output with exit 2. JSON apply requires explicit approval for
moves even when attached to a terminal. Readable CLI output preserves the chosen
encoding and escapes unrepresentable characters instead of crashing on legacy
Windows pipes. JSON's escapes remain lossless when parsed.

History remains lazy: default preview, inspection, and duplicate reports never
initialize SQLite. To support selected artifacts within a project, a history
database may reside inside the project root while remaining outside the selected
files and destination root. Selecting the database or its SQLite sidecars is
rejected. The existing Phase 2 executor/database implementation and its separate
filesystem/history outcome semantics remain unchanged.

## Implementation and provenance

New cohesive modules are `scanning.py`, `inspection.py`, `duplicates.py`, and
`reporting.py`. Existing organizer/planning/CLI adapters use them; operation plans
also capture include/exclude/all-file scope. The old future-per-file duplicate
implementation was replaced by sequential size-group processing. The demo now
inspects and previews/applies copies entirely within its own disposable fixture,
reports duplicates, and removes the fixture without creating a database.

The pre-change source, tests, root docs/metadata, and ignore file are preserved in
[phase3-reference.zip](audits/phase3-reference.zip). The
[source comparison](audits/phase3-source.diff) and
[change manifest](audits/phase3-change-manifest.json) identify changes/new files.
Earlier audit artifacts remain historical. Execution, database, scheduler, and
plugin implementation files were checked against the archive and are unchanged
in this phase. [Attribution](../ATTRIBUTION.md) identifies inherited versus newly
implemented components; upstream licensing/origin remains unresolved.

## Regression evidence

Windows/Python 3.12.4, pytest 9.1.1, existing isolated editable `.venv`:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=.test-tmp --junitxml=docs\audits\phase3-test-results.xml
```

**132 passed, 1 skipped in 20.55 seconds.** The final run used approved execution
outside the sandbox to allow disposable junction fixtures. Both actual junction
tests passed. Real file-symlink fixture creation remains unavailable to this
Windows account (`WinError 1314`), so that single case is explicitly skipped.
[JUnit evidence](audits/phase3-test-results.xml) records all 133 cases.

The tests retain Phase 1/2 safety regressions, updated to explicitly opt into the
former all-file scope where intended. New tests cover:

- Nested fixtures, extensionless/Unicode names, empty files, correct extension and
  byte totals, largest-file ordering, and deterministic reports.
- Basename/root-relative/recursive globs, custom/default exclusions, nonrecursive
  scanning, exclusion pruning, invalid patterns, and no-match selections.
- Size-based candidate counts, proof that unique sizes are never hashed,
  equal-prefix/different-content files, empty duplicate groups, full hashes,
  changed candidates, and read/metadata/directory-access failures.
- Required selection, unmatched-rule skips, selected copy/move application from a
  project containing its own history database, preserved source code/.git data,
  retained directory structure, and exact size boundaries.
- Valid standalone JSON for inspection, duplicates, organization, runtime errors,
  and partial history failure; no prompts in JSON; default read-only behavior.
- Subprocess CLI execution outside the fixture's source root, paths with spaces,
  Unicode names, and readable reports under strict CP1252 stdout for all workflows.

An installed-wheel test exposed the CP1252 issue after the initial 129-pass run:
readable inspection crashed on Chinese filenames. The failure was reproduced,
CLI stream error handling was corrected without changing the caller's encoding,
and three subprocess regressions were added. The final results above include that
fix. The failed install check was not counted as successful verification.

## Package verification

A normal wheel was built with the existing setuptools and installed with cached
runtime wheels in a new `.venv-phase3` without global site-packages:

```powershell
# TEMP and TMP pointed to the writable .install-check\tmp directory.
python -m pip wheel --no-deps --no-build-isolation --wheel-dir .install-check\phase3-wheels .
python -m venv --without-pip .venv-phase3
.\.venv\Scripts\python.exe -m pip --python .venv-phase3\Scripts\python.exe install --no-index --find-links .install-check\wheels .install-check\phase3-wheels\taskmaster-2.0.1-py3-none-any.whl
python -B docs/audits/verify_phase3_install.py
```

The wheel was rebuilt and force-reinstalled after the encoding correction. The
unreleased baseline package version remains 2.0.1; no release or dependency change
was made. The verification script creates a fresh fixture under `.install-check`
for every run and removes `PYTHONPATH` from child processes. It preserves fixture
data for inspection and writes its evidence/sample reports in `docs/audits`.
Final installed-check results are recorded in
[phase3-install-results.json](audits/phase3-install-results.json).

**All 30 installed-package checks passed** outside the source tree: editable and
normal-wheel help/entry points, new-module imports, full disposable demo,
readable/JSON inspection and duplicates, deterministic repeated JSON, exclusion
options, selected preview/copy/move, mandatory approval and selections,
organization with existing project-local history, protected history-file
selection, no-match/size/traversal/missing-root behavior, disabled deletion,
retained task registration/listing, and dependency consistency.

Example report artifacts:

- [Inspection JSON](audits/phase3-sample-inspection.json)
- [Duplicate JSON](audits/phase3-sample-duplicates.json)
- [Organization preview JSON](audits/phase3-sample-organization.json)

These describe the fixture at reporting time; later application intentionally
moves its selected logs/reports. They are report examples, not saved executable
workflow/plan files.

## Limits and phase boundary

Scans are not atomic snapshots of changing trees; candidate metadata/state is
checked around hashing, but later changes remain possible. Counts are for
successfully inspected files. Duplicate byte totals are logical redundant bytes,
not guaranteed filesystem savings. Large-tree throughput/memory use is unmeasured;
the first implementation favors sequential correctness over concurrency.

Phase 2 race/transaction limits still apply: path validation is not an OS sandbox,
copy-plus-unlink is not atomic, ACL/alternate-stream preservation is not promised,
and file/history changes are separate transactions. Partial outputs are retained
for inspection; there is no automatic rollback or retry. Rule conditions and
history callbacks are trusted Python. Actual permission failures are mostly
tested by injection, apart from the real Windows link/junction checks described.

Automatic duplicate deletion remains unavailable. Reliable scheduling, dynamic
plugins, image/PDF processing, validated JSON workflows, expanded run history,
release CI, dependency audit/locking, broader platform coverage, and upstream
license verification remain outside this phase. JSON output reports do not
implement the Phase 4 JSON workflow configuration system.

All three MVP workflows have fixture-based evidence, invalid inputs fail usefully,
selected organization preserves unrelated source files, and reported duplicates
are full-content verified. Phase 4 has not started and requires separate approval.
