"""Read-only developer workspace summaries."""
from pathlib import Path

from .errors import PlanValidationError
from .scanning import scan_tree


def inspect_project(root: Path, *, top: int = 10, min_size: int = 0, **scan_options) -> dict:
    if type(top) is not int or top < 0 or type(min_size) is not int or min_size < 0:
        raise PlanValidationError("top and min_size must be nonnegative integers")
    scan = scan_tree(root, **scan_options)
    extensions = {}
    for entry in scan.files:
        extension = entry.path.suffix.lower()
        group = extensions.setdefault(extension, {"extension": extension, "file_count": 0, "size_bytes": 0})
        group["file_count"] += 1
        group["size_bytes"] += entry.size_bytes
    largest = sorted((entry for entry in scan.files if entry.size_bytes >= min_size),
                     key=lambda entry: (-entry.size_bytes, entry.path.relative_to(scan.root).as_posix()))[:top]
    return {
        "schema_version": 1, "command": "inspect", "root": str(scan.root),
        "complete": not scan.errors,
        "scope": {"includes": list(scan.includes), "exclusions": list(scan.exclusions)},
        "summary": {"file_count": len(scan.files), "size_bytes": sum(entry.size_bytes for entry in scan.files),
                    "directories_visited": scan.directories_visited, "excluded_entries": scan.excluded_entries,
                    "error_count": len(scan.errors)},
        "extensions": [extensions[key] for key in sorted(extensions)],
        "largest_files": [{"path": entry.path.relative_to(scan.root).as_posix(), "size_bytes": entry.size_bytes}
                          for entry in largest],
        "errors": [{"path": str(error.path), "error": error.error} for error in scan.errors],
    }
