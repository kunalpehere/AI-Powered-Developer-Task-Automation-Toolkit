# Phase 6 — Durable project-review scheduling

Date: 15 October 2026 (Asia/Calcutta)

Status: local implementation complete. Hosted platform CI and upstream provenance
verification remain the existing release gates. Nothing has been published.

## Use case and scope

The user selected recurring project-review workflows. A saved review can contain
inspection, duplicate reporting and artifact-plan previews, depend on another
review, and retain its attempt/retry state through process restarts. An existing
OS scheduler remains suitable for an independent CLI invocation; this runner
adds portable dependency ordering and integrated attempts/history without OS-specific
job configuration. A foreground owner process must be running for dispatch.

The previous callable/thread-pool scheduler could not restore commands, queried
the original schedule rather than retry due time, could queue duplicate work,
and could not terminate a timed-out Python thread. It has been replaced with
serializable tasks and isolated worker processes. No scheduling dependency was
added: SQLite, asyncio, POSIX process groups and Windows Job Objects cover the
small single-worker design. Third-party scheduler libraries would not eliminate
the need to define crash/side-effect policies or terminate actual work.

## Model, persistence and dispatch

`schedules.py` contains `ScheduledTask`, validated named operation parameters,
timezone normalization and recurrence arithmetic. `scheduler.py` owns registration,
graph validation, dispatch, retries and recovery. `scheduled_worker.py` executes
the saved snapshot; `processes.py` contains output limits and tree cleanup.

SQLite schema 2 adds `scheduled_tasks` and `scheduled_attempts` in the same
versioned initialization transaction. Earlier task, run, step, file and index
records are preserved. Legacy callable-only task rows remain visible separately
but are never guessed into executable commands. Attempts have full UUID IDs,
occurrence/attempt numbers, start/finish times, PID and structured reports.

The owner holds an OS advisory lock for the entire scheduler session. Atomic
claims commit running state and an attempt before any child starts. One worker
prevents concurrent scheduled attempts in a database. Symlink/hard-link database
aliases are refused. Other databases, manually launched commands and arbitrary
external writers are outside that coordination boundary.

The worker waits on stdin until its parent has assigned process containment and
recorded its PID, then receives the immutable task snapshot. Windows uses a
kill-on-close Job Object; POSIX uses a separate process group. Timeout/cancellation
terminates the tree before the final attempt transaction. Standard-output/error
tails for commands are bounded to 4 KiB each; named-workflow output has a 4 MiB
limit. Excessive workflow output produces a failure with advice to inspect
workflow history, rather than pretending the underlying file changes rolled back.

## Defined behavior

| Concern | Policy |
| --- | --- |
| Timezones | Require explicit offsets in the API; normalize to UTC. Legacy CLI minute strings explicitly mean UTC |
| Cadence | Anchor to original scheduled time; run one coalesced overdue occurrence, skip missed ticks and choose the next future boundary |
| Monthly dates | Clamp to month's end while retaining the original day anchor for later months |
| Retries | `max_retries` means additional attempts; default zero. Exponential delay starts at retry-delay seconds, capped at 300 |
| Counters | Lifetime run/failure counts persist; occurrence attempt budget resets on success; retain last ten diagnostic errors |
| Side effects | File-changing workflows require saved approval and prohibit automatic retries. Shell retries require explicit retry-safe acknowledgement |
| Dependencies | Existing distinct IDs, no self/cycles; require a successful prerequisite at/after the dependent occurrence's scheduled time |
| Blocked work | Visible `BLOCKED` state, no consumed attempt, rechecked by the active runner |
| Pause/cancel | Pending work stops immediately; running requests are polled and terminate the tree. Inspect the final attempt to confirm cancellation |
| Shutdown | Stop dispatch, terminate active work, leave its job paused. Completed files may remain |
| Unclean restart | Convert durable running work to interrupted; block every dispatch until review/acknowledgement, then leave recovered tasks paused |
| Failed finish journal | Preserve running state for recovery; do not replay automatically |

Names, paths and explicit shell commands are public metadata. Common credential
assignments in diagnostics/output are redacted; this is not a universal secret
detector. Callables, dynamic plugin tasks and shell commands inside JSON workflow
configuration are not supported. Explicit `task add --command` remains a trusted
shell-execution feature with no credential isolation.

## Verification and evidence

The regression suite includes 26 new scheduling cases covering future/retry due
times, restoration, exact retry budgets, missed ticks, month boundaries, UTC
offsets, dependency blocking/cycles, same-/cross-process owner exclusion, atomic
claims, interrupted review, pause/cancel, final-journal failures, legacy rows,
snapshot restoration, bounded/redacted output and approval/retry guards.

Real Windows timeout checks launch a descendant that writes a ready marker,
terminate its tree, then verify that its delayed file write never occurs.
Shutdown and cancellation tests terminate active work before checking persisted
states. Existing workflow/file safety regressions remain, with the legacy command
registration test updated to assert serialized command text instead of a closure.
Schema-upgrade assertions now expect version 2 without rewriting prior outcomes.

Reports are saved as [JUnit](audits/phase6-test-results.xml),
[coverage JSON](audits/phase6-coverage.json), and
[installed checks](audits/phase6-install-results.json). The portable installation
verifier also registers a recurring review, deletes its config fixture, dispatches
it in another process, reads attempt history, exercises controls and rejects an
unknown dependency. All fixtures are disposable; no real recurring service or
user command was installed or left running.

Before/after evidence: [reference snapshot](audits/phase6-reference.zip),
[source diff](audits/phase6-source.diff), [hash manifest](audits/phase6-change-manifest.json),
and [verification summary](audits/phase6-verification.json). The reference archive
includes pre-change code and the hash-verified Phase 5 source archive's original
guides/examples, preserved before the Phase 6 build.

## Limits

The runner is a single local owner, not distributed scheduling or an OS sandbox.
On POSIX, children can survive abrupt owner death. Recovery requires the operator
to inspect partial results and ensure old processes are stopped before acknowledging.
Windows Job Objects also do not promise containment of hostile commands that
deliberately exploit OS mechanisms. SQLite waits and cleanup add to timeout latency;
no realtime deadline is promised. Filesystem and journal changes remain separate,
so cancellation/crash can leave partial copies or completed moves.

Exactly-once side effects, automatic rollback/resume, arbitrary Python callback
restoration, cross-database overlap prevention and named local-time/DST calendars
are not claimed. CI is configured for Windows/Linux and Python 3.12–3.14; only
Windows/Python 3.12.4 was available locally. Prior release/provenance checks remain
pending and historical phase records describe their earlier snapshots.
