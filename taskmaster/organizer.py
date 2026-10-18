"""
TaskMaster - Advanced File Organizer
Smart file organization with duplicate detection, content analysis, and rules engine.
"""
import hashlib
import mimetypes
from dataclasses import replace
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from .models import FileRule, FileOperation, OperationPlan
from .database import Database
from .errors import PlanValidationError
from .execution import execute_plan, preview_plan
from .planning import absolute_path, build_plan, expand_template, scan_files, validate_action, validate_template, validate_roots
from .scanning import patterns, require_complete, scan_tree
from .duplicates import duplicate_report

class FileOrganizer:
    """Advanced file organizer with rule-based processing and duplicate detection."""

    # File type categories
    CATEGORIES = {
        "images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico"},
        "videos": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
        "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
        "documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx"},
        "code": {".py", ".js", ".html", ".css", ".java", ".cpp", ".c", ".h", ".go", ".rs", ".ts"},
        "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
        "data": {".json", ".xml", ".csv", ".yaml", ".yml", ".sql", ".db"},
        "executables": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"},
    }

    def __init__(self, db: Database | None = None, dry_run: bool = False, *, history_recorder=None,
                 history_path: Path | None = None):
        self.db = db
        self.history_recorder = history_recorder or (db.log_file_operation if db is not None else None)
        known_path = history_path if history_path is not None else (db.db_path if db is not None else None)
        self.history_path = absolute_path(known_path) if known_path is not None and str(known_path) != ":memory:" else None
        self.dry_run = dry_run
        self.rules: List[FileRule] = []

    def add_rule(self, rule: FileRule) -> None:
        """Add an organization rule."""
        self._validate_action(rule.action)
        if rule.action != "delete":
            validate_template(rule.destination_template)
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def get_file_category(self, path: Path) -> str:
        """Determine file category based on extension."""
        ext = path.suffix.lower()
        for category, extensions in self.CATEGORIES.items():
            if ext in extensions:
                return category
        return "misc"

    @staticmethod
    def _validate_action(action: str) -> None:
        validate_action(action)

    def close(self) -> None:
        """Compatibility lifecycle hook; file scans are now sequential."""

    def calculate_checksum(self, path: Path, algorithm: str = "sha256", 
                          chunk_size: int = 8192) -> str:
        """Calculate file checksum for duplicate detection."""
        hash_obj = hashlib.new(algorithm)
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()

    def get_file_info(self, path: Path) -> Dict[str, Any]:
        """Get comprehensive file information."""
        stat = path.stat()
        return {
            "path": path,
            "name": path.name,
            "stem": path.stem,
            "extension": path.suffix.lower(),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime),
            "created": datetime.fromtimestamp(stat.st_ctime),
            "category": self.get_file_category(path),
            "mime_type": mimetypes.guess_type(str(path))[0] or "unknown",
        }

    def scan_directory(self, directory: Path, recursive: bool = True,
                      pattern: str = "*") -> List[Path]:
        """Scan directory for files matching pattern."""
        return scan_files(directory, recursive, pattern)

    def find_duplicates(self, directory: Path, recursive: bool = True,
                       fast_mode: bool = False, *, record_index: bool = False,
                       exclusions=(), use_default_excludes: bool = True) -> Dict[str, List[Path]]:
        """Legacy dictionary API: all size candidates receive complete SHA-256.

        Unlike the report API, this adapter raises if results are incomplete.
        fast_mode remains accepted but never enables partial fingerprints.
        """
        report = duplicate_report(directory, recursive=recursive, exclusions=exclusions,
                                  use_default_excludes=use_default_excludes,
                                  checksum=self.calculate_checksum)
        if not report["complete"]:
            error = report["errors"][0]
            raise PlanValidationError(f"Duplicate scan incomplete: {error['path']}: {error['error']}")
        root = Path(report["root"])
        duplicates = {group["sha256"]: [root / name for name in group["paths"]] for group in report["groups"]}
        if record_index:
            if self.db is None:
                raise PlanValidationError("record_index=True requires an explicit Database")
            for checksum, paths in duplicates.items():
                for path in paths:
                    self.db.index_file(path, checksum, path.stat().st_size)
        return duplicates

    def apply_template(self, template: str, file_info: dict) -> Path:
        return expand_template(template, file_info)

    def plan_directory(self, source_root: Path, destination_root: Path, *,
                       includes=(), all_files: bool = False, exclusions=(), use_default_excludes: bool = True,
                       recursive: bool = True, conflict_policy: str = "error") -> OperationPlan:
        selected = patterns(includes)
        if type(all_files) is not bool or (not selected and not all_files) or (selected and all_files):
            raise PlanValidationError("Select include patterns or explicitly choose all_files=True (not both)")
        self._check_history_location(source_root, destination_root)
        source, destination = validate_roots(source_root, destination_root)
        scan = scan_tree(source, includes=selected, exclusions=exclusions,
                         use_default_excludes=use_default_excludes, recursive=recursive)
        require_complete(scan)
        if self.history_path is not None:
            reserved = self._history_files()
            if any(entry.path in reserved for entry in scan.files):
                raise PlanValidationError("History database must be outside source selections and destination roots; refine includes/exclusions")
        if selected and not scan.files:
            raise PlanValidationError("No files matched the selected include patterns after exclusions")
        plan = build_plan(source, destination, self.rules, files=[entry.path for entry in scan.files],
                          file_info=self.get_file_info, conflict_policy=conflict_policy)
        return replace(plan, includes=scan.includes, exclusions=scan.exclusions, all_files=all_files)

    def preview(self, plan: OperationPlan) -> List[FileOperation]:
        return preview_plan(plan)

    def apply(self, plan: OperationPlan, *, confirmed: bool = False) -> List[FileOperation]:
        self._check_history_location(plan.source_root, plan.destination_root, plan.operations)
        return execute_plan(plan, confirmed=confirmed, history_recorder=self.history_recorder)

    def _history_files(self) -> set[Path]:
        return {Path(str(self.history_path) + suffix) for suffix in ("", "-wal", "-shm", "-journal", ".scheduler.lock")}

    def _check_history_location(self, source_root: Path, destination_root: Path, operations=()) -> None:
        if self.history_path is not None and (self.history_path.is_relative_to(absolute_path(destination_root))
                or any(operation.source in self._history_files() for operation in operations)):
            raise PlanValidationError("History database must be outside source selections and destination roots")

    def organize_file(self, source: Path, rule: FileRule, *, destination_root: Path,
                      source_root: Path | None = None, confirmed: bool = False,
                      conflict_policy: str = "error") -> FileOperation:
        """Compatibility adapter: explicit roots and approval now use the shared contract."""
        source = Path(source)
        self._check_history_location(source_root or source.absolute().parent, destination_root)
        if self.history_path is not None and absolute_path(source) in self._history_files():
            raise PlanValidationError("History database must be outside source selections and destination roots")
        plan = build_plan(source_root or source.absolute().parent, destination_root, [rule],
                          files=[source], file_info=self.get_file_info,
                          conflict_policy=conflict_policy)
        return (self.preview(plan) if self.dry_run else self.apply(plan, confirmed=confirmed))[0]

    def organize_directory(self, source_dir: Path, *, destination_root: Path,
                           recursive: bool = True, confirmed: bool = False,
                           conflict_policy: str = "error", includes=(), all_files: bool = False,
                           exclusions=(), use_default_excludes: bool = True) -> List[FileOperation]:
        """Compatibility adapter; new callers should retain the plan for preview/apply."""
        plan = self.plan_directory(source_dir, destination_root, recursive=recursive,
                                   conflict_policy=conflict_policy, includes=includes, all_files=all_files,
                                   exclusions=exclusions, use_default_excludes=use_default_excludes)
        return self.preview(plan) if self.dry_run else self.apply(plan, confirmed=confirmed)

    def clean_empty_directories(self, directory: Path, recursive: bool = True):
        raise PlanValidationError("Unplanned directory cleanup is disabled; this phase plans regular files only")

    def generate_report(self, operations: List[FileOperation]) -> Dict[str, Any]:
        """Generate summary report of operations."""
        total = len(operations)
        successful = sum(1 for op in operations if op.status in ("success", "completed_with_errors"))
        failed = sum(1 for op in operations if op.status == "failed")
        skipped = sum(1 for op in operations if op.status == "skipped")
        dry_run = sum(1 for op in operations if op.status == "dry_run")

        total_size = sum(op.size_bytes for op in operations if op.status in ("success", "completed_with_errors", "dry_run"))

        return {
            "total_files": total,
            "history_failed": sum(op.history_status == "failed" for op in operations),
            "filesystem_changed": sum(op.destination_created or op.source_removed for op in operations),
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "dry_run": dry_run,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "timestamp": datetime.now().isoformat(),
        }
