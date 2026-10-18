"""Deterministic workspace scans with explicit scope and visible access errors."""
from dataclasses import dataclass
import fnmatch
from functools import lru_cache
import os
from pathlib import Path, PureWindowsPath
import stat
from typing import Iterable

from .errors import PlanValidationError
from .planning import absolute_path, reject_links, stat_identity

DEFAULT_EXCLUSIONS = (".git", ".venv*", "venv", "__pycache__", "node_modules",
                      ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox")


def patterns(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise PlanValidationError("Patterns must be a sequence of strings, not one string")
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise PlanValidationError("Include/exclude patterns must be nonempty strings")
        value = value.replace("\\", "/")
        if value.endswith("/"):
            value += "**"
        if (value.startswith("/") or PureWindowsPath(value).drive or ":" in value
                or any(part in {"", ".", ".."} for part in value.split("/"))):
            raise PlanValidationError(f"Patterns must be relative without traversal: {value!r}")
        normalized.append(value)
    return tuple(dict.fromkeys(normalized))


def matches(relative: str, pattern: str) -> bool:
    """No slash: basename at any depth. Slash: root-relative; ** spans segments."""
    if "/" not in pattern:
        return fnmatch.fnmatchcase(relative.rsplit("/", 1)[-1], pattern)
    parts, tokens = tuple(relative.split("/")), tuple(pattern.split("/"))

    @lru_cache(maxsize=None)
    def visit(index, token):
        if token == len(tokens):
            return index == len(parts)
        if tokens[token] == "**":
            return visit(index, token + 1) or (index < len(parts) and visit(index + 1, token))
        return index < len(parts) and fnmatch.fnmatchcase(parts[index], tokens[token]) and visit(index + 1, token + 1)

    return visit(0, 0)


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    size_bytes: int
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class ScanIssue:
    path: Path
    error: str


@dataclass(frozen=True)
class ScanResult:
    root: Path
    files: tuple[ScannedFile, ...]
    errors: tuple[ScanIssue, ...]
    exclusions: tuple[str, ...]
    includes: tuple[str, ...]
    directories_visited: int
    excluded_entries: int


def scan_tree(root: Path, *, includes: Iterable[str] = (), exclusions: Iterable[str] = (),
              use_default_excludes: bool = True, recursive: bool = True) -> ScanResult:
    root = absolute_path(root)
    reject_links(root)
    if not root.exists():
        raise FileNotFoundError(f"Source directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Source must be a directory: {root}")
    selected = patterns(includes)
    excluded = tuple(dict.fromkeys((DEFAULT_EXCLUSIONS if use_default_excludes else ()) + patterns(exclusions)))
    files, errors = [], []
    visited = omitted = 0

    def scan_error(error):
        errors.append(ScanIssue(Path(error.filename) if error.filename else root, str(error)))

    for current, directories, names in os.walk(root, followlinks=False, onerror=scan_error):
        visited += 1
        retained = []
        for name in sorted(directories):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if any(matches(relative, pattern) for pattern in excluded):
                omitted += 1
                continue
            try:
                reject_links(path)
                retained.append(name)
            except (OSError, ValueError) as error:
                errors.append(ScanIssue(path, str(error)))
        directories[:] = retained if recursive else []
        for name in sorted(names):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if any(matches(relative, pattern) for pattern in excluded):
                omitted += 1
                continue
            if selected and not any(matches(relative, pattern) for pattern in selected):
                continue
            try:
                reject_links(path)
                info = path.stat()
                if not stat.S_ISREG(info.st_mode):
                    raise PlanValidationError(f"Only regular files are supported: {path}")
                files.append(ScannedFile(path, info.st_size, stat_identity(info)))
            except (OSError, ValueError) as error:
                errors.append(ScanIssue(path, str(error)))
    key = lambda item: item.path.relative_to(root).as_posix()
    return ScanResult(root, tuple(sorted(files, key=key)), tuple(sorted(errors, key=key)),
                      excluded, selected, visited, omitted)


def require_complete(scan: ScanResult) -> None:
    if scan.errors:
        first = scan.errors[0]
        raise PlanValidationError(f"Scan incomplete ({len(scan.errors)} errors): {first.path}: {first.error}")
