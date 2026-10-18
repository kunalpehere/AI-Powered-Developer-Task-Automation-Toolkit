# Phase 1 implementation record

Date: 15 October 2026 (Asia/Calcutta)  
Status: completed; Phase 2 has not started.

## Result and design

The inherited CLI could not parse, its setup directory omitted the application
package, and a shell-command argument replaced the dispatch field. It also
trusted partial fingerprints for duplicate deletion and overwrote existing file
destinations. These failures were reproduced in [Phase 0](audits/PHASE_0_AUDIT.md).

The baseline now installs from a root `pyproject.toml`, exposes both `taskmaster`
and `tm`, and runs as `python -m taskmaster`. The inherited UI remains, with its
malformed strings repaired and subcommand dispatch separated from shell text.
Resources are initialized lazily so help/usage errors do not create a database.
Module and console entry points propagate meaningful exit codes.

The plugin classes were consolidated into the existing `taskmaster.plugins`
package, eliminating the module/package collision. Their implementation was
retained and the default discovery directory adjusted. Explicit registration is
tested; dynamic discovery and optional processors are not advertised as validated.

All duplicate reports use complete SHA-256 hashes, including calls with legacy
`fast_mode=True`. Both automatic-deletion UI paths are disabled. This is a safety
restriction pending a separately reviewed design, not a claim of a complete
Phase 3 duplicate workflow. Scanning still hashes every file and writes the index.

File operations validate actions and sources, capture metadata failures per file,
and reject existing destinations. Destination files are opened with exclusive
creation, so an ordinary competing file creation cannot turn a checked copy into
an overwrite. Move/rename use exclusive copy followed by source removal. This
changes their atomicity and may affect filesystem metadata such as ACLs or
alternate streams; the implementation has no atomic rename/rollback guarantee.
Existing-destination preservation was tested for copy, move, rename, preview,
directory destinations, and a simulated concurrent destination creation.

Size sorting is explicitly unavailable instead of silently writing a literal
placeholder directory. Interactive Python evaluation is disabled; Python API
callables remain available. Shell tasks raise on nonzero subprocess exit status.
Artificial progress delays were removed, and repeated organization clears stale
rules/dry-run selections. The demo was replaced with a disposable preview and
duplicate-report example, using file-backed SQLite rather than broken `:memory:`.

The root README is authoritative; the nested README redirects to it. The old
nested setup file and shadowed plugin module were retired after replacements
were validated. [Attribution](../ATTRIBUTION.md) records inherited/adapted/new
components. No original-license or author identity was invented.

## Executed verification

Environment: Windows, Python 3.12.4. `.venv` excludes global site-packages and
contains an editable development install. `.venv-clean` excludes global
site-packages and contains the normal application wheel plus runtime dependencies.

| Command/check | Actual result |
| --- | --- |
| `python -m venv .venv` | Created after using workspace-local TEMP/TMP |
| `.\.venv\Scripts\python.exe -m pip install --retries 1 --timeout 20 -e '.[dev]'` | Success with approved network access; application 2.0.1, Rich 13.9.4, pytest 9.1.1 |
| `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=.test-tmp` | **30 passed in 4.58s** |
| `python -m pip wheel --no-deps --no-build-isolation --wheel-dir .install-check\wheels .` | Built `taskmaster-2.0.1-py3-none-any.whl` using existing setuptools 73.0.1 |
| `python -m venv --without-pip .venv-clean` | Created isolated second environment |
| `.\.venv\Scripts\python.exe -m pip --python .venv-clean\Scripts\python.exe install --no-index --find-links .install-check\wheels taskmaster==2.0.1` | Normal wheel and runtime dependency installation succeeded |
| Installed-package checks from `.install-check/outside` | **17 checks passed**, with expected success/error exits |
| `.\.venv\Scripts\python.exe -m pip check` | No broken requirements found |
| Parse all current application modules | All parsed |
| Baseline archive versus Phase 0 source/README hashes | All 13 original hashes matched |

Installation initially failed due to managed Windows temporary-directory access
and sandbox DNS restrictions. Workspace-local TEMP/TMP resolved the first issue;
approved network access resolved dependency downloads. The final wheel install
used local wheels without network. No global dependency installation was made.

The installed checks cover editable and normal-wheel module help and both console
commands, imports resolved from `.venv-clean` rather than the source tree, absence
of optional Pillow/PyPDF2, disposable demo, duplicate reporting, preview, actual
organization on fixtures, missing-source failure, disabled-deletion usage error,
task-add dispatch, and task listing. Commands, outputs, versions, and exit codes
are saved in [installation evidence](audits/phase1-install-results.json).

The 30 pytest cases cover the false-positive duplicate regression, genuine
duplicate group members, collision preservation, normal file operations, invalid
actions/sources, injected metadata/read errors, dispatch and shell text, preview,
nonzero exits, help/parse side effects, plugin imports/registration, interactive
deletion restriction, and module/demo startup.

## Review and local verification

The original application files, READMEs, and pre-change plan are preserved in
[phase1-reference.zip](audits/phase1-reference.zip). A
[source comparison](audits/phase1-source.diff) records modifications and removals
against that archive; newly added packaging/tests/docs are separate files.
Models, database, and scheduler implementation files remain unchanged. Phase 0
results remain historical; its collector now refuses a changed source snapshot
before replacing recorded evidence. No Git repository or commits were created.

Run the pytest command above and the help/demo commands in the
[README](../README.md) to verify locally. Important Python concepts here are
package discovery and import resolution, argparse destinations, lazy properties,
exceptions and process exits, chunked hashing, exclusive file creation, context
managers, and regression tests with disposable fixtures/mocks.

## Remaining limits and next boundary

- Preview still writes history; duplicate scans still write index records.
  Phase 2 will define the plan/preview/apply boundary.
- Parent symlinks/junctions, protected roots, concurrent source changes, rollback,
  and partial filesystem/history failures need the Phase 2 design. A failed
  operation may leave a new/partial destination; a retry requires inspecting it.
- Scheduler restoration, due-time selection, retries, failure logs, dependency
  accounting, timeout semantics, and shutdown remain unreliable or unverified.
  This phase verifies task registration/dispatch, not reliable scheduling.
- The database `:memory:` bug and incomplete indexed duplicate member query remain;
  current duplicate reports use organizer results rather than that query.
- Dynamic plugins and image/PDF processing remain deferred. Optional installation
  extras were retired from the supported package baseline.
- Linux/macOS, other Python versions, dependency vulnerability review, full
  reproducibility locking, and release checks are not completed in this phase.
- Upstream origin and actual license/copyright notices remain unresolved. The
  preserved snapshot establishes what was inherited, not distribution rights.

All Phase 1 acceptance items are met on the tested Windows/Python environment:
installation and help work, meaningful regressions pass, invalid inputs fail
usefully, and documentation distinguishes verified behavior from limitations.
The next phase is planning/execution separation and requires separate approval.
