# TaskMaster — Developer Task Automation Toolkit

A Python CLI for inspecting developer workspaces, finding verified duplicates, organizing selected files, and running repeatable workflows with SQLite history and durable scheduling.

File operations follow **plan → preview → apply → report**. The project demonstrates CLI design, filesystem validation, configuration validation, persistence, and automated testing. It currently uses explicit rules and workflows; **no AI model integration or API key is required**.

**Publication status:** local development candidate. The inherited source's upstream repository, revision, license text, and copyright notices still need verification before distribution. This project includes adapted reference material and is not represented as wholly original work. See [attribution](ATTRIBUTION.md).

## Features

- Workspace summaries: file counts, extension statistics, sizes, and largest files.
- Duplicate reporting: size filtering followed by complete SHA-256 verification.
- File organization: selected copies/moves, preview by default, validated destinations, and conflict preservation.
- Validated JSON workflows with ordered steps and stop/continue failure policies.
- SQLite run history with recorded filesystem and journal outcomes.
- Durable scheduling with recurrence, dependencies, retries, timeouts, and interruption recovery.
- CLI aliases (`taskmaster`, `tm`), module execution, Python API, and text/JSON reports.

## Requirements and installation

Requires **Python 3.12+**, `pip`, `venv`, and network access to PyPI for the first install. Rich is the only direct runtime dependency; SQLite and hashing use Python's standard library. No external service is needed.

Open a terminal in the project root beside `pyproject.toml`. For normal use on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m taskmaster --help
```

For Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m taskmaster --help
```

For development with pinned, hashed dependencies, use a fresh environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements/dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pip check
```

On Linux/macOS, substitute `.venv/bin/python`. Normal installation resolves the declared runtime version range; the development baseline pins exact dependencies. See [dependency setup](requirements/README.md) for runtime-only pins and lockfile updates.

## Quick start

These PowerShell examples inspect the bundled fixture, report duplicates, and preview a workflow without changing the selected files or creating history:

```powershell
.\.venv\Scripts\python.exe -m taskmaster inspect --source examples/fixtures/workspace --top 5
.\.venv\Scripts\python.exe -m taskmaster duplicates --dir examples/fixtures/workspace --format json
.\.venv\Scripts\python.exe -m taskmaster workflow validate examples/workflows/review-artifacts.json
.\.venv\Scripts\python.exe -m taskmaster workflow run examples/workflows/review-artifacts.json
```

Preview copying selected logs into a separate destination:

```powershell
.\.venv\Scripts\python.exe -m taskmaster organize --source examples/fixtures/workspace --destination ../taskmaster-output --include "logs/**/*.log" --action copy
```

Review the preview before repeating with `--apply`. Moves also need explicit approval (`--yes` for noninteractive use). Existing destinations are preserved; inspect partial outputs after failures before retrying.

The disposable demo creates and removes its own temporary fixtures:

```powershell
.\.venv\Scripts\python.exe -m taskmaster.demo --directory .
```

## Configuration and commands

No `.env` file or credentials are needed. Workflow JSON uses `version: 1`, a name, and ordered steps. Relative workflow paths resolve against the configuration file. See [workflow examples](examples/workflows) and the [usage guide](docs/USAGE.md) for parameters, Python API examples, scheduling, and failure behavior.

| Command | Purpose |
| --- | --- |
| `inspect --source PATH` | Summarize a workspace |
| `duplicates --dir PATH` | Report verified duplicate groups |
| `organize --source PATH --destination PATH --include PATTERN` | Preview selected file operations |
| `workflow validate FILE` / `workflow run FILE` | Validate or preview a workflow; add `--apply` to execute changes |
| `history list` / `history show ID` | Read saved run history |
| `task add` / `list` / `run-due` / `start` | Register, inspect, and run schedules |
| `task pause` / `resume` / `cancel` / `attempts` / `recover` | Manage task state and recovery |

Use `--help` on each command. Global `--database PATH` goes before the command; the default is `taskmaster.db` in the current working directory. Apply and scheduling commands can persist records. Keep databases outside version control and never put credentials in task names or shell commands. `task start` runs in the foreground.

## Testing

After the development installation, quick checks include:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check taskmaster tests scripts
.\.venv\Scripts\python.exe scripts/check_project.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_mvp.py -k "inspection_counts or duplicate_candidates"
```

The full suite is a separate command and includes filesystem/process tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Existing tests cover scanning, duplicates, planning/execution, workflow validation, history, and scheduling. GitHub Actions defines Windows/Ubuntu and Python 3.12–3.14 checks. Historical local evidence covers Windows/Python 3.12.4; hosted CI and a fresh network installation have not been revalidated during publication preparation. See [feature evidence](docs/FEATURE_EVIDENCE.md) and [release checks](docs/RELEASE.md).

## Project structure

```text
taskmaster/        CLI, filesystem operations, workflows, database, scheduler
tests/             Regression tests
examples/          Workflows and small workspace fixtures
requirements/      Pinned and hashed dependency baselines
scripts/           Configuration, distribution, and installation checks
docs/              Usage, design, platform notes, and historical evidence
.github/workflows/ GitHub Actions configuration
```

## Limitations

- No AI integration, GUI, automatic duplicate deletion, or installed background service.
- Dynamic plugin discovery and image/PDF processing remain deferred.
- Filesystem changes and SQLite history use separate transactions; there is no automatic rollback or exactly-once guarantee.
- Path checks do not isolate hostile or concurrently modified trees. Unsafe destinations, overlapping organization roots, and links/reparse points are rejected.
- Scheduling uses UTC recurrence. Interrupted attempts need review before recovery; shell tasks execute trusted commands.

See [design](docs/DESIGN.md), [platform limits](docs/PLATFORMS.md), and the [detailed usage guide](docs/USAGE.md).

## License and attribution

No project license is asserted while the inherited source's reuse terms remain unverified. A historical README mentioned MIT but supplied no actual license or copyright notice. Identify the upstream source and preserve its applicable notices before publishing inherited or adapted code; adding a new license alone does not resolve this.

[ATTRIBUTION.md](ATTRIBUTION.md) records inherited and added components. Original source archives and hashes in `docs/audits/` remain preserved as provenance evidence. Historical text reports replace the local Windows username with `LOCAL_USER` for privacy; source hashes and reference archives are unchanged.
