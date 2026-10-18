import hashlib
import json
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from taskmaster.cli import main
from taskmaster.database import Database
from taskmaster.duplicates import duplicate_report
from taskmaster.errors import PlanValidationError
from taskmaster.inspection import inspect_project
from taskmaster.organizer import FileOrganizer
from taskmaster.planning import expand_template, source_state
from taskmaster.scanning import matches, patterns, scan_tree


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    entries = {
        "src/main.py": b"print('hi')\n", "logs/app.log": b"log\n",
        "logs/archive/app.log": b"log\n", "reports/总结.csv": b"one,two\n",
        "LICENSE": b"license", "empty/a": b"", "empty/b": b"",
        ".git/config": b"git", "venv/skip.py": b"skip", "node_modules/pkg/x.js": b"skip",
        "nested/__pycache__/byte.pyc": b"skip",
    }
    for name, data in entries.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_inspection_counts_extensions_largest_and_exclusions(project):
    before = tree(project)
    report = inspect_project(project, top=3, min_size=4)
    assert report["complete"]
    assert report["summary"]["file_count"] == 7
    assert report["summary"]["size_bytes"] == sum(len(before[name]) for name in (
        "src/main.py", "logs/app.log", "logs/archive/app.log", "reports/总结.csv", "LICENSE", "empty/a", "empty/b"))
    extensions = {item["extension"]: item["file_count"] for item in report["extensions"]}
    assert extensions == {"": 3, ".csv": 1, ".log": 2, ".py": 1}
    assert [item["path"] for item in report["largest_files"]] == ["src/main.py", "reports/总结.csv", "LICENSE"]
    assert report == inspect_project(project, top=3, min_size=4)
    assert tree(project) == before


def test_custom_exclusions_and_default_override(project):
    assert inspect_project(project, exclusions=("logs/", "*.csv"))["summary"]["file_count"] == 4
    assert inspect_project(project, use_default_excludes=False)["summary"]["file_count"] == 11
    assert inspect_project(project, includes=("logs/**/*.log",))["summary"]["file_count"] == 2
    assert inspect_project(project, recursive=False)["summary"]["file_count"] == 1


@pytest.mark.parametrize("relative,pattern,expected", [
    ("logs/app.log", "logs/**/*.log", True), ("logs/archive/app.log", "logs/**/*.log", True),
    ("logs/deep/nested/a.log", "logs/**/*.log", True), ("src/a.log", "logs/**/*.log", False),
    ("reports/a.csv", "reports/*.csv", True), ("reports/nested/a.csv", "reports/*.csv", False),
    ("nested/a.log", "*.log", True), ("nested/a.LOG", "*.log", False),
    ("cache/nested/a", "cache/", True), ("logs/app.log", r"logs\*.log", True),
])
def test_scope_glob_semantics(relative, pattern, expected):
    assert matches(relative, patterns((pattern,))[0]) is expected


@pytest.mark.parametrize("invalid", ["", " ", "../*", "/absolute", "C:relative", "foo//bar", "foo/../bar", "."])
def test_invalid_patterns_are_actionable(invalid):
    with pytest.raises(PlanValidationError, match="pattern|Patterns"):
        patterns((invalid,))


def test_patterns_are_not_silently_split_into_characters(project):
    with pytest.raises(PlanValidationError, match="sequence"):
        scan_tree(project, exclusions="logs")


def test_excluded_directories_are_pruned_before_link_checks(project, monkeypatch):
    from taskmaster import scanning
    actual = scanning.reject_links

    def checked(path):
        assert path.name not in {".git", "venv", "node_modules", "__pycache__"}
        return actual(path)

    monkeypatch.setattr(scanning, "reject_links", checked)
    assert inspect_project(project)["complete"]


def test_duplicate_candidates_only_are_hashed_and_empty_groups_are_verified(project):
    calls = []

    def hash_file(path):
        calls.append(path.relative_to(project).as_posix())
        return source_state(path).sha256

    report = duplicate_report(project, checksum=hash_file)
    assert report["complete"]
    assert report["summary"]["candidate_files"] == report["summary"]["hashed_files"] == 4
    assert sorted(calls) == ["empty/a", "empty/b", "logs/app.log", "logs/archive/app.log"]
    assert report["summary"]["duplicate_groups"] == 2
    assert report["summary"]["redundant_bytes"] == 4
    assert report["groups"][1] == {"sha256": hashlib.sha256(b"").hexdigest(),
                                   "size_bytes": 0, "paths": ["empty/a", "empty/b"]}


def test_equal_size_matching_prefix_still_requires_complete_hash(tmp_path):
    for name, tail in (("a.bin", b"A"), ("b.bin", b"B")):
        (tmp_path / name).write_bytes(b"x" * 1024 + tail)
    report = duplicate_report(tmp_path)
    assert report["summary"]["hashed_files"] == 2
    assert report["groups"] == []


def test_unique_size_does_not_read_content(tmp_path, monkeypatch):
    (tmp_path / "unique.log").write_text("only one file")
    hasher = Mock(side_effect=AssertionError("A unique-size file is not a candidate"))
    assert duplicate_report(tmp_path, checksum=hasher)["summary"]["hashed_files"] == 0
    hasher.assert_not_called()


def test_duplicate_read_failure_is_reported_alongside_verified_groups(project, monkeypatch):
    actual = Path.open

    def denied(path, mode="r", *args, **kwargs):
        if path == project / "logs/app.log" and mode == "rb":
            raise PermissionError("read denied")
        return actual(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    report = duplicate_report(project)
    assert not report["complete"] and report["summary"]["error_count"] == 1
    assert report["errors"][0]["error"] == "read denied"
    assert report["summary"]["duplicate_groups"] == 1  # The readable empty-file group remains valid.


def test_changed_size_candidate_is_not_reported_as_verified(tmp_path):
    for name in ("a.log", "b.log"):
        (tmp_path / name).write_text("same")

    def changing_hasher(path):
        digest = source_state(path).sha256
        if path.name == "a.log":
            path.write_text("changed while hashing")
        return digest

    report = duplicate_report(tmp_path, checksum=changing_hasher)
    assert not report["complete"] and report["groups"] == []
    assert "changed" in report["errors"][0]["error"]


def test_inspection_stat_error_is_visible_and_prevents_organization(project, tmp_path, monkeypatch, capsys):
    actual = Path.stat

    def denied(path, *args, **kwargs):
        if path == project / "logs/app.log":
            raise PermissionError("metadata denied")
        return actual(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    report = inspect_project(project)
    assert not report["complete"] and report["summary"]["file_count"] == 6
    assert "metadata denied" in report["errors"][0]["error"]
    assert main(["inspect", "--source", str(project), "--format", "json"]) == 1
    assert not json.loads(capsys.readouterr().out)["complete"]
    organizer = FileOrganizer()
    try:
        with pytest.raises(PlanValidationError, match="Scan incomplete"):
            organizer.plan_directory(project, tmp_path / "out", includes=("logs/**/*.log",))
        assert not (tmp_path / "out").exists()
    finally:
        organizer.close()


def test_walk_permission_error_marks_summary_incomplete(project, monkeypatch):
    from taskmaster import scanning

    def walk(root, *, followlinks, onerror):
        yield str(root), [], ["LICENSE"]
        onerror(PermissionError(13, "directory denied", str(root / "private")))

    monkeypatch.setattr(scanning.os, "walk", walk)
    report = inspect_project(project)
    assert not report["complete"] and report["summary"]["file_count"] == 1
    assert "private" in report["errors"][0]["path"]


def test_selection_is_required_and_unmatched_rules_never_move_files(project, tmp_path):
    organizer = FileOrganizer()
    before = tree(project)
    try:
        with pytest.raises(PlanValidationError, match="Select include"):
            organizer.plan_directory(project, tmp_path / "out")
        with pytest.raises(PlanValidationError, match="No files matched"):
            organizer.plan_directory(project, tmp_path / "out", includes=("*.missing",))
        plan = organizer.plan_directory(project, tmp_path / "out", includes=("logs/**/*.log",))
        assert len(plan.operations) == 2
        assert all(item.status == "skipped" for item in organizer.apply(plan))
        assert tree(project) == before
        assert not (tmp_path / "out").exists()
    finally:
        organizer.close()


@pytest.mark.parametrize("size,expected", [(0, "small"), (1048575, "small"), (1048576, "medium"),
    (104857599, "medium"), (104857600, "large")])
def test_size_strategy_exact_boundaries(size, expected):
    info = {"stem": "file", "name": "file", "extension": "", "category": "misc",
            "mime_type": "unknown", "size": size}
    assert expand_template("{size_category}/{filename}", info) == Path(expected) / "file"


def test_json_inspection_and_duplicates_are_complete_deterministic_documents(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    before = tree(project)
    for command in (["inspect", "--source", "."], ["duplicates", "--dir", "."]):
        assert main([*command, "--format", "json"]) == 0
        first = capsys.readouterr().out
        report = json.loads(first)
        assert report["complete"] and report["schema_version"] == 1
        assert main([*command, "--format", "json"]) == 0
        assert capsys.readouterr().out == first
    assert tree(project) == before
    assert not (project / "taskmaster.db").exists()


def test_selected_artifacts_copy_and_move_without_touching_source_code(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(project)
    before = tree(project)
    flags = ["organize", "--source", ".", "--include", "logs/**/*.log", "--include", "reports/**",
             "--include", "LICENSE", "--format", "json"]
    copy_target, move_target = tmp_path / "copy", tmp_path / "move"
    assert main([*flags, "--destination", str(copy_target)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "preview" and len(report["operations"]) == 4
    assert tree(project) == before and not copy_target.exists()
    assert main([*flags, "--destination", str(copy_target), "--action", "copy", "--apply"]) == 0
    copied = json.loads(capsys.readouterr().out)
    assert copied["summary"]["successful"] == 4
    assert (copy_target / "data/reports/总结.csv").read_bytes() == before["reports/总结.csv"]
    assert (copy_target / "misc/LICENSE").read_bytes() == before["LICENSE"]
    assert (copy_target / "misc/logs/archive/app.log").read_bytes() == before["logs/archive/app.log"]
    assert all((project / name).read_bytes() == data for name, data in before.items())
    # The history database now lives within the project, but outside the explicit selection.
    assert (project / "taskmaster.db").exists()
    assert main([*flags, "--destination", str(move_target), "--apply", "--yes"]) == 0
    moved = json.loads(capsys.readouterr().out)
    assert moved["mode"] == "apply" and all(item["source_removed"] for item in moved["operations"])
    assert (project / "src/main.py").read_bytes() == before["src/main.py"]
    assert (project / ".git/config").read_bytes() == before[".git/config"]
    assert not (project / "logs/app.log").exists()


def test_all_files_remains_explicit_and_still_respects_default_exclusions(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["organize", "--source", str(project), "--destination", str(tmp_path / "out"),
                 "--all-files", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scope"]["all_files"] and len(report["operations"]) == 7
    assert not (tmp_path / "out").exists()


def test_json_apply_never_prompts_and_requires_explicit_move_approval(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("taskmaster.cli.Confirm.ask", Mock(side_effect=AssertionError("JSON must not prompt")))
    assert main(["organize", "--source", str(project), "--destination", str(tmp_path / "out"),
                 "--include", "*.log", "--apply", "--format", "json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["complete"] and "Confirmation required" in report["error"]
    assert not (tmp_path / "taskmaster.db").exists()


def test_json_history_failure_keeps_the_file_outcome(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Database, "log_file_operation", Mock(side_effect=sqlite3.OperationalError("disk full")))
    destination = tmp_path / "out"
    assert main(["organize", "--source", str(project), "--destination", str(destination),
                 "--include", "logs/app.log", "--action", "copy", "--apply", "--format", "json"]) == 1
    report = json.loads(capsys.readouterr().out)
    result = report["operations"][0]
    assert not report["complete"] and result["status"] == "completed_with_errors"
    assert result["filesystem_status"] == "copied" and result["history_error"] == "disk full"
    assert (destination / "misc/logs/app.log").exists()


@pytest.mark.parametrize("options", [["inspect", "--source", "missing"],
    ["inspect", "--source", ".", "--top", "-1"],
    ["duplicates", "--dir", ".", "--exclude", "../bad"]])
def test_json_runtime_errors_are_valid_documents(tmp_path, monkeypatch, capsys, options):
    monkeypatch.chdir(tmp_path)
    assert main([*options, "--format", "json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["complete"] and report["error"]
    assert not (tmp_path / "taskmaster.db").exists()


def test_cli_read_error_returns_json_and_nonzero(project, monkeypatch, capsys):
    actual = Path.open

    def denied(path, mode="r", *args, **kwargs):
        if path == project / "logs/app.log" and mode == "rb":
            raise PermissionError("candidate denied")
        return actual(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    assert main(["duplicates", "--dir", str(project), "--format", "json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["complete"] and report["errors"][0]["error"] == "candidate denied"


def test_human_reports_and_empty_workflows(tmp_path, monkeypatch, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["inspect", "--source", str(root)]) == 0
    assert "Files: 0" in capsys.readouterr().out
    assert main(["duplicates", "--dir", str(root)]) == 0
    assert "Found 0 duplicate groups" in capsys.readouterr().out
    assert main(["organize", "--source", str(root), "--destination", "out", "--all-files", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["operations"] == []
    assert not (tmp_path / "out").exists()


def test_size_strategy_is_available_for_selected_files(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["organize", "--source", str(project), "--destination", "out", "--include", "*.log",
                 "--strategy", "size", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert all("small" in Path(item["destination"]).parts for item in report["operations"])
    assert len({item["destination"] for item in report["operations"]}) == 2


def test_module_cli_workflows_with_spaces_unicode_and_json(project, tmp_path):
    # Source integration test; wheel installation is verified separately outside
    # the checkout with PYTHONPATH removed.
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    def run(args, code=0):
        result = subprocess.run([sys.executable, "-B", "-m", "taskmaster", *args], cwd=tmp_path,
                                env=environment, capture_output=True, text=True, timeout=30)
        assert result.returncode == code, result.stderr + result.stdout
        return json.loads(result.stdout)

    assert run(["inspect", "--source", str(project), "--format", "json"])["summary"]["file_count"] == 7
    assert run(["duplicates", "--dir", str(project), "--format", "json"])["summary"]["duplicate_groups"] == 2
    destination = tmp_path / "output with spaces"
    report = run(["organize", "--source", str(project), "--destination", str(destination),
                  "--include", "reports/**", "--action", "copy", "--apply", "--format", "json"])
    assert report["mode"] == "apply" and report["summary"]["successful"] == 1
    assert (destination / "data/reports/总结.csv").exists()
    run(["inspect", "--source", "missing", "--format", "json"], code=1)


@pytest.mark.parametrize("command", ["inspect", "duplicates", "organize"])
def test_readable_reports_work_with_unicode_paths_and_cp1252_pipes(project, tmp_path, command):
    (project / "reports/副本.csv").write_bytes((project / "reports/总结.csv").read_bytes())
    options = {"inspect": ["--source", str(project)],
               "duplicates": ["--dir", str(project)],
               "organize": ["--source", str(project), "--destination", str(tmp_path / "out"),
                            "--include", "reports/**"]}
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                   "PYTHONIOENCODING": "cp1252:strict"}
    result = subprocess.run([sys.executable, "-B", "-m", "taskmaster", command, *options[command]],
                            cwd=tmp_path, env=environment, capture_output=True, encoding="cp1252", timeout=30)
    assert result.returncode == 0, result.stderr
    assert r"\u603b\u7ed3.csv" in result.stdout
    assert not (tmp_path / "out").exists()
