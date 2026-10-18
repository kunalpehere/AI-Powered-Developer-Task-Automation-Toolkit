# Attribution and component history

Publication preparation preserves the reference ZIP archives and recorded source
hashes. Historical text reports replace the local Windows account name with
`LOCAL_USER` for privacy; this redacts execution paths, not original source or
authorship. Unredacted local report backups remain in ignored `.install-check/`.

The input was a local TaskMaster v2.0 snapshot. No upstream URL, revision, Git
history, actual LICENSE file, or copyright notice was supplied. The original
READMEs described MIT and setup metadata named a placeholder author. These are
recorded observations, not verified permission or an invented attribution.

The original 11 Python files, two READMEs, and pre-implementation development
plan are preserved in `docs/audits/phase1-reference.zip`. Original source hashes
are recorded in `docs/audits/phase0-results.json`. The original files in that
archive must remain available as provenance evidence until a verified upstream
history and notices can be established. No Git history was created in this phase.

| Component | Origin and treatment through Phase 6 |
| --- | --- |
| Models | Inherited task/rule types retained; Phase 2 adds immutable plan/source-state records and independent filesystem/history outcome fields; Phase 4 adds run/step links and full UUID file-operation IDs |
| Database | Inherited persistence retained; Phase 2 adds backward-compatible file-outcome columns; Phase 4 adds transactional versioned initialization, runs/steps, file associations and read-only run queries; scheduling defects remain |
| Scheduler | Inherited prototype preserved in references; replaced in Phase 6 by single-owner durable named scheduling, atomic claims, retry/dependency state and explicit crash recovery |
| Organizer | Adapted: source/action validation, scoped plan/preview/apply adapters, read-only size-first duplicate reporting, conflict preservation; implicit unmatched-file movement removed |
| Planning, execution, errors | Newly added in Phase 2 for root/template/state validation, confirmation, execution, and partial-failure reporting |
| Scanning, inspection, duplicates, reporting | Newly added in Phase 3 for explicit selections/exclusions, project summaries, sequential full hashing of size candidates, readable/JSON output |
| Configuration, operations, workflows | Newly added in Phase 4 for strict versioned JSON, shared parameter validation, sequential named operations, failure policy, contextual diagnostics and run journaling |
| CLI and module entry point | Adapted: syntax, dispatch, error exits, lazy resources, default preview, explicit destination/apply/approval, safety restrictions, accurate warnings; Phase 4 adds workflow/history commands, database selection and tracked direct/interactive application |
| Plugin classes and manager | Inherited code consolidated from `plugins.py` into `plugins/__init__.py`; discovery default adjusted for that location |
| Demo | Replaced with disposable inspection, preview/apply-copy, and duplicate reporting |
| Nested packaging and duplicated docs | Replaced by root `pyproject.toml` and authoritative README; nested README redirects |
| Regression tests and phase records | Newly added for this implementation |
| Workflow example and fixtures | Newly added in Phase 4 to demonstrate inspection, duplicate reporting and copying disposable log/CSV artifacts |
| CI, dependency baselines, release verification and design guides | Newly added in Phase 5; application changes are limited to unused-import removal identified by Ruff |
| Schedule model, process containment and worker | Newly added in Phase 6 for validated serializable task snapshots, UTC recurrence, Windows Job Objects/POSIX process groups and isolated execution |
| Schedule/attempt tables and CLI controls | Newly added in Phase 6 with schema-2 additive migration; legacy callable-only rows remain preserved and nonexecutable |

The pre-Phase-2 state is separately preserved in
`docs/audits/phase2-reference.zip`; the pre-Phase-3 source/tests/root docs are in
`docs/audits/phase3-reference.zip`; the pre-Phase-4 snapshot is in
`docs/audits/phase4-reference.zip`; the pre-Phase-5 code/tests/examples/root docs
are in `docs/audits/phase5-reference.zip`. Earlier reports describe their historical
snapshots; current behavior is documented in the root README and Phase 6 record.
The pre-Phase-6 source/scripts and original Phase 5 guides/examples are preserved
in `docs/audits/phase6-reference.zip`.

Phase 5 removed unused imports from inherited/adapted modules, including the
scheduler and plugin package, without repairing or extending their behavior.
Third-party dependency versions, package license metadata and installed notice
paths are recorded in `docs/audits/phase5-project.json`; that inventory does not
establish reuse terms for the supplied TaskMaster source.

The remaining provenance release gate is explicit: the upstream URL/revision,
actual license text and copyright notices have not been supplied or verified.
No new LICENSE file or package license identifier is fabricated. Historical
reference archives and hashes must remain with the repository during this review.

The inherited project is not represented as wholly original work. Resolve the
upstream reuse terms and preserve required copyright/license notices before
publishing retained or adapted code. No license identifier or author is invented
in the new package metadata.
