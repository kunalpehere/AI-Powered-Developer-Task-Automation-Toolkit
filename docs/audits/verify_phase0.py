"""Reproduce the inherited snapshot's defects without changing application files.

Run from the workspace root: python -B docs/audits/verify_phase0.py
This is audit evidence, not a passing application regression suite. All filesystem
operations use a TemporaryDirectory. Subprocess checks have a 20-second limit.
"""
import ast
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def inventory():
    paths = sorted((ROOT / "taskmaster").rglob("*.py"))
    paths += [ROOT / "README.md", ROOT / "taskmaster/README.md"]
    return {str(p.relative_to(ROOT)).replace("\\", "/"):
            hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def command(args, cwd=ROOT):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                timeout=20, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return {"argv": args, "cwd": str(cwd), "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"argv": args, "cwd": str(cwd), "timeout_seconds": 20}


def main():
    before = inventory()
    recorded = ROOT / "docs/audits/phase0-results.json"
    if recorded.exists():
        original = json.loads(recorded.read_text(encoding="utf-8"))["inventory_sha256"]
        if before != original:
            raise SystemExit("Phase 0 collector requires the original snapshot. Current code has changed; "
                             "run tests/ for current regression checks. Historical results were preserved.")
    report = {"date": "2026-10-15", "python": sys.version, "inventory_sha256": before,
              "checks": {}}
    checks = report["checks"]
    report["installed_versions"] = {}
    for name in ("pip", "pytest", "rich", "setuptools", "Pillow", "PyPDF2"):
        try:
            report["installed_versions"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["installed_versions"][name] = None
    checks["parse"] = {}
    for path in sorted((ROOT / "taskmaster").rglob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            outcome = "parsed"
        except SyntaxError as error:
            outcome = {"line": error.lineno, "message": error.msg}
        checks["parse"][str(path.relative_to(ROOT))] = outcome
    checks["cli_help"] = command([sys.executable, "-B", "-m", "taskmaster", "--help"])
    checks["test_collection"] = command([sys.executable, "-B", "-m", "pytest",
                                         "--collect-only", "-q", "-p", "no:cacheprovider"])
    checks["git"] = command(["git", "rev-parse", "--is-inside-work-tree"])
    checks["package_discovery"] = command([sys.executable, "-B", "-c",
        "from setuptools import find_packages; print(find_packages())"], ROOT / "taskmaster")
    import taskmaster.plugins as plugins
    checks["plugin_import"] = {"loaded": str(Path(plugins.__file__).relative_to(ROOT)),
                               "has_PluginManager": hasattr(plugins, "PluginManager")}
    checks["readmes_identical"] = (ROOT / "README.md").read_bytes() == (ROOT / "taskmaster/README.md").read_bytes()
    checks["provenance_files"] = [p.name for p in ROOT.iterdir()
                                 if p.name.lower().startswith(("license", "copying", "attribution"))]

    # Extract only the syntactically valid parser method; never repair or import cli.py.
    source = (ROOT / "taskmaster/cli.py").read_text(encoding="utf-8")
    method = source[source.index("    def run_cli("):source.index("\ndef main():")]
    namespace = {}
    import argparse
    captured = {}

    class CaptureParser(argparse.ArgumentParser):
        def parse_args(self, *args, **kwargs):
            parsed = super().parse_args(*args, **kwargs)
            captured.update(vars(parsed))
            return parsed

    from typing import Optional, List
    namespace.update(argparse=SimpleNamespace(ArgumentParser=CaptureParser,
                     RawDescriptionHelpFormatter=argparse.RawDescriptionHelpFormatter),
                     Optional=Optional, List=List)
    method = "\n".join(line[4:] if line.startswith("    ") else line
                       for line in method.splitlines())
    exec(compile(method, "<isolated run_cli>", "exec"), namespace)
    namespace["run_cli"](object(), ["task", "add", "--name", "probe", "--command",
                                    "echo phase0", "--schedule", "2026-10-15 12:00"])
    checks["parser_dispatch"] = captured

    from taskmaster.database import Database
    from taskmaster.models import Task, FileRule
    from taskmaster.organizer import FileOrganizer
    from taskmaster.scheduler import TaskScheduler

    try:
        Database(":memory:").get_stats()
        checks["memory_database"] = "unexpected success"
    except Exception as error:
        checks["memory_database"] = f"{type(error).__name__}: {error}"

    # Keep fixtures inside the writable workspace on managed Windows hosts.
    with tempfile.TemporaryDirectory(prefix="phase0-fixtures-", dir=ROOT / "docs/audits") as temporary:
        base = Path(temporary).resolve()
        if not base.is_relative_to((ROOT / "docs/audits").resolve()):
            raise RuntimeError("Fixture cleanup target is outside the audit directory")
        db = Database(str(base / "audit.sqlite"))
        organizer = FileOrganizer(db)
        scheduler = TaskScheduler(db)
        try:
            candidates = base / "candidates"
            candidates.mkdir()
            (candidates / "a.bin").write_bytes(b"x" * 1024 + b"A")
            (candidates / "b.bin").write_bytes(b"x" * 1024 + b"B")
            quick = organizer.find_duplicates(candidates)
            full = organizer.find_duplicates(candidates, fast_mode=False)
            checks["duplicate_false_positive"] = {"quick_groups": len(quick), "full_groups": len(full),
                                                    "index_rows": db.get_stats()["indexed_files"]}
            checks["database_duplicate_members"] = [{"count": row["count"],
                "returned_path_fields": sum(key == "path" for key in row)} for row in db.find_duplicates()]
            source_path, target = base / "source.txt", base / "destination.txt"
            source_path.write_text("new", encoding="utf-8")
            target.write_text("existing", encoding="utf-8")
            op = organizer.organize_file(source_path, FileRule("copy", "*", str(target), action="copy"))
            checks["overwrite"] = {"status": op.status, "destination_contents": target.read_text()}
            op = organizer.organize_file(source_path, FileRule("invalid", "*", str(base / "absent.txt"), action="bogus"))
            checks["invalid_action"] = {"status": op.status, "source_preserved": source_path.exists()}
            checks["missing_source"] = len(organizer.scan_directory(base / "missing"))
            checks["size_template"] = str(organizer.apply_template("{size_category}/{name}.{ext}",
                                                     organizer.get_file_info(source_path)))
            history_before = db.get_stats()["file_operations"]
            organizer.dry_run = True
            with contextlib.redirect_stdout(io.StringIO()):
                op = organizer.organize_file(source_path, FileRule("preview", "*", str(base / "preview.txt")))
            checks["dry_run"] = {"status": op.status, "new_history_rows": db.get_stats()["file_operations"] - history_before,
                                 "source_preserved": source_path.exists(), "destination_created": (base / "preview.txt").exists()}
            with patch.object(organizer, "get_file_info", side_effect=PermissionError("simulated metadata denial")):
                try:
                    organizer.organize_file(source_path, FileRule("metadata", "*", str(target)))
                    checks["metadata_error"] = "unexpected success"
                except PermissionError as error:
                    checks["metadata_error"] = f"escaped: {error}"
            now = datetime.now()
            task = Task("future retry", lambda: None, now - timedelta(days=1), next_run=now + timedelta(days=1))
            db.save_task(task)
            checks["due_time"] = {"future_next_run_returned_as_due": task.id in {r["id"] for r in db.get_due_tasks(now)},
                                  "command_persisted": "command" in db.get_task(task.id)}

            async def focused_scheduler():
                # No background watcher, workers, sync command execution, or timeout probing.
                await scheduler._handle_failure(task, "phase0 synthetic failure")
                checks["failure_log"] = {"persisted": json.loads(db.get_task(task.id)["error_log"]),
                                         "fail_count": task.fail_count}
                blocked = Task("blocked", lambda: None, now, dependencies=["missing-dependency"])
                db.save_task(blocked)
                try:
                    await scheduler._execute_task(blocked)
                except Exception as error:
                    checks["blocked_dependency"] = {"error": str(error), "run_count": blocked.run_count,
                                                     "fail_count": blocked.fail_count, "status": blocked.status.name}

            # These selected paths complete without suspension: no event loop or
            # background service is started. Fail if that assumption changes.
            probe = focused_scheduler()
            try:
                probe.send(None)
            except StopIteration:
                pass
            else:
                probe.close()
                raise RuntimeError("Focused scheduler probe unexpectedly suspended")
        finally:
            organizer._executor.shutdown(wait=True)
            scheduler._executor.shutdown(wait=True)
    report["application_files_unchanged"] = before == inventory()
    output = ROOT / "docs/audits/phase0-results.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["application_files_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
