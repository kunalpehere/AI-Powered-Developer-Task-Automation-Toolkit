"""Read-only scanning, template validation, and immutable operation planning."""
from dataclasses import replace
from collections import Counter
from datetime import datetime
import fnmatch
import hashlib
import os
from pathlib import Path, PureWindowsPath
import stat
from string import Formatter
from typing import Callable, Iterable

from .errors import PlanValidationError
from .models import FileRule, OperationPlan, PlannedOperation, SourceState

ACTIONS = {"copy", "move", "rename", "delete"}
CONFLICT_POLICIES = {"error", "skip"}
FIELDS = {"name", "filename", "ext", "type", "mime", "date", "year", "month", "day", "size_category", "relative_dir"}


def absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def reject_links(path: Path) -> None:
    """Check every existing component, including Windows reparse points."""
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PlanValidationError(f"Symlinks, junctions, and reparse points are not allowed: {part}")


def validate_roots(source_root: Path, destination_root: Path) -> tuple[Path, Path]:
    source, destination = absolute_path(source_root), absolute_path(destination_root)
    reject_links(source)
    reject_links(destination)
    if not source.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"Source must be a directory: {source}")
    if destination.exists() and not destination.is_dir():
        raise PlanValidationError(f"Destination root must be a directory: {destination}")
    if source == Path(source.anchor) or destination == Path(destination.anchor):
        raise PlanValidationError("A filesystem root cannot be an organization root")
    if source == Path.home() or destination == Path.home():
        raise PlanValidationError("Select a specific folder rather than the entire home directory")
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise PlanValidationError("Source and destination roots must not overlap")
    # Missing parents may be created only if existing ancestors are directories.
    for parent in destination.parents:
        if parent.exists() and not parent.is_dir():
            raise PlanValidationError(f"Destination parent is not a directory: {parent}")
    return source, destination


def validate_action(action: str, conflict_policy: str = "error") -> None:
    if not isinstance(action, str) or action not in ACTIONS:
        raise PlanValidationError(f"Unsupported action: {action!r}. Use copy, move, rename, or delete.")
    if not isinstance(conflict_policy, str) or conflict_policy not in CONFLICT_POLICIES:
        raise PlanValidationError(f"Unsupported conflict policy: {conflict_policy!r}. Use error or skip.")


def scan_files(directory: Path, recursive: bool = True, pattern: str = "*") -> list[Path]:
    # Lazy import avoids a cycle: scanner reuses the path/state helpers below.
    from .scanning import require_complete, scan_tree
    scan = scan_tree(directory, recursive=recursive, includes=(pattern,))
    require_complete(scan)
    return [entry.path for entry in scan.files]


def stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def source_state(path: Path) -> SourceState:
    reject_links(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise PlanValidationError(f"Source must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        # Python 3.12 on Windows exposes different ctime semantics for path stat
        # and fstat. Compare handle identity/size/mtime; compare path ctime only
        # with other path stats, and always verify full contents.
        if stat_identity(os.fstat(reader.fileno()))[:4] != stat_identity(before)[:4]:
            raise PlanValidationError(f"Source changed while being opened: {path}")
        while chunk := reader.read(1024 * 1024):
            digest.update(chunk)
    reject_links(path)
    if stat_identity(path.stat()) != stat_identity(before):
        raise PlanValidationError(f"Source changed while being inspected: {path}")
    return SourceState(*stat_identity(before), digest.hexdigest())


def validate_template(template: str) -> None:
    if not isinstance(template, str) or not template.strip():
        raise PlanValidationError("Destination template must be a nonempty string")
    try:
        for _, field, spec, conversion in Formatter().parse(template):
            if field is not None and (field not in FIELDS or spec or conversion):
                raise PlanValidationError(f"Unsupported template placeholder: {{{field}}}")
    except ValueError as error:
        raise PlanValidationError(f"Invalid destination template: {error}") from error


def expand_template(template: str, info: dict, now: datetime | None = None) -> Path:
    validate_template(template)
    if "{size_category}" in template and (type(info.get("size")) is not int or info["size"] < 0):
        raise PlanValidationError("Size templates require a nonnegative integer file size")
    now = now or datetime.now()
    values = {"name": info["stem"], "filename": info["name"],
              "ext": info["extension"].lstrip("."), "type": info["category"],
              "mime": info["mime_type"].replace("/", "_"),
              "date": now.strftime("%Y-%m-%d"), "year": now.strftime("%Y"),
              "month": now.strftime("%m"), "day": now.strftime("%d"),
              "relative_dir": info.get("relative_dir", ""),
              "size_category": ("small" if info.get("size", 0) < 1024 * 1024 else
                                "medium" if info.get("size", 0) < 100 * 1024 * 1024 else "large")}
    return Path(template.format_map(values))


def destination_path(rendered: Path, root: Path) -> Path:
    # Check both separator styles even when a plan is prepared on Linux.
    windows = PureWindowsPath(str(rendered))
    if ".." in windows.parts or ".." in rendered.parts:
        raise PlanValidationError("Destination traversal (..) is not allowed")
    if windows.drive and not rendered.is_absolute():
        raise PlanValidationError("Drive-relative or foreign absolute destination is not allowed")
    # Windows absolute-path normalization may strip trailing dots/spaces. Reject
    # those aliases before normalization, rather than silently changing a plan.
    for component in rendered.parts:
        if component == rendered.anchor:
            continue
        if (PureWindowsPath(component).is_reserved() or component.endswith((".", " "))
                or any(char in component for char in '<>:"|?*\\')):
            raise PlanValidationError(f"Destination contains an unsupported path component: {component!r}")
    destination = absolute_path(rendered if rendered.is_absolute() else root / rendered)
    if destination == root or not destination.is_relative_to(root):
        raise PlanValidationError(f"Destination is outside its root: {destination}")
    for component in destination.relative_to(root).parts:
        if (PureWindowsPath(component).is_reserved() or component.endswith((".", " "))
                or any(char in component for char in '<>:"|?*\\')):
            raise PlanValidationError(f"Destination contains an unsupported path component: {component!r}")
    reject_links(destination)
    for parent in destination.parents:
        if parent.exists() and not parent.is_dir():
            raise PlanValidationError(f"Destination parent is not a directory: {parent}")
        if parent == root:
            break
    return destination


def validate_operation(plan: OperationPlan, operation: PlannedOperation) -> None:
    validate_action(operation.action, operation.conflict_policy)
    source = operation.source
    if not source.is_absolute() or source != absolute_path(source) or not source.is_relative_to(plan.source_root):
        raise PlanValidationError(f"Source is outside its root: {source}")
    reject_links(source)
    if operation.action == "delete":
        if operation.destination is not None:
            raise PlanValidationError("A delete operation must not have a destination")
    elif operation.destination is None:
        raise PlanValidationError("This action requires a destination")
    else:
        destination_path(operation.destination, plan.destination_root)


def build_plan(source_root: Path, destination_root: Path, rules: Iterable[FileRule], *,
               file_info: Callable[[Path], dict], files: Iterable[Path] | None = None,
               recursive: bool = True, conflict_policy: str = "error") -> OperationPlan:
    source, destination = validate_roots(source_root, destination_root)
    validate_action("copy", conflict_policy)
    rules = sorted((rule for rule in rules if rule.enabled), key=lambda r: r.priority, reverse=True)
    for rule in rules:
        validate_action(rule.action, conflict_policy)
        if rule.condition is not None and not callable(rule.condition):
            raise PlanValidationError("Rule condition must be callable or None")
        if not isinstance(rule.source_pattern, str) or not rule.source_pattern:
            raise PlanValidationError("Rule source_pattern must be a nonempty string")
        if rule.action != "delete":
            validate_template(rule.destination_template)
    paths = scan_files(source, recursive) if files is None else sorted(absolute_path(p) for p in files)
    now = datetime.now()
    operations = []
    for path in paths:
        rule = next((r for r in rules if fnmatch.fnmatchcase(path.name, r.source_pattern)), None)
        if rule is None:
            operations.append(PlannedOperation(path, None, "copy", None, conflict_policy,
                                               skipped_reason="No enabled rule matched"))
            continue
        state, target, error, skipped = None, None, None, None
        try:
            if not path.is_relative_to(source):
                raise PlanValidationError(f"Source is outside its root: {path}")
            state = source_state(path)
            if rule.action != "delete":
                info = file_info(path)
                relative_dir = path.relative_to(source).parent.as_posix()
                info = {**info, "relative_dir": "" if relative_dir == "." else relative_dir}
                target = destination_path(expand_template(rule.destination_template, info, now), destination)
            if rule.condition and not rule.condition(path):
                skipped = "Condition not met"
            elif target is not None and target.exists():
                if conflict_policy == "skip":
                    skipped = f"Destination already exists: {target}"
                else:
                    raise FileExistsError(f"Destination already exists; leaving it unchanged: {target}")
        except (OSError, ValueError) as failure:
            error = str(failure)
        operations.append(PlannedOperation(path, target, rule.action, state, conflict_policy, error, skipped))
    # A plan must not let two inputs contend for a target or execute a source twice.
    source_counts = Counter(op.source for op in operations)
    destination_counts = Counter(op.destination for op in operations if op.destination is not None)
    for index, operation in enumerate(operations):
        if source_counts[operation.source] > 1 or (operation.destination is not None
                and destination_counts[operation.destination] > 1):
            operations[index] = replace(operation, validation_error="Multiple operations share a source or destination")
    return OperationPlan(source, destination, tuple(operations), now)
