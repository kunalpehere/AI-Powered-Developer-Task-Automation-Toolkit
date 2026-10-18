# Design and interview notes

TaskMaster inspects projects, verifies duplicate content, and organizes selected
development artifacts. Phase 6 replaces the inherited scheduler engine with
durable named schedules and isolated attempts. Dynamic plugins remain experimental.

## Control flow

```text
CLI arguments or versioned JSON
    -> shared parameter validation (operations.py)
    -> scoped read-only scan (scanning.py)
    -> inspection / size-first full duplicate hashing
       or immutable organization plan (planning.py)
    -> preview or explicit approval
    -> revalidation and per-file execution (execution.py)
    -> actual file outcomes and structured reports
    -> run/step/file journal for CLI and workflow apply
```

JSON validation rejects unknown fields and code-bearing operations. Canonical
serialization includes defaults and provides a fingerprint; it does not freeze
the filesystem. Relative paths use the workflow directory. Direct commands use
the shell's directory. Steps execute sequentially; previews do not simulate
future outputs. Stop/continue applies between steps, while a file batch retains
mixed results. These choices make composition explainable without a scheduler.

Organization plans are frozen dataclasses containing source metadata and content
fingerprints. Apply uses the same displayed plan, rechecks state, creates outputs
exclusively, verifies copies, and unlinks moved inputs only after successful copy
verification. Existing files are never silently overwritten. Include/exclude
patterns define scope before reads; symlinks and reparse points are refused.

The database commits a run and a step's start before allowing its action. A
filesystem operation and its SQLite record cannot be one atomic transaction.
Reports separate source removal, destination creation and journal outcomes;
`running` can survive a crash. No automatic resume, rollback or exactly-once
guarantee is implied. The journal itself is excluded from selected inputs.

The schedule layer persists validated snapshots, UTC cadence and dependency
state in schema 2. An OS owner lock plus atomic attempt claims prevents duplicate
dispatch, and one worker prevents overlap within the same database. Attempts run
in contained child processes so timeout/cancellation can terminate actual work.
Interrupted attempts require review and explicit recovery rather than replay.
See [Phase 6](PHASE_6.md) for retry, recurrence, crash and shutdown semantics.

Inspection uses metadata. Duplicate reporting groups by size, hashes only
candidate groups with full SHA-256 in bounded reads, and rechecks state. Empty
files work. Logical redundant bytes do not measure actual space reclaimed.
Sequential hashing favors clear correctness over unmeasured parallel speed.

## Python concepts to explain

| Concept | Concrete example |
| --- | --- |
| Dataclasses and immutability | Plans/source states and canonical workflow step snapshots |
| Functions, collections and separation of concerns | Scanning, normalization, reporting and sequential dispatch |
| Context managers | File handles, SQLite transactions and disposable demo fixtures |
| Exceptions and explicit results | Validation fails early; file and journal outcomes remain independently visible |
| Serialization | Versioned JSON, normalized defaults, fingerprints and stored report JSON |
| Generators/iteration and bounded I/O | Tree traversal and chunked content hashing |
| Testing and dependency injection | Read/write denial, changed sources, collisions, and journal failures without relying on OS ACL setup |

## Inherited versus newly designed

The supplied snapshot contributed models, persistence, organizer, scheduler, CLI
and plugin ideas/code. Phases 1–4 repaired startup, replaced unsafe file flows,
added scanning/inspection/duplicates and implemented named JSON workflows/history.
Phase 5 adds reproducible setup, CI, coverage, audits, packaging verification and
these notes. Phase 6 replaces scheduler behavior and adds serializable schedule
models, attempt persistence and contained process execution.
See [ATTRIBUTION.md](../ATTRIBUTION.md) for the component record and unresolved
upstream terms. Do not describe this as wholly original work.

## Deliberate limits

Path checks cannot prevent every hostile replacement race. Moves are copy/unlink,
not atomic renames, and do not promise full ACL/alternate-stream preservation.
History is file-backed SQLite, with no pruning/recovery protocol. Names and paths
are public metadata; diagnostic redaction is best effort for common formats.
Performance on very large trees and concurrent writers is not characterized.
These limits should be explained alongside the successful safety tests.
