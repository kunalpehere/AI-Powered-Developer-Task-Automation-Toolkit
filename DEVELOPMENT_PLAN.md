# Developer Task Automation Toolkit — Development Plan

Date: 15 October 2026  
Status: Phases 0–6 implemented locally. Hosted CI and upstream provenance acceptance remain pending release gates.

## 1. Purpose and engineering goals

Develop an original, reliable Python CLI that helps developers inspect a workspace, identify duplicate files, and safely organize selected development artifacts through reusable workflows.

The project should demonstrate the skills relevant to a Python Development internship at 404Minds Technologies:

- Python functions, collections, modules, type hints, and appropriate object-oriented design.
- Maintainable automation with clear validation and error handling.
- Debugging based on reproduced failures rather than speculative changes.
- Unit and integration testing, including invalid inputs and partial failures.
- Thoughtful AI-assisted development with human understanding and review.
- Clear documentation, attribution, and small, reviewable changes.

The existing TaskMaster snapshot is a reference implementation, not a specification. Preserve useful ideas and code where justified, while making substantive improvements to correctness, safety, and product focus.

## 2. Audit baseline

All 13 supplied files were inspected, including every Python module and both READMEs. No repository files were changed during the audit; the file inventory and SHA-256 hashes matched before and after it.

### Current application

The source attempts to combine:

- An asynchronous task scheduler with priorities, dependencies, recurrence, retries, callbacks, and SQLite records.
- A file organizer with extension categories, destination templates, move/copy/rename/delete operations, duplicate detection, and history.
- A Rich terminal interface and a plugin prototype.

There is no AI integration, validated workflow configuration system, or developer-project inspection feature. The application cannot currently start through its CLI.

### Architecture inventory

| Existing file | Responsibility | Assessment |
| --- | --- | --- |
| `taskmaster/models.py` | Task, rule, and operation dataclasses; enums; recurrence | Useful foundation with insufficient validation |
| `taskmaster/database.py` | SQLite records, history, and checksum index | Useful concepts with persistence defects |
| `taskmaster/scheduler.py` | Watcher, priority queue, workers, retries, callbacks | Prototype requiring substantial correctness work |
| `taskmaster/organizer.py` | Scanning, templates, file operations, duplicate grouping | Reusable functions mixed with unsafe execution policies |
| `taskmaster/cli.py` | Interactive interface and argparse commands | Syntax and dispatch blockers |
| `taskmaster/plugins.py` | Plugin interfaces, loading, image/PDF processors | Hidden by the identically named package |
| `taskmaster/plugins/__init__.py` | Empty package | Shadows `plugins.py` |
| `taskmaster/demo.py` | Feature demonstration | Invalid syntax and environment assumptions |
| `taskmaster/setup.py` | Dependencies and console entry points | Incorrect package discovery |
| `taskmaster/__main__.py` | Module entry point | Imports the broken CLI |
| `taskmaster/__init__.py` | Package initialization | Empty |
| `README.md`, `taskmaster/README.md` | Identical documentation | Claims exceed verified behavior |

### Checks actually run

| Check | Result |
| --- | --- |
| Parse all 11 Python files | Nine parsed; `cli.py` and `demo.py` failed |
| `python -B -m taskmaster --help` | Failed with `SyntaxError` |
| `python -B -m pytest --collect-only -q -p no:cacheprovider` | No tests collected |
| Package discovery from the setup directory | Found only `plugins`, not `taskmaster` |
| Import `taskmaster.plugins` | Loaded the empty package without `PluginManager` |
| Disposable file/database probes | Reproduced the defects listed below |
| Isolated unchanged CLI parser method | Reproduced the command argument collision |
| Git status from workspace root and nested package | Both reported that the location is not a Git repository |

The observed environment contained Python 3.12.4, Rich 13.8.0, pytest 9.1.1, setuptools 73.0.1, and Pillow 10.4.0. PyPDF2 was absent. This was not a verified clean installation of the project.

Broader asynchronous probes stalled and were interrupted. End-to-end scheduler, timeout, and shutdown behavior was not successfully validated. Focused scheduler checks used mock persistence and directly completed coroutines without starting the background service. No dependency vulnerability scan was completed.

### Confirmed defects and implementation weaknesses

1. **CLI and demo syntax errors:** invalid multiline quoted strings prevent execution. The first failures are at `cli.py:162` and `demo.py:20`.
2. **Broken package discovery:** `setup.py` is inside the application package; its `find_packages()` invocation omits the application targeted by the console entry points.
3. **Plugin import collision:** `plugins/` shadows `plugins.py`, so demonstrated imports cannot access `PluginManager`.
4. **CLI dispatch collision:** both the subparser destination and shell-command option use `command`; the shell text replaces the value used to dispatch `task add`.
5. **False duplicate matches:** default detection groups files by size and the first 1 KB. Files with different remaining contents were grouped together. Deletion uses these groups without full-content verification.
6. **Silent overwrite:** existing destinations have no explicit conflict policy. A disposable copy probe overwrote existing contents and reported success.
7. **Incomplete size strategy:** `{size_category}` is not expanded, and the interactive size helper is unused.
8. **Invalid actions report success:** an unknown rule action performs no operation but receives a success result.
9. **Errors escape per-file handling:** metadata lookup and template expansion occur outside the operation exception handler. A simulated permission failure escaped it.
10. **Missing sources appear empty:** a nonexistent directory returns an empty scan rather than a useful error.
11. **Dry run writes state:** file contents remain intact, but preview writes operation history; duplicate scans also update the index.
12. **Wrong due-time field:** the database queries `schedule_time`, while recurrence and retries update `next_run`. A future `next_run` does not prevent a task from being returned as due.
13. **Tasks cannot resume after restart:** commands are not persisted, and restoration is left as `pass`; the CLI does not supply the missing restoration.
14. **Failure logs are erased:** an error is written to SQLite and then overwritten by saving a task whose in-memory error list was not updated.
15. **Dependencies consume retries:** dependency checks occur after execution counters and status are changed, treating blocked work as failure rather than waiting.
16. **In-memory database fails:** each operation opens a separate connection, losing the schema created by the initial `:memory:` connection.
17. **Incomplete database duplicate groups:** grouping by checksum selects one path and a count, not every member of the group.

Additional inspection findings:

- No tests, coverage configuration, CI, dependency lock, migration system, or configuration schema.
- No Git metadata or applicable `AGENTS.md` found in the checked workspace/ancestor locations.
- SQLite connections are opened and closed per operation; the documentation's connection-pooling claim is inaccurate.
- Date organization uses the current date; monthly recurrence is a 30-day approximation.
- Input validation is inconsistent for actions, intervals, callables, and numeric values.
- Shell command execution ignores nonzero return codes and stderr when determining success.
- Interactive Python input uses unrestricted `eval()`.
- Logging configuration occurs at import time; other modules print or suppress exceptions.
- Some type annotations use builtin `any` rather than `typing.Any`.
- Progress is displayed after organization finishes, with an artificial delay.
- Interactive operations retain mutable rules and dry-run state.
- The demo contains a hard-coded `/mnt/agents/output` path.

### Potential risks requiring dedicated validation

These are distinct from reproduced runtime defects:

- Arbitrary destination paths, symlinks, junctions, protected directories, and output trees inside input trees lack a defined policy.
- A synchronous thread can outlive a timeout; retrying side-effecting work may overlap execution.
- Pending tasks can be queued repeatedly, and some skipped items bypass queue completion accounting.
- A filesystem change may succeed before hashing, indexing, or history recording fails.
- Indexes can become stale and mix quick fingerprints with full checksums.
- Large scans materialize every path and submit a future per file; indexing uses many small transactions.
- Plugin discovery executes imported Python with process privileges.
- Broad dependency minimums and the absence of a reproducible baseline complicate dependency assurance.

## 3. Product direction and MVP scope

**User problem:** developers need a predictable way to inspect workspace clutter and maintain selected artifacts without accidentally moving source files or deleting unique content.

**Execution model:** plan → validate → preview → apply → report.

The first useful release should offer:

1. **Project inspection:** file counts, extension distribution, large files, and configurable exclusions such as `.git` and virtual environments.
2. **Verified duplicate reporting:** size grouping followed by full SHA-256 hashing. Initially report duplicates without deleting them.
3. **Safe artifact organization:** operate on explicitly selected logs, build outputs, or exported reports with an explicit destination root.
4. **Validated JSON workflows:** compose a short sequence of supported named operations.
5. **Execution reporting and history:** record successes, skips, failures, and actionable reasons.

Do not sort an entire source tree by file type by default: that can break imports and build configuration.

The original engineering contribution should be the developer-specific scope, consistent execution contracts, safety policies, validation, and evidence from tests. Renaming the project or adding an AI call is not sufficient.

### Deferred scope

- Background scheduling and automatic retries.
- Dynamic plugin discovery and image/PDF processing.
- Web dashboards, external databases, paid APIs, and task brokers.
- AI explanations until structured errors exist and a clear use case is demonstrated.
- Automatic duplicate deletion until a separately reviewed safety design is justified.

## 4. Component disposition

| Decision | Components | Rationale |
| --- | --- | --- |
| Retain and test | Extension categories, chunked file reading, useful pathlib code | Small, understandable building blocks |
| Refactor | Rules, operation results, summaries, and history | Useful concepts need explicit validation and contracts |
| Refactor | CLI presentation | Separate parsing, execution, and output rendering |
| Replace | Duplicate verification | Prefix checks may select candidates but must not authorize deletion |
| Replace | Destination handling | Require root boundaries, conflict policies, planning, and revalidation |
| Replace | Persisted callable tasks | Use named operations with serializable validated parameters |
| Defer | Scheduler and dynamic plugins | High correctness cost without first-release value |
| Remove after replacement | `eval()`, artificial delays, environment-specific demo path, duplicate documentation | Unsafe or misleading behavior without product value |

Do not silently remove existing features. Document their status, replacement rationale, and provenance; preserve reference history once Git and upstream provenance are established.

## 5. Phased implementation roadmap

Each phase requires focused review and validation before the next begins. Proposed module names below are design suggestions, not a requirement to create unnecessary abstractions.

### Phase 0 — Repository audit and baseline verification

- **Status:** completed with the limitations stated above; independently reverified on 15 October 2026. See [Phase 0 audit report](docs/audits/PHASE_0_AUDIT.md), [recorded results and source hashes](docs/audits/phase0-results.json), and [repeatable verification script](docs/audits/verify_phase0.py).
- **Objective:** establish actual behavior, structure, defects, and provenance gaps.
- **Files inspected:** all supplied Python, packaging, and documentation files.
- **Changes:** none during the audit. This plan is saved separately at the user's request.
- **Validation:** parsing, CLI startup, test collection, package discovery, import resolution, focused probes, and source hashes.
- **Dependencies and risks:** incomplete asynchronous verification; no Git history or verified upstream license text.
- **Learning/interview topic:** explain the difference between advertised behavior, inspected behavior, and reproduced evidence.
- **Acceptance criteria:** actionable audit findings and a bounded roadmap exist without implementation changes.

### Phase 1 — Establish a runnable, safe baseline

**Status:** completed on 15 October 2026. See the [implementation and verification record](docs/PHASE_1.md): 30 regression tests passed, isolated editable and normal-wheel installation verified, and 17 installed-package checks passed. Later phases have not started.

**Objective:** make installation and basic CLI use reliable before adding capabilities.

**Existing files affected:** `cli.py`, `setup.py`, `demo.py`, `plugins.py`/`plugins/`, `organizer.py`, and installation documentation.

**Problems addressed:** syntax failures, package discovery, plugin naming, command dispatch, unverified duplicate deletion, invalid actions, and missing-source handling.

**Proposed changes:**

- Correct malformed strings and distinguish the subcommand name from shell-command text.
- Establish root-level packaging and working console/module entry points.
- Resolve the plugin import collision without claiming plugin support beyond what is tested.
- Prevent deletion based on partial fingerprints.
- Validate actions and source directories, with useful messages and nonzero error exits.
- Repair the demonstration or clearly limit it to verified behavior.
- Keep scheduler limitations explicit; do not advertise persistence/restoration as working.

**Proposed additions/removals:** root `pyproject.toml`, focused `tests/`, development dependencies, and one authoritative README. Retire obsolete packaging/documentation only after replacements work.

**Tests:** clean-environment installation, module/console `--help`, parser dispatch, identical-prefix/different-content files, invalid sources/actions, and preservation of existing destinations.

**Dependencies, risks, and outcome:** no AI dependency; packaging changes require import and installed-entry-point verification. Outcome is a runnable baseline with critical safety regressions guarded.

**Learning/interview topics:** package discovery, import resolution, argparse destinations, regression tests, and exit codes.

**Acceptance criteria:**

- A clean environment can install the package and run its help commands.
- Focused regression tests pass, including the critical duplicate-safety test.
- Invalid input produces actionable errors.
- Documentation accurately states which features remain unreliable or unavailable.

### Phase 2 — Separate planning from filesystem execution

**Status:** completed on 15 October 2026. See the [Phase 2 implementation record](docs/PHASE_2.md): immutable plans, read-only preview/reporting, scoped validation, confirmation, revalidation, and separate filesystem/history outcomes. Final regression run: 82 passed, 1 skipped because this Windows account cannot create file symlinks; actual junction tests passed. Phase 3 has not started.

**Objective:** make changes inspectable and testable before touching files.

**Existing files affected:** `models.py`, `organizer.py`, CLI integration, and persistence boundaries.

**Problems addressed:** mixed responsibilities, silent overwrites, arbitrary destinations, weak validation, preview side effects, and ambiguous partial failures.

**Proposed design:**

- Explicit operation-plan and result dataclasses.
- Separate scanning/planning, validation, execution, and presentation.
- Validate root boundaries, actions, template placeholders, and conflict policies.
- Preview does not alter files or history by default; any intentional preview recording must be explicit.
- Require explicit confirmation before applying destructive changes.
- Revalidate relevant file state immediately before applying a plan.
- Represent file-change success separately from a subsequent history-recording failure.

**Proposed additions:** `planning.py`, `execution.py`, and `errors.py`; extract scanning helpers only where that improves clarity.

**Tests:** destination conflicts, traversal, missing and changed files, permission failures, symlink/junction policy where supported, and batches containing successful and failed items.

**Dependencies, risks, and outcome:** standard library only. Path validation does not eliminate all concurrent filesystem races; document the practical guarantees. Outcome is a coherent preview/apply contract.

**Learning/interview topics:** dataclasses, explicit exceptions, dependency injection, filesystem semantics, and partial failure.

**Acceptance criteria:**

- Plans fully describe intended operations before execution.
- Preview leaves files and default history unchanged.
- Existing destinations are preserved unless an explicit documented policy permits replacement.
- Mixed results are reported accurately, including failures after a filesystem change.

### Phase 3 — Deliver the developer-focused MVP

**Status:** completed on 15 October 2026. See the [Phase 3 implementation record](docs/PHASE_3.md): project inspection, configurable exclusions, sequential size-first/full-SHA duplicate reporting, explicit artifact selection, size sorting, and readable/JSON reports. Final validation: 132 regression tests passed, 1 skipped for unavailable Windows file-symlink privileges, and 30 installed-package checks passed. Actual junction checks passed. These are the Phase 3 completion results.

**Objective:** complete project inspection, verified duplicate reporting, and safe artifact organization.

**Existing files affected:** scanner/checksum functions, CLI commands, planning, and execution.

**Problems addressed:** lack of developer-specific value, incomplete organization strategies, unverified duplicate groups, and unclear scan scope.

**Proposed features and files:**

- Project inspection with configurable exclusions and deterministic summaries.
- Size-based candidate selection followed by full SHA-256 duplicate verification.
- Explicit source selections and destination roots for artifact organization.
- Human-readable and machine-readable reports.
- Add focused modules such as `inspection.py` or `duplicates.py` when they represent cohesive responsibilities.
- Remove unsupported template strategies or implement and document their exact behavior.

**Tests:** nested trees, empty files, identical files, differing contents, extensionless and Unicode names, exclusions, unreadable files, and end-to-end CLI fixtures.

**Dependencies, risks, and outcome:** no additional runtime dependency required. Start sequentially; measure before adding concurrency. Outcome is a small usable product rather than a broad prototype.

**Learning/interview topics:** collections, generators, hashing, algorithmic cost, deterministic output, and integration tests.

**Acceptance criteria:** all three workflows work on fixture projects; invalid inputs produce actionable errors; source trees are not changed unexpectedly; duplicate reporting verifies full content.

### Phase 4 — Validated workflows and execution history

**Status:** completed on 15 October 2026. See the [Phase 4 implementation record](docs/PHASE_4.md): version-1 validated JSON workflows, shared named-operation validation, stop/continue policies, structured diagnostics, UUID run/step/file associations, versioned SQLite migration, read-only history, and tracked direct/interactive organization. Final regression validation: 195 passed, 1 skipped for unavailable Windows file-symlink privileges; actual junction checks passed. Fresh wheel verification is recorded in `docs/audits/phase4-install-results.json`. Phase 5 has not started.

**Objective:** make supported operations reusable and auditable.

**Existing files affected:** CLI, models, executor, database, and reporting.

**Problems addressed:** nonserializable callable tasks, lack of configuration validation, inconsistent logging, and incomplete execution history.

**Proposed additions/design:**

- `config.py` and `workflows.py` with versioned JSON configuration.
- A small registry of named operations with validated parameters; no `eval()` or arbitrary dynamic imports.
- Unique run identifiers, structured diagnostic fields, and SQLite history.
- Explicit stop-on-failure versus continue-on-failure policy.
- Versioned database initialization/migrations as needed by real schema changes.
- Define operation result and exit-code semantics consistently across CLI and workflows.

**Tests:** malformed JSON, unsupported versions, unknown operations, wrong field types, configuration round trips, mixed-success runs, and history-write failures.

**Dependencies, risks, and outcome:** use `json`, `logging`, and `sqlite3`. File operations and database transactions are not one atomic transaction; report that boundary accurately. Outcome is reproducible workflow execution with trustworthy records.

**Learning/interview topics:** serialization, validation boundaries, registries, transaction semantics, and reproducibility.

**Acceptance criteria:** saved workflows use the same validation as direct commands; reports, history, and exit codes reflect actual outcomes; errors retain sufficient context without exposing secrets.

### Phase 5 — Documentation, testing, and release readiness

**Status:** local implementation completed on 15 October 2026. See the [Phase 5 record](docs/PHASE_5.md): hashed runtime/development baselines, Windows/Linux CI configuration, branch/subprocess coverage, advisory audits, distribution/fresh-install checks, design/platform notes and feature evidence. The local suite passes 195 tests with one Windows file-symlink privilege skip. Known-advisory checks found no vulnerabilities in 4 runtime / 43 development pins. Hosted matrix execution and upstream license/copyright verification remain release acceptance gates; this candidate has not been published. Optional Phase 6 has not started.

**Objective:** produce a reproducible portfolio release that can be explained and demonstrated.

**Existing files affected:** tests, packaging, READMEs, examples, and provenance documentation.

**Proposed additions:** Windows/Linux CI, coverage reporting, dependency auditing, reproducible development setup, a safe demo, and concise design notes. Add attribution/license files once provenance is verified.

**Problems addressed:** unverified feature claims, absent release checks, platform differences, dependency uncertainty, and incomplete attribution.

**Tests and validation:** clean installation, installed-package imports, every documented command, invalid inputs, representative permission failures, collision preservation, partial failures, and report accuracy. Coverage must include important failure paths rather than only chase a percentage.

**Dependencies, risks, and outcome:** development tools only unless a concrete runtime need emerges. Document filesystem behavior that differs across platforms. Outcome is a defensible, demonstrable release.

**Learning/interview topics:** CI, packaging, dependency maintenance, test quality, documentation, and engineering tradeoffs.

**Acceptance criteria:**

- A fresh checkout can be installed, tested, and demonstrated from the README.
- CI passes on the declared platforms and Python versions.
- Every advertised feature has validation evidence.
- Dependency review and attribution are complete, with unresolved limitations documented.
- The author can explain inherited versus newly designed components.

### Optional Phase 6 — Scheduling only when justified

**Status:** implemented locally on 15 October 2026 for the user's selected project-review workflows. See [Phase 6](docs/PHASE_6.md): persisted named workflow snapshots, UTC recurrence/next-run scheduling, explicit retry budgets, dependency/cycle checks, one owner/worker, isolated subprocess attempts, timeout/cancel/shutdown tree cleanup, and interrupted-run review. Legacy rows are preserved without inventing lost callables. Hosted Linux/newer-Python results remain pending.

**Entry condition:** a useful recurring developer workflow exists that cannot be adequately served by invoking the CLI through an existing scheduler.

**Affected files:** `scheduler.py`, task models, database persistence, workflow integration, and scheduler tests.

**Required design changes:** persist named operations and parameters; use `next_run`; restore saved tasks; define retry counts, idempotency, dependency cycles, timezone behavior, cancellation, and subprocess termination. Prevent duplicate dispatch and define crash recovery.

**Tests:** recurrence boundaries, future due times, retry delays, restart recovery, blocked/cyclic dependencies, timeout behavior, shutdown, and repeated/overlapping side effects.

**Dependencies and risks:** prefer a simple execution model; add a scheduling dependency only after comparing it with maintaining custom scheduling. Scheduling increases concurrency and recovery complexity.

**Learning/interview topics:** state machines, idempotency, concurrency, time, cancellation, and recovery.

**Acceptance criteria:** a justified recurring workflow survives restart and behaves predictably under failure; all declared scheduling guarantees have tests. This phase is not required for the first release.

## 6. Recommended technology stack

| Area | Recommendation | Rationale |
| --- | --- | --- |
| Python | Python 3.12+ with maintained patch releases and an explicitly tested range | Modern standard library and typing without preserving an unnecessary 3.8 baseline |
| CLI | `argparse` | Adequate for the product; avoid a framework migration |
| Terminal output | Rich, if useful | Retain existing presentation value outside core logic |
| Filesystem | `pathlib` and explicit plans | Readable paths and testable decisions |
| Hashing | `hashlib.sha256` after size grouping | Full-content verification with bounded reads |
| Configuration | JSON and explicit validation | Standard library, inspectable, serializable |
| History | SQLite in Phase 4 | Local persistence without a service |
| Testing | pytest, `tmp_path`, mocks, pytest-cov | Unit, integration, and failure-scenario verification |
| Development | Ruff, a reproducible dependency baseline, pip-audit | Consistency and dependency checks |
| Packaging | Root `pyproject.toml` and setuptools | Correct installation and metadata |

Existing declarations are `rich>=13.0.0`, optional `Pillow>=9.0.0`, and optional `PyPDF2>=3.0.0`. They are not a reproducible tested environment. Do not install optional image/PDF dependencies for the proposed MVP.

Python 3.8 is end-of-life. Use the official lifecycle when choosing supported versions: [Python version status](https://devguide.python.org/versions/).

PyPDF2 is deprecated according to its documentation. If PDF processing later becomes necessary, assess the maintained `pypdf` project rather than carrying the obsolete optional dependency forward: [PyPDF2 documentation](https://pypdf2.readthedocs.io/en/3.x/index.html).

## 7. License and attribution plan

The READMEs say MIT and setup metadata includes an MIT classifier, but the snapshot has no actual LICENSE file, upstream URL, copyright notice, or Git history. The author field is a placeholder. Provenance is unresolved.

Before publishing a derivative:

1. Identify the upstream repository and exact revision where possible.
2. Obtain and preserve the actual license and copyright notices.
3. Record inherited, adapted, replaced, and newly written components in a provenance document, such as `ATTRIBUTION.md`.
4. Credit retained or adapted implementation and describe the derivative relationship honestly.
5. Preserve reference history when establishing Git; do not rewrite inherited code as an entirely original contribution.

Do not invent a copyright holder or rely solely on an MIT label in a README as the complete provenance record. Resolve reuse terms before distributing copied implementation.

## 8. AI-assisted implementation and review process

For every approved implementation phase:

1. Explain the specific problem and its evidence before changing code.
2. Explain why the selected design fits the small product.
3. Identify the Python concepts the developer should understand.
4. Define important edge cases and meaningful tests.
5. Make focused changes without unrelated refactoring or overwriting user work.
6. Run the relevant checks and record exact commands/results.
7. Review the diff and explain how to verify locally.
8. Update documentation to reflect verified behavior.
9. Stop at the phase boundary for review; do not implement the entire roadmap at once.

Use Codex and Antigravity as development/review aids. The developer should be able to explain the control flow, safety policies, failure handling, and tests without relying on generated descriptions.

For reported errors, reproduce and investigate the root cause first. Never label a test as passed unless it was actually run.

## 9. Recommended next action

Review the [Phase 6 implementation and evidence](docs/PHASE_6.md). Before publishing, connect a repository and obtain actual passing hosted matrix results, identify the exact upstream source/revision and preserve its actual license/copyright notices. No further implementation phase is authorized by this document alone.

Saving or updating this document does not authorize implementation of subsequent phases.
