# TaskMaster usage guide

Inspect a developer workspace, report fully verified duplicate files, and
organize explicitly selected artifacts through plan → preview → apply → report.
Validated JSON workflows and structured run history compose these MVP operations.
Phase 5 adds pinned setup, CI, coverage, dependency audits and package checks.
Phase 6 adds durable scheduling for saved project-review workflows.
This is a development candidate; hosted CI and upstream reuse terms remain
release gates.

## Install and verify

Requires Python 3.12+. Run from the repository root containing `pyproject.toml`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements/dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check taskmaster tests scripts
.\.venv\Scripts\python.exe -m pytest -q --cov --cov-report=term-missing --cov-report=xml:reports/coverage.xml
.\.venv\Scripts\taskmaster.exe --help
.\.venv\Scripts\python.exe -m taskmaster.demo --directory .
```

`tm` is an equivalent console entry point; `python -m taskmaster` also works.
On Linux/macOS use `.venv/bin/python`, `.venv/bin/taskmaster`, and `.venv/bin/tm`.
Local validation covers Windows/Python 3.12.4. The CI target matrix is Windows
and Ubuntu on Python 3.12–3.14; passing hosted results are still pending. Rich is
the only direct runtime dependency; the hashed development baseline adds tests,
coverage, lint, audit and build tools. No service, API key, Pillow, or PDF package
is needed. For runtime-only use, install `requirements/runtime.txt` with
`--require-hashes`, then install a built local wheel with `--no-deps`.
Managed Windows hosts may need TEMP/TMP to point to an existing writable directory
before venv/pip/build. For example:

```powershell
New-Item -ItemType Directory -Force .install-check\tmp | Out-Null
$env:TEMP = (Resolve-Path .install-check\tmp).Path
$env:TMP = $env:TEMP
```

The first development install needs network access to PyPI. Lockfiles record
the tested dependency versions/hashes; `.[dev]` alone is a convenience install
with ranges. See [dependency setup](../requirements/README.md),
[release checks](../docs/RELEASE.md), [design notes](../docs/DESIGN.md), and
[platform limits](../docs/PLATFORMS.md). Full build/clean-install/audit commands are
in the release guide.

The demo creates its own temporary child directory, inspects sample logs,
previews/applies disposable copies, reports duplicates, and removes its fixtures.
It never runs the scheduler, initializes SQLite, or modifies existing files.

## Inspect a workspace

```powershell
.\.venv\Scripts\tm.exe inspect --source . --top 10
.\.venv\Scripts\tm.exe inspect --source . --min-size 1048576 --exclude "build/" --format json
```

Reports file count, total bytes, final-extension counts/bytes, and the largest
files. Extensions are lowercased; extensionless files use an empty extension in
JSON and `(no extension)` in text. Largest files sort by descending bytes and then
root-relative path. `--top` defaults to 10; `--min-size` filters that listing, not
the totals. Both accept nonnegative integers, and `--top 0` omits the listing.

Inspection reads metadata, not file contents. Errors are visible: incomplete scans
return exit 1 and `complete: false`; counts cover successfully inspected files.

## Report duplicates

```powershell
.\.venv\Scripts\tm.exe duplicates --dir . --exclude "reports/private/"
.\.venv\Scripts\tm.exe duplicates --dir . --format json
```

Files are grouped by size first. Only sizes with multiple files receive a complete
SHA-256 hash, using bounded reads and sequential processing. Empty files are
supported. Every reported group includes all its verified members and their size.
Reports expose candidate/hashed counts so the size filter can be checked. Groups
sort by descending size and SHA-256; member paths are sorted. `redundant_bytes`
measures logical duplicate content, not guaranteed disk savings (hard links,
compression, and filesystem allocation can differ).

Metadata is checked around hashing to detect changed candidates. Read errors
produce an incomplete report and exit 1 while retaining other verified groups.
Unique-size files are not read for content, so their content-read permissions are
not tested. No scan is an atomic snapshot of a concurrently changing tree.

Duplicate reporting creates no database and changes no index. Automatic deletion
remains disabled; `duplicates --delete` exits 2 and deletes nothing.

## Organize selected artifacts

Directory organization requires a repeatable `--include` pattern or an explicit
`--all-files`. It never chooses the entire tree implicitly. Include logs, exported
reports, or build artifacts rather than selecting source files unintentionally.
Source and destination roots must be separate and nonoverlapping.

```powershell
# Preview selected logs inside a project; no filesystem/history writes.
.\.venv\Scripts\tm.exe organize --source . --destination ..\organized --include "logs/**/*.log"

# Apply that scope as moves with explicit approval.
.\.venv\Scripts\tm.exe organize --source . --destination ..\organized --include "logs/**/*.log" --apply --yes

# Select multiple artifact sets and copy them, preserving sources.
.\.venv\Scripts\tm.exe organize --source . --destination ..\exports --include "reports/**/*.csv" --include "reports/**/*.json" --action copy --apply --format json

# Size sorting of a deliberately selected artifact folder.
.\.venv\Scripts\tm.exe organize --source .\artifacts --destination ..\sorted-artifacts --all-files --strategy size
```

Preview is the default; `--dry-run` explicitly selects it. `--apply` performs the
captured plan. Moves need `--yes` in noninteractive or JSON mode; in a text
terminal the command can prompt after displaying the plan. Refusing approval
changes no files/history. Copies require `--apply` but not destructive approval.
`--yes` requires `--apply`; `--dry-run` and `--apply` are mutually exclusive.
An independently rerun CLI command builds a new plan. The Python API can retain
one exact plan between preview and apply; saved plan files are not implemented.

Strategies are `type`, `date`, and `size`. Date uses the date when planning, not
file modification dates. Size categories are **small < 1 MiB**, **medium from
1 MiB to less than 100 MiB**, and **large ≥ 100 MiB** (binary units). Default
strategies preserve root-relative subdirectories and complete filenames under
the selected category/date/size. For example, `logs/archive/app.log` becomes
`misc/logs/archive/app.log` under type sorting. Same-named files in separate
subdirectories remain separate by default.

`--template` overrides the strategy. Supported fields are `{filename}`, `{name}`
(stem), `{ext}`, `{type}`, `{mime}`, `{date}`, `{year}`, `{month}`, `{day}`,
`{size_category}`, and `{relative_dir}` (empty at the source root). Unknown fields,
attribute/index lookups, format specifications, conversions, traversal, reserved
names, and nonportable destination components are rejected. An explicit template
can flatten paths, but collisions fail rather than overwrite. `--conflict error`
is the default; `--conflict skip` reports conflicts without changing them.

## Scope and exclusions

All three commands share:

- `--exclude PATTERN`, repeatable; appended to the defaults.
- `--no-default-excludes`, to use only explicit exclusions.
- `--no-recursive`, to scan immediate files only.
- `--format text|json`, defaulting to readable text.

Default directory/file-name exclusions are `.git`, `.venv*`, `venv`,
`__pycache__`, `node_modules`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`,
and `.nox`. Excluded directories are pruned before access/link checks. Exclusion
counts represent encountered/pruned entries, not every descendant inside them.
Inspect/duplicates also accept optional repeated `--include` filters.

Patterns without a slash match a basename at any depth (`*.log`). Patterns with
slashes match from the scan root: `reports/*.csv` selects direct CSV children;
`reports/**/*.csv` includes direct and nested CSV files. `**` spans zero or more
directory segments; `*` within a path segment never crosses a slash. A trailing
slash means the subtree (`build/` means `build/**`). Backslashes are accepted as
separators. Matching is case-sensitive on all platforms. Absolute paths, empty
patterns, and traversal are invalid. Quote globs in the shell so TaskMaster
receives the pattern itself.

Inspection/duplicate scans report included links, reparse points, or unreadable
paths as errors. Organization refuses incomplete scans before making a plan for
execution. A selection matching no files after exclusions returns an actionable
error; an explicitly selected empty tree via `--all-files` is a valid empty plan.

## Python API

```python
from pathlib import Path
from taskmaster.inspection import inspect_project
from taskmaster.duplicates import duplicate_report
from taskmaster.models import FileRule
from taskmaster.organizer import FileOrganizer

print(inspect_project(Path("project"), exclusions=("build/",)))
print(duplicate_report(Path("project")))
organizer = FileOrganizer()  # No database initialized.
try:
    organizer.add_rule(FileRule("logs", "*.log", "logs/{relative_dir}/{filename}", action="move"))
    plan = organizer.plan_directory(Path("project"), Path("organized"), includes=("logs/**/*.log",))
    for item in organizer.preview(plan):
        print(item.source, item.destination, item.status, item.error)
    # Call only after the caller explicitly approves this captured plan.
    results = organizer.apply(plan, confirmed=True)
finally:
    organizer.close()
```

`plan_directory`/`organize_directory` require `includes=(...)` or `all_files=True`.
Exclusions are `exclusions=(...)` and `use_default_excludes=False` disables default
patterns. Rule patterns match basenames case-sensitively; selected files with no
enabled matching rule are skipped. The inherited fallback that moved unmatched
files is removed. Direct `organize_file` already selects one file explicitly and
still requires `destination_root=...`. Destructive adapters require
`confirmed=True`; `dry_run=True` uses the shared read-only preview.

The legacy `find_duplicates` dictionary API uses the same size-first/full-SHA
algorithm and raises on incomplete reports. `fast_mode=True` never enables
partial fingerprints. Explicit legacy indexing is possible only with
`record_index=True` and a supplied Database; ordinary reports never write it.

## Validated workflows and run history

A workflow is a JSON document with integer `version: 1`, a public `name`, optional
`on_failure: "stop"` (or `"continue"`), and 1–100 ordered steps. Each step has a
unique `id` (letter followed by letters/digits/underscore/hyphen, at most 64
characters), an `operation`, and a `parameters` object. The closed operation
registry supports only `inspect`, `duplicates`, and `organize`. No shell/Python
execution, dynamic imports, environment settings, or credentials are accepted.
Unknown fields, duplicate JSON keys, nonfinite numbers, wrong types, unsupported
versions, and invalid selections/template syntax are rejected before any step runs.
Source existence, destination containment and filesystem state are checked as
each step is prepared.
JSON files use UTF-8 (a BOM is accepted) and are limited to 1 MiB.

```json
{
  "version": 1,
  "name": "Copy selected logs",
  "on_failure": "stop",
  "steps": [
    {
      "id": "copy_logs",
      "operation": "organize",
      "parameters": {
        "source": "./artifacts",
        "destination": "../organized",
        "includes": ["logs/**/*.log"],
        "action": "copy"
      }
    }
  ]
}
```

Relative paths resolve against the workflow file's directory, independently of
the shell's current directory. Absolute paths and home-relative paths are also
supported. The **database path** is execution context: it is relative to the
shell's working directory, or an absolute path, and its parent must exist. Global
`--database` goes **before** the command.

Try the included [artifact-review workflow](../examples/workflows/review-artifacts.json)
against its tiny bundled fixture; the copy step preserves the source fixture:

```powershell
.\.venv\Scripts\tm.exe workflow validate .\examples\workflows\review-artifacts.json --format json
.\.venv\Scripts\tm.exe workflow run .\examples\workflows\review-artifacts.json --format json
.\.venv\Scripts\tm.exe --database .\taskmaster.db workflow run .\examples\workflows\review-artifacts.json --apply --format json
.\.venv\Scripts\tm.exe history list --format json
.\.venv\Scripts\tm.exe history show <run-id> --format json
```

Validation checks configuration shape/parameters without scanning source trees.
Run defaults to preview; it executes read-only inspection/duplicate steps and
previews organization with **no journal/database creation**. Preview does not
simulate copies/moves: a later step referring to an output that does not exist
yet can fail in preview. Apply prepares each step immediately before running it,
so later steps can consume actual earlier outputs. The complete configuration is
validated and held as an immutable canonical snapshot before execution.

Move workflows require `--apply --yes` even in a text terminal. Copy workflows
require `--apply`. `--yes` without apply is a usage error. Named workflow approval
covers the configured steps; current per-step plans and results are recorded.
There is no saved-plan execution or transactional multi-step simulation.

| Parameters | Supported fields/defaults |
| --- | --- |
| Shared | Required `source`; `includes: []`, `exclusions: []`, `use_default_excludes: true`, `recursive: true` |
| `inspect` | Shared fields plus `top: 10`, `min_size: 0` (nonnegative integers) |
| `duplicates` | Shared fields only |
| `organize` | Shared fields plus required `destination`; `action: "move"`, `strategy: "type"`, `template: null`, `conflict_policy: "error"`, `all_files: false`; requires nonempty includes or explicit all_files=true, never both |

Saved and direct named commands use the same parameter validator, scanner,
planner, and executor. Workflow configuration does not expose legacy
rename/delete rules or arbitrary Python callbacks. `Workflow.to_json()` returns
canonical JSON with defaults; parsing it again preserves the validated meaning.
Config fingerprints hash that canonical form. The config file itself cannot be
selected for movement/replacement, and known history files are protected.

`on_failure` acts **between steps**. `stop` marks remaining steps `not_run` after
an incomplete/failed step; `continue` attempts the remaining steps and still
returns exit 1 when anything failed. Within an organization step, the existing
file executor continues to report mixed successes/failures. Skips caused by the
explicit conflict policy remain nonfailures. No automatic rollback or retries
are introduced.

Every workflow preview/apply has a UUID run ID and UTC times. Apply records the
run before executing anything and records each step as `running` before starting
it. A run/step start-journal failure blocks that action. A completed file change
followed by file/step/final-journal failure remains visible as a real file change
and causes exit 1. A final-journal failure can leave a persisted run marked
`running`; history displays saved step states rather than claiming completion.
An interrupted run is not automatically resumed/retried.

Direct `organize --apply` and the interactive organizer also use this tracked path
while retaining the exact displayed plan. Their reports include `run_id` and
`run_history`. Low-level Python `FileOrganizer.apply` remains an execution API;
use `run_workflow` for run/step journaling. Direct read-only inspect/duplicates
remain deterministic and do not create journal rows.

History list/show use SQLite read-only connections and never initialize/migrate a
missing or older database. A missing history file lists no runs; an unknown run
ID returns exit 1. `history list --limit N` accepts 1–1000, default 20. Writable
initialization transactionally upgrades unversioned Phase 1–3 files to SQLite
`user_version=2`, retaining existing rows/outcomes and adding runs, steps, and
nullable run/step links on file history. New file-operation IDs are full UUIDs;
old IDs are retained. Newer unsupported schemas are rejected without downgrade.

Reports/history retain public operation IDs, paths, file outcomes, and structured
codes/messages. Raw configuration contents and arbitrary parameter values are
not included in validation errors or logs. Common credential assignments and URL
userinfo are redacted in diagnostic text; credentials are not supported workflow
parameters. Standard-library logging adds run/step context without configuring
logging at import time. Run history is separate from legacy scheduler records;
Phase 6 stores restorable schedules and attempt reports in separate tables.

## Reports, history, and safety limits

JSON is one unwrapped document on stdout, with `schema_version: 1`, command,
completion status, scope, summaries, and command-specific details. Inspection and
duplicate reports are deterministic for an unchanged tree. Organization reports
include planned identity/content fingerprints, intended paths, and actual
filesystem/history outcomes. Preview data has no random result IDs/timestamps;
tracked apply and workflow reports additionally include run IDs and UTC times.
JSON application never prompts. Runtime errors after valid argument parsing also
produce JSON; invalid CLI syntax/required options use argparse's stderr usage
message and exit 2. Reports can be redirected by the caller; no report file is
created automatically. Readable CLI reports escape characters that the selected
terminal/pipe encoding cannot represent (for example Chinese paths in CP1252),
instead of crashing. JSON escapes remain lossless when parsed.

The CLI writes apply attempts to `taskmaster.db` in its working directory
(unless global `--database` selects another file). That
file and its SQLite sidecars must be outside the selected sources and destination
root. A project root may contain history while includes select only logs/reports;
selecting the history file itself is rejected. The Python API records history
only when given a Database/history callback. Conditions and custom callbacks are
trusted Python and must keep their own side effects/storage appropriate.

Plans and source states are immutable. Apply rechecks roots, links, identity,
metadata, and full contents; creates destinations exclusively; verifies copies
before unlinking moved sources; and preserves existing destinations. Results
separate `filesystem_status`, `destination_created`, `source_removed`,
`history_status`, `history_error`, and overall status. A completed file change
with failed history is `completed_with_errors`; CLI exit 1 exposes the failure.
A failed unlink can leave source and complete destination; a failed write can
leave a partial destination. Inspect these before retrying. New partial files and
parent directories are not automatically rolled back. Batches continue after
per-file failures, with no automatic retries.

Success, preview, or an ordinary skip uses exit 0; access/validation/per-file or
history failures use 1. Argument syntax uses 2. Preview makes no intentional
filesystem/persistence writes, though reading may update OS access times.
Path checks are practical safeguards, not an OS security sandbox: another process
can still replace a path between validation and open/unlink. Avoid application
in hostile or actively modified trees. Move/rename are copy-plus-unlink, with no
atomicity/full ACL or alternate-stream preservation guarantee. Filesystem and
SQLite are separate transactions; crash recovery/exactly-once execution is not
claimed. Symlinks/junctions/reparse points, filesystem/home organization roots,
and overlapping roots are rejected. Real Windows junction tests pass; a real
file-symlink test skips when account privileges prevent creating its fixture.

## Durable project-review scheduling

The recurring use case is a saved project review with dependency ordering,
persisted attempts and restart behavior. A single independent CLI command can
still be invoked through an OS scheduler; this runner provides the integrated
state and history needed for dependent reviews. It runs in the foreground until
stopped; no background service is installed automatically.

```powershell
.\.venv\Scripts\tm.exe task add --name "Project review" --workflow .\examples\workflows\scheduled-project-review.json --schedule "2026-10-16T09:00:00+05:30" --recurrence hourly --max-retries 2 --timeout 60 --format json
.\.venv\Scripts\tm.exe task list --format json
.\.venv\Scripts\tm.exe task run-due --format json
.\.venv\Scripts\tm.exe task start
.\.venv\Scripts\tm.exe task attempts --format json
.\.venv\Scripts\tm.exe task pause <task-id>
.\.venv\Scripts\tm.exe task resume <task-id>
.\.venv\Scripts\tm.exe task cancel <task-id>
```

`task add` stores an immutable JSON copy of the validated workflow and its base
directory; editing/deleting the original file does not change the schedule.
Default workflow mode is read-only preview. File-changing workflows require
`--apply --yes` at registration and cannot have automatic retries. Known journal,
lock and workflow configuration paths remain protected from organization.
Direct `--operation inspect|duplicates --source PATH` is also supported.
Explicit `--command "..."` schedules a trusted shell command, stored verbatim;
this is separate from the closed JSON workflow registry. Commands, names and
paths are public database metadata, so do not store credentials in them.

Times require ISO timestamps with offsets and normalize to UTC. Legacy
`YYYY-MM-DD HH:MM` is interpreted as **UTC**, including interactive registration.
Daily/weekly cadence uses elapsed UTC time, not local DST wall time. Monthly
schedules retain the original day and clamp to the month's end, then restore the
anchor day in later months. `minutely`/`custom` use positive `--interval-minutes`.
Missed occurrences are coalesced into one run, followed by the next future tick.
The scheduler queries `next_run`, so retries and future due times survive restart.

`--max-retries N` means **N additional attempts**, default zero. Read-only failures
use exponential `--retry-delay` seconds (default 1, capped at 300). Subprocess
retries require `--retry-safe`, an explicit statement that repeated side effects
are acceptable. Exhaustion leaves the schedule failed. Success resets the current
occurrence's attempt budget, retaining lifetime counters and the last ten errors.
There is no exactly-once or automatic rollback guarantee.

`--depends-on TASK_ID` is repeatable and requires existing tasks. A dependency
must have succeeded at or after the dependent occurrence's scheduled time.
Missing/self/cyclic graphs are rejected. Waiting tasks become `BLOCKED` without
consuming attempts and are reconsidered while the runner is active.

Only one scheduler owns a database, using a held OS lock. Claims and attempt
starts commit together before launching work. One worker prevents overlapping
scheduled attempts in that database; separate databases and unrelated direct
commands are not coordinated. Database symlink/hard-link aliases are rejected.
Timeouts use a monotonic clock and terminate the process tree before recording
failure. Windows uses a kill-on-close Job Object; POSIX uses a process group.
The worker waits for its payload until containment is established. Subprocess
output keeps only a 4 KiB tail per stream; workflow output is limited to 4 MiB.
Timeout/cancel latency includes process cleanup and any SQLite lock waits.

Pause/cancel requests on running jobs are asynchronous: inspect `task attempts`
for the completed cancellation. Ctrl+C stops dispatch, terminates the active
tree, and pauses that job. Partial copies/moves may remain and need inspection.
An unexpected owner exit/final-journal failure leaves an interrupted attempt.
Restart marks it `INTERRUPTED` and blocks all dispatch until reviewed:

```powershell
# Only after checking actual outputs and that no old child process remains:
.\.venv\Scripts\tm.exe task recover <task-id> --acknowledge
# Recovery leaves it paused; explicitly choose whether to run again:
.\.venv\Scripts\tm.exe task resume <task-id>
```

On POSIX, children can survive an abrupt owner crash until explicitly terminated;
the recovery gate prevents automatic overlap/replay. This runner is not a sandbox
for hostile commands. Legacy callable-only task rows are preserved and listed as
`legacy_tasks`; their commands cannot be reconstructed and are never executed.
See [Phase 6 design and evidence](../docs/PHASE_6.md).

## Deferred work and provenance

Interactive Python evaluation, automatic duplicate deletion, and unplanned
empty-directory cleanup remain unavailable. The legacy callable Task model is
retained for compatibility with old records, not durable dispatch.
Plugin imports/explicit registration work; dynamic discovery
and image/PDF processing are deferred. Plugins execute trusted Python.

Phase 4 workflows are separate from JSON output reports. Phase 5 provides local
release checks and CI configuration. Hosted matrix results and verified upstream
license/copyright notices remain required before publishing. No publish job or
release credential is configured. Phase 6 scheduling is implemented locally.
See [development plan](../DEVELOPMENT_PLAN.md), [Phase 5 record](../docs/PHASE_5.md), [Phase 4 record](../docs/PHASE_4.md), [Phase 3 record](../docs/PHASE_3.md),
[Phase 2 record](../docs/PHASE_2.md), and [original audit](../docs/audits/PHASE_0_AUDIT.md).
The pre-Phase-6 code/tests/scripts are preserved in
[phase6-reference.zip](../docs/audits/phase6-reference.zip); earlier archives/evidence
remain historical.

This derives from the supplied TaskMaster snapshot. Its upstream URL/revision,
copyright holder, and actual license notices are unresolved. The original README
said MIT but supplied no LICENSE. No new copyright/license claim is made; resolve
provenance before distributing inherited code. See [attribution](../ATTRIBUTION.md).
