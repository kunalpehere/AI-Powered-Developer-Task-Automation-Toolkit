"""Execute a previously inspected plan; persistence is an independent boundary."""
import hashlib
import os
import shutil
from typing import Callable

from .errors import ConfirmationRequired, PlanValidationError
from .models import FileOperation, OperationPlan, PlannedOperation
from .planning import source_state, stat_identity, validate_operation, validate_roots


def preview_plan(plan: OperationPlan) -> list[FileOperation]:
    """Render captured intentions without file reads, file writes, or history."""
    results = []
    for operation in plan.operations:
        result = FileOperation(source=operation.source, destination=operation.destination,
                               operation=operation.action,
                               size_bytes=operation.source_state.size if operation.source_state else 0)
        if operation.validation_error:
            result.status, result.error = "failed", operation.validation_error
        elif operation.skipped_reason:
            result.status, result.error = "skipped", operation.skipped_reason
        else:
            result.status = "dry_run"
            result.checksum = operation.source_state.sha256 if operation.source_state else None
        results.append(result)
    return results


def revalidate_source(plan: OperationPlan, operation: PlannedOperation) -> None:
    roots = validate_roots(plan.source_root, plan.destination_root)
    if roots != (plan.source_root, plan.destination_root):
        raise PlanValidationError("Plan roots must be absolute normalized paths")
    validate_operation(plan, operation)
    if operation.source_state is None or source_state(operation.source) != operation.source_state:
        raise PlanValidationError(f"Source changed since planning; create a new plan: {operation.source}")


def _apply_file(plan: OperationPlan, operation: PlannedOperation, result: FileOperation) -> None:
    revalidate_source(plan, operation)
    destination = operation.destination
    if destination is not None and destination.exists():
        if operation.conflict_policy == "skip":
            result.status, result.error = "skipped", f"Destination already exists: {destination}"
            return
        raise FileExistsError(f"Destination already exists; leaving it unchanged: {destination}")
    if operation.action == "delete":
        operation.source.unlink()
        result.source_removed = True
        result.filesystem_status = "deleted"
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Recheck newly created parents and file state before opening either file.
        revalidate_source(plan, operation)
        expected = operation.source_state
        digest = hashlib.sha256()
        with operation.source.open("rb") as reader:
            if stat_identity(os.fstat(reader.fileno()))[:4] != (expected.device, expected.inode,
                    expected.size, expected.modified_ns):
                raise PlanValidationError(f"Source changed while being opened: {operation.source}")
            try:
                writer = destination.open("xb")
            except FileExistsError:
                if operation.conflict_policy != "skip":
                    raise
                result.status, result.error = "skipped", f"Destination already exists: {destination}"
                return
            result.destination_created = True
            result.filesystem_status = "partial"
            with writer:
                while chunk := reader.read(1024 * 1024):
                    digest.update(chunk)
                    writer.write(chunk)
        if digest.hexdigest() != expected.sha256:
            raise PlanValidationError("Source content changed during copy; inspect the partial destination")
        revalidate_source(plan, operation)
        shutil.copystat(operation.source, destination)
        if source_state(destination).sha256 != expected.sha256:
            raise PlanValidationError("Destination verification failed; source was retained")
        result.filesystem_status = "copied"
        result.checksum = expected.sha256
        if operation.action in {"move", "rename"}:
            revalidate_source(plan, operation)
            operation.source.unlink()
            result.source_removed = True
            result.filesystem_status = "moved" if operation.action == "move" else "renamed"
    result.status = "success"
    result.checksum = operation.source_state.sha256


def execute_plan(plan: OperationPlan, *, confirmed: bool = False,
                 history_recorder: Callable[[FileOperation], None] | None = None) -> list[FileOperation]:
    """Apply each item once, continuing on per-file failures. No automatic retries.

    A confirmation failure happens before *any* mutation or history recording.
    New partial files are retained on failure for inspection; no unsafe rollback
    deletion or replacement of existing destinations is attempted.
    """
    validate_roots(plan.source_root, plan.destination_root)
    if not isinstance(confirmed, bool):
        raise PlanValidationError("confirmed must be an explicit boolean")
    if plan.requires_confirmation and not confirmed:
        raise ConfirmationRequired("Confirmation required for move, rename, or delete operations")
    results = preview_plan(plan)
    for operation, result in zip(plan.operations, results):
        if result.status == "dry_run":
            # A preview checksum describes the planned source, not necessarily
            # the contents of a partially written destination after failure.
            result.checksum = None
            try:
                _apply_file(plan, operation, result)
            except Exception as error:
                result.status, result.error = "failed", str(error)
        if history_recorder is not None:
            try:
                result.history_status = "recorded"
                history_recorder(result)
            except Exception as error:
                result.history_status, result.history_error = "failed", str(error)
                if result.status == "success":
                    result.status = "completed_with_errors"
    return results
