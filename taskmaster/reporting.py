"""CLI output without terminal markup or wrapping in machine-readable reports."""
from dataclasses import asdict
import json


def emit_json(report: dict) -> None:
    # ASCII escapes are lossless and work even with legacy Windows pipe encodings.
    print(json.dumps(report, indent=2, sort_keys=True))


def organization_report(plan, results, *, summary: dict, mode: str, scope: dict) -> dict:
    entries = []
    for operation, result in zip(plan.operations, results):
        entries.append({
            "source": str(operation.source),
            "destination": str(operation.destination) if operation.destination else None,
            "action": operation.action, "conflict_policy": operation.conflict_policy,
            "source_state": asdict(operation.source_state) if operation.source_state else None,
            "validation_error": operation.validation_error, "skipped_reason": operation.skipped_reason,
            "status": result.status, "filesystem_status": result.filesystem_status,
            "destination_created": result.destination_created, "source_removed": result.source_removed,
            "checksum": result.checksum, "error": result.error,
            "history_status": result.history_status, "history_error": result.history_error,
        })
    return {"schema_version": 1, "command": "organize", "mode": mode,
            "complete": not (summary["failed"] or summary["history_failed"]),
            "source_root": str(plan.source_root), "destination_root": str(plan.destination_root),
            "scope": scope, "operations": entries,
            "summary": {key: value for key, value in summary.items() if key != "timestamp"}}


def show_scan_report(console, report: dict) -> None:
    console.print(f"{report['command'].capitalize()}: {report['root']}", markup=False)
    if report["command"] == "inspect":
        console.print(f"Files: {report['summary']['file_count']}; bytes: {report['summary']['size_bytes']}")
        for extension in report["extensions"]:
            console.print(f"{extension['extension'] or '(no extension)'}: {extension['file_count']} files, "
                          f"{extension['size_bytes']} bytes", markup=False)
        console.print("Largest files:")
        for entry in report["largest_files"]:
            console.print(f"{entry['size_bytes']} bytes | {entry['path']}", markup=False)
    else:
        console.print(f"Found {report['summary']['duplicate_groups']} duplicate groups "
                      f"(full SHA-256; {report['summary']['hashed_files']} files hashed)")
        for group in report["groups"]:
            console.print(f"{group['sha256']} | {group['size_bytes']} bytes", markup=False)
            for path in group["paths"]:
                console.print(path, markup=False)
    for error in report["errors"]:
        console.print(f"Error: {error['path']}: {error['error']}", markup=False)
    if not report["complete"]:
        console.print("Incomplete scan; totals and groups cover successfully inspected files only.")


def show_step_report(console, report: dict) -> None:
    if report["command"] in {"inspect", "duplicates"}:
        show_scan_report(console, report)
        return
    for result in report["operations"]:
        console.print(f"{result['status']}: {result['source']} | files={result['filesystem_status']}"
                      f" | history={result['history_status']}"
                      f"{(' | ' + result['error']) if result['error'] else ''}"
                      f"{(' | History error: ' + result['history_error']) if result['history_error'] else ''}", markup=False)
    summary = report["summary"]
    console.print(f"Successful: {summary['successful']}; failed: {summary['failed']}; "
                  f"skipped: {summary['skipped']}; history failures: {summary['history_failed']}")
