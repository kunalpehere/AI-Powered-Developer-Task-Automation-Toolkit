"""Size-grouped, complete SHA-256 duplicate reporting without deletion."""
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .errors import PlanValidationError
from .planning import reject_links, source_state, stat_identity
from .scanning import scan_tree


def duplicate_report(root: Path, *, checksum: Callable[[Path], str] | None = None, **scan_options) -> dict:
    scan = scan_tree(root, **scan_options)
    sizes = defaultdict(list)
    for entry in scan.files:
        sizes[entry.size_bytes].append(entry)
    candidates = [entry for size in sorted(sizes) if len(sizes[size]) > 1 for entry in sizes[size]]
    groups = defaultdict(list)
    errors = [{"path": str(error.path), "error": error.error} for error in scan.errors]
    hasher = checksum or (lambda path: source_state(path).sha256)
    hashed = 0
    # Sequential by design: no future per file and no speculative parallelism.
    for entry in candidates:
        try:
            reject_links(entry.path)
            if stat_identity(entry.path.stat()) != entry.identity:
                raise PlanValidationError("File changed after the size scan")
            digest = hasher(entry.path)
            reject_links(entry.path)
            if stat_identity(entry.path.stat()) != entry.identity:
                raise PlanValidationError("File changed while hashing")
            groups[(entry.size_bytes, digest)].append(entry.path)
            hashed += 1
        except (OSError, ValueError) as error:
            errors.append({"path": str(entry.path), "error": str(error)})
    duplicates = [{"sha256": digest, "size_bytes": size,
                   "paths": [path.relative_to(scan.root).as_posix() for path in paths]}
                  for (size, digest), paths in sorted(groups.items(), key=lambda pair: (-pair[0][0], pair[0][1]))
                  if len(paths) > 1]
    return {
        "schema_version": 1, "command": "duplicates", "root": str(scan.root), "algorithm": "sha256",
        "complete": not errors,
        "scope": {"includes": list(scan.includes), "exclusions": list(scan.exclusions)},
        "summary": {"file_count": len(scan.files), "candidate_files": len(candidates), "hashed_files": hashed,
                    "duplicate_groups": len(duplicates),
                    "redundant_bytes": sum((len(group["paths"]) - 1) * group["size_bytes"] for group in duplicates),
                    "excluded_entries": scan.excluded_entries, "error_count": len(errors)},
        "groups": duplicates, "errors": sorted(errors, key=lambda item: (item["path"], item["error"])),
    }
