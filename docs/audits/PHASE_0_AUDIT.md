# Phase 0 — Baseline verification

Date: 15 October 2026 (Asia/Calcutta)  
Status: complete within the audit scope; application defects remain unfixed.

## Scope and preservation

Read all 11 original Python files, both original READMEs, and the development
plan. Reproduced the key baseline defects without editing application code or
running organization/deletion against user data. File operations and SQLite
probes used disposable fixtures. The two READMEs are byte-identical.

The evidence file records SHA-256 hashes for all 13 original application and
README files. Before/after comparison returned `application_files_unchanged:
true`. The development plan was updated only to link this evidence. Added files
are this report, the verification script, and its JSON output. No Git repository,
virtual environment, dependency installation, or application fix was created.

## Reproduce and inspect

From the project root in PowerShell:

```powershell
python -B docs/audits/verify_phase0.py
```

The completed audit command exited 0 and saved
[`phase0-results.json`](phase0-results.json). That exit code means the audit
finished and source hashes matched; it does **not** mean the application passed
its checks. The script is an evidence collector, not an assertion-based regression
suite. Re-running replaces the JSON and creates/deletes disposable fixtures below
this directory. It does not install dependencies.

Environment: Python 3.12.4, pip 25.0.1, Git 2.46.2.windows.1,
pytest 9.1.1, Rich 13.8.0, setuptools 73.0.1, Pillow 10.4.0.
PyPDF2 is not installed. This is the existing environment, not a verified clean
project installation. No applicable AGENTS.md was found in the workspace or
checked ancestors.

## Executed checks

| Check | Actual result | Follow-up |
| --- | --- | --- |
| Parse all original Python files with `ast.parse` | 9 parsed; CLI fails at line 162 and demo at line 20 with unterminated strings | Phase 1 |
| `python -B -m taskmaster --help` | Exit 1, CLI SyntaxError | Phase 1 |
| `python -B -m pytest --collect-only -q -p no:cacheprovider` | Exit 5, no tests collected | Phase 1 |
| `find_packages()` from existing setup directory | Only `['plugins']`; application package omitted | Phase 1 |
| Import `taskmaster.plugins` | Empty package loaded; no `PluginManager` | Phase 1 |
| Isolated CLI parser method | Shell text `echo phase0` replaces dispatch value `task`; task-add branch is skipped | Phase 1 |
| Two equal-sized files with identical first 1 KB and different final bytes | Default scan reports 1 duplicate group; full-content mode reports 0 | Phase 1 safety fix, Phase 3 replacement |
| Database duplicate query | Count 2 but only one member path returned | Phase 3/4 |
| Copy onto existing disposable destination | Reports success and replaces existing contents | Phase 1 preservation check, Phase 2 policy |
| Unknown action `bogus` | Reports success without performing the requested operation | Phase 1 |
| Scan missing directory | Returns empty list instead of an error | Phase 1 |
| Size destination template | `{size_category}` remains literal | Phase 3 |
| Dry-run organization | Source preserved and destination absent, but 1 history row added | Phase 2 |
| Duplicate scan | Writes 2 index rows for false-positive group | Phase 2/3 |
| Injected metadata PermissionError | Escapes per-file handling | Phase 2 |
| Past schedule with future `next_run` | Returned as due | Deferred scheduler work |
| Task database record | No command persisted | Deferred scheduler work |
| Focused failure handler with SQLite | Failure count increments, persisted error log becomes empty | Phase 4 / scheduler work |
| Focused blocked-dependency execution | Run count and failure count both increment to 1; status returns to PENDING | Deferred scheduler work |
| `Database(':memory:').get_stats()` | OperationalError: no such table: tasks | Persistence refactor |
| `git rev-parse --is-inside-work-tree` | Exit 128: not a Git repository | Establish version control before implementation |

The parser probe extracts only the valid `run_cli` method and supplies an
instrumented parser. It does not import or repair the broken CLI and does not
execute shell commands. The scheduler probes directly complete selected
coroutines that do not suspend, using a real disposable SQLite database. They
do not start watcher tasks, worker threads, or the background service.

## Inspection findings and practical implications

- Both CLI deletion paths use the reported duplicate groups without an additional
  full-content check. The reproduced false-positive grouping can therefore expose
  unique files to deletion once CLI syntax is repaired. No deletion path was run.
- Scheduler restoration is a `pass`, and the CLI supplies no restoration. Task
  serialization omits its callable. Persisted tasks cannot be reconstructed by
  the current implementation.
- The worker can skip items before `task_done()`, and the watcher lacks a queued
  marker. Queue accounting, overlapping work, timeout behavior, and cancellation
  require dedicated tests before scheduler guarantees can be made.
- Organizing an entire project by extension can break source structure. The
  plan's explicit artifact selection and preview/apply design remain appropriate.
- Source/destination boundaries, symlinks/junctions, concurrent file changes,
  conflicts, and post-operation history failures have no coherent policy yet.
- Interactive Python uses `eval()`. Shell execution does not treat nonzero exit
  status as task failure. Logging is configured during scheduler import.
- Monthly recurrence adds 30 days; date templates use current time. These are
  implementation behaviors rather than calendar/file-date guarantees.
- Plugin discovery executes imported Python. It should remain deferred under
  the MVP scope. Optional image/PDF packages are unnecessary for that scope.
- Existing docs overstate reliability, connection pooling, and supported behavior.
  Preserve them as baseline evidence until Phase 1 establishes accurate docs.

These are source-inspection findings where not separately listed as reproduced
above. They are not claims of successful end-to-end execution.

## Provenance and remaining limits

There is no local Git history, verified upstream URL/revision, LICENSE/COPYING
file, or attribution document. Existing README MIT labels and setup metadata do
not establish the missing upstream notices. No copyright holder was invented.
Resolve origin and retain the actual notices before publishing retained code.

No online provenance lookup, dependency vulnerability scan, clean installation,
installed console entry-point check, Windows/Linux comparison, full scheduler
lifecycle test, real permission-denial filesystem test, symlink/junction test, or
performance benchmark was completed. Metadata-denial behavior was simulated.

An initial audit harness run failed while extracting the method, and another
failed because patching argparse's global class caused recursion; both harness
issues were corrected without application edits. The managed Windows default
temporary directory rejected SQLite access and cleanup, so completed probes used
workspace-local temporary fixtures. An event-loop-based harness attempt stalled
and was interrupted; the final audit uses only the bounded synchronous coroutine
paths described above. This does not validate asynchronous scheduling behavior.

## Acceptance and next boundary

Phase 0 acceptance is met: the original inventory is preserved, important defects
have reproducible evidence, provenance gaps and validation limits are explicit,
and the existing phased roadmap bounds the work.

Next is Phase 1, subject to separate authorization: establish version control and
an isolated development environment, repair startup/packaging/dispatch, guard
duplicate safety and destination preservation, add focused regression tests, and
make documentation match verified behavior. No Phase 1 changes were made.
