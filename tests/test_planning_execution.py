from dataclasses import FrozenInstanceError, replace
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from taskmaster.cli import main
from taskmaster.database import Database
from taskmaster.errors import ConfirmationRequired, PlanValidationError
from taskmaster.execution import execute_plan
from taskmaster.models import FileRule
from taskmaster.organizer import FileOrganizer


@pytest.fixture
def workspace(tmp_path):
    source, destination = tmp_path / "input", tmp_path / "output"
    source.mkdir()
    (source / "first.log").write_bytes(b"first log\n")
    organizer = FileOrganizer()
    organizer.add_rule(FileRule("logs", "*.log", "{filename}", action="copy"))
    try:
        yield organizer, source, destination
    finally:
        organizer.close()


def contents(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_plan_and_preview_are_read_only_and_immutable(workspace, tmp_path):
    organizer, source, destination = workspace
    before = contents(tmp_path)
    plan = organizer.plan_directory(source, destination, all_files=True)
    assert plan.source_root == source
    assert plan.destination_root == destination
    operation = plan.operations[0]
    assert operation.source_state.sha256 == hashlib.sha256(b"first log\n").hexdigest()
    assert operation.destination == destination / "first.log"
    with pytest.raises(FrozenInstanceError):
        operation.action = "delete"
    results = organizer.preview(plan)
    assert results[0].status == "dry_run"
    assert results[0].history_status == "not_requested"
    assert contents(tmp_path) == before
    assert not destination.exists()


def test_preview_and_duplicate_report_leave_existing_database_unchanged(workspace, tmp_path):
    _, source, destination = workspace
    db = Database(str(tmp_path / "history.sqlite"))
    organizer = FileOrganizer(db)
    organizer.add_rule(FileRule("logs", "*", "{filename}", action="copy"))
    (source / "second.log").write_bytes(b"first log\n")
    before = contents(tmp_path)
    try:
        organizer.preview(organizer.plan_directory(source, destination, all_files=True))
        assert len(organizer.find_duplicates(source)) == 1
        assert contents(tmp_path) == before
        assert db.get_stats()["file_operations"] == 0
        assert db.get_stats()["indexed_files"] == 0
        organizer.find_duplicates(source, record_index=True)
        assert db.get_stats()["indexed_files"] == 2
    finally:
        organizer.close()


@pytest.mark.parametrize("action", ["move", "rename", "delete"])
def test_destructive_actions_require_confirmation_before_any_mutation(workspace, tmp_path, action):
    organizer, source, destination = workspace
    organizer.rules = [FileRule("logs", "*", "{filename}", action=action)]
    recorder = Mock()
    plan = organizer.plan_directory(source, destination, all_files=True)
    before = contents(tmp_path)
    with pytest.raises(ConfirmationRequired):
        execute_plan(plan, history_recorder=recorder)
    assert contents(tmp_path) == before
    assert not destination.exists()
    recorder.assert_not_called()
    result = execute_plan(plan, confirmed=True)[0]
    assert result.status == "success"
    assert result.source_removed
    assert not (source / "first.log").exists()
    assert result.filesystem_status == {"move": "moved", "rename": "renamed", "delete": "deleted"}[action]
    assert result.destination_created == (action != "delete")


def test_mixed_copy_and_move_confirmation_is_batch_wide(workspace):
    organizer, source, destination = workspace
    (source / "other.txt").write_text("other")
    organizer.rules.append(FileRule("other", "*.txt", "{filename}", action="move"))
    plan = organizer.plan_directory(source, destination, all_files=True)
    with pytest.raises(ConfirmationRequired):
        organizer.apply(plan)
    assert not destination.exists()
    assert len(list(source.iterdir())) == 2


@pytest.mark.parametrize("template", ["{unknown}", "{name.upper}", "{name[0]}", "{name!r}",
    "{name:>20}", "{", ""])
def test_invalid_templates_fail_before_planning(workspace, template):
    organizer, source, destination = workspace
    organizer.rules = [FileRule("bad", "*", template)]
    with pytest.raises(PlanValidationError, match="template|placeholder"):
        organizer.plan_directory(source, destination, all_files=True)
    assert not destination.exists()


@pytest.mark.parametrize("template", ["../escape.log", "sub/../../escape.log", r"sub\..\escape.log",
    "C:escape.log", "NUL.txt", "stream:secret", "trailing."])
def test_destination_traversal_and_nonportable_components_are_rejected(workspace, template):
    organizer, source, destination = workspace
    organizer.rules = [FileRule("bad", "*", template, action="copy")]
    result = organizer.preview(organizer.plan_directory(source, destination, all_files=True))[0]
    assert result.status == "failed"
    assert not destination.exists()


def test_absolute_destination_outside_root_is_rejected(workspace, tmp_path):
    organizer, source, destination = workspace
    organizer.rules = [FileRule("escape", "*", str(tmp_path / "escape.log"), action="copy")]
    result = organizer.apply(organizer.plan_directory(source, destination, all_files=True))[0]
    assert result.status == "failed"
    assert "outside" in result.error
    assert not (tmp_path / "escape.log").exists()


@pytest.mark.parametrize("relationship", ["equal", "inside_source", "source_inside_destination"])
def test_overlapping_roots_are_rejected(workspace, tmp_path, relationship):
    organizer, source, destination = workspace
    root = {"equal": source, "inside_source": source / "output", "source_inside_destination": tmp_path}[relationship]
    with pytest.raises(PlanValidationError, match="overlap"):
        organizer.plan_directory(source, root, all_files=True)


def test_two_files_cannot_share_one_planned_destination(workspace):
    organizer, source, destination = workspace
    (source / "second.log").write_text("second")
    organizer.rules = [FileRule("collision", "*", "same.log", action="copy")]
    plan = organizer.plan_directory(source, destination, all_files=True)
    results = organizer.apply(plan)
    assert [r.status for r in results] == ["failed", "failed"]
    assert all("Multiple operations" in r.error for r in results)
    assert not destination.exists()


def test_same_size_content_change_with_restored_mtime_is_detected(workspace):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True)
    path = source / "first.log"
    before = path.stat()
    path.write_bytes(b"other log\n")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    result = organizer.apply(plan)[0]
    assert result.status == "failed"
    assert "changed since planning" in result.error
    assert not destination.exists()
    assert path.read_bytes() == b"other log\n"


def test_missing_source_does_not_hide_success_of_other_items(workspace):
    organizer, source, destination = workspace
    (source / "second.log").write_text("second")
    plan = organizer.plan_directory(source, destination, all_files=True)
    (source / "first.log").unlink()
    results = organizer.apply(plan)
    assert [r.status for r in results] == ["failed", "success"]
    assert results[0].filesystem_status == "unchanged"
    assert results[1].filesystem_status == "copied"
    assert (destination / "second.log").read_text() == "second"
    assert organizer.generate_report(results)["failed"] == 1


@pytest.mark.parametrize("policy,status", [("error", "failed"), ("skip", "skipped")])
def test_destination_appearing_after_plan_obeys_conflict_policy(workspace, policy, status):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True, conflict_policy=policy)
    destination.mkdir()
    (destination / "first.log").write_text("existing")
    result = organizer.apply(plan)[0]
    assert result.status == status
    assert result.filesystem_status == "unchanged"
    assert (destination / "first.log").read_text() == "existing"
    assert (source / "first.log").exists()


def test_existing_destination_skip_is_visible_in_plan(workspace):
    organizer, source, destination = workspace
    destination.mkdir()
    (destination / "first.log").write_text("existing")
    plan = organizer.plan_directory(source, destination, all_files=True, conflict_policy="skip")
    assert plan.operations[0].skipped_reason
    assert organizer.preview(plan)[0].status == "skipped"
    assert organizer.apply(plan)[0].status == "skipped"


def test_condition_skip_and_new_files_do_not_change_a_captured_plan(workspace):
    organizer, source, destination = workspace
    organizer.rules = [FileRule("condition", "*", "{filename}", condition=lambda _: False)]
    plan = organizer.plan_directory(source, destination, all_files=True)
    (source / "new.log").write_text("new")
    assert not plan.requires_confirmation
    results = organizer.apply(plan)
    assert len(results) == 1 and results[0].status == "skipped"
    assert not destination.exists()
    assert len(list(source.iterdir())) == 2


def test_history_failure_does_not_erase_successful_file_change(workspace):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True)
    recorder = Mock(side_effect=sqlite3.OperationalError("history disk full"))
    result = execute_plan(plan, history_recorder=recorder)[0]
    assert result.status == "completed_with_errors"
    assert result.filesystem_status == "copied"
    assert result.destination_created and not result.source_removed
    assert result.error is None
    assert result.history_status == "failed" and result.history_error == "history disk full"
    assert (destination / "first.log").read_bytes() == b"first log\n"
    report = organizer.generate_report([result])
    assert report["successful"] == 1 and report["history_failed"] == 1


def test_file_failure_and_history_failure_are_both_retained(workspace):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True)
    (source / "first.log").unlink()
    result = execute_plan(plan, history_recorder=Mock(side_effect=OSError("history denied")))[0]
    assert result.status == "failed" and result.error
    assert result.history_error == "history denied"
    assert result.filesystem_status == "unchanged"


def test_unlink_failure_reports_completed_copy_and_preserved_source(workspace, monkeypatch):
    organizer, source, destination = workspace
    organizer.rules[0].action = "move"
    plan = organizer.plan_directory(source, destination, all_files=True)
    real_unlink = Path.unlink

    def denied_unlink(path, *args, **kwargs):
        if path == source / "first.log":
            raise PermissionError("source unlink denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied_unlink)
    result = organizer.apply(plan, confirmed=True)[0]
    assert result.status == "failed"
    assert result.filesystem_status == "copied"
    assert result.destination_created and not result.source_removed
    assert "unlink denied" in result.error
    assert (source / "first.log").exists() and (destination / "first.log").exists()


def test_partial_write_failure_preserves_source_and_reports_new_file(workspace, monkeypatch):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True)
    real_open = Path.open

    class BrokenWriter:
        def __init__(self, file):
            self.file = file
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.file.close()
        def write(self, data):
            self.file.write(data[:3])
            raise OSError("simulated write failure")

    def broken_open(path, mode="r", *args, **kwargs):
        file = real_open(path, mode, *args, **kwargs)
        return BrokenWriter(file) if path == destination / "first.log" and mode == "xb" else file

    monkeypatch.setattr(Path, "open", broken_open)
    result = organizer.apply(plan)[0]
    assert result.status == "failed" and "write failure" in result.error
    assert result.filesystem_status == "partial" and result.destination_created
    assert result.checksum is None
    assert not result.source_removed
    assert (destination / "first.log").read_bytes() == b"fir"
    assert (source / "first.log").read_bytes() == b"first log\n"


def test_forged_source_escape_is_rejected_at_execution(workspace, tmp_path):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True)
    outside = tmp_path / "outside.log"
    outside.write_text("keep")
    forged = replace(plan.operations[0], source=source / ".." / "outside.log")
    result = organizer.apply(replace(plan, operations=(forged,)))[0]
    assert result.status == "failed" and "outside" in result.error
    assert outside.read_text() == "keep"
    assert not destination.exists()


def test_cli_preview_and_duplicate_report_create_no_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "input"
    source.mkdir()
    (source / "a.log").write_text("same")
    (source / "b.log").write_text("same")
    before = contents(tmp_path)
    assert main(["organize", "--all-files", "--source", "input", "--destination", "output"]) == 0
    assert main(["duplicates", "--dir", "input"]) == 0
    assert contents(tmp_path) == before
    assert not (tmp_path / "taskmaster.db").exists()
    assert not (tmp_path / "output").exists()


def test_cli_noninteractive_move_requires_explicit_approval(workspace, tmp_path, monkeypatch, capsys):
    _, source, destination = workspace
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["organize", "--all-files", "--source", str(source), "--destination", str(destination), "--apply"]) == 1
    assert "Confirmation required" in capsys.readouterr().out
    assert not destination.exists() and not (tmp_path / "taskmaster.db").exists()


def test_cli_reuses_displayed_plan_after_confirmation(workspace, tmp_path, monkeypatch, capsys):
    _, source, destination = workspace
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def approve(*args, **kwargs):
        (source / "first.log").write_text("changed after preview")
        return True

    monkeypatch.setattr("taskmaster.cli.Confirm.ask", approve)
    assert main(["organize", "--all-files", "--source", str(source), "--destination", str(destination), "--apply"]) == 1
    assert "changed since planning" in " ".join(capsys.readouterr().out.split())
    assert not destination.exists()


def test_cli_history_failure_returns_nonzero_with_file_success(workspace, tmp_path, monkeypatch, capsys):
    _, source, destination = workspace
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Database, "log_file_operation", Mock(side_effect=sqlite3.OperationalError("history full")))
    assert main(["organize", "--all-files", "--source", str(source), "--destination", str(destination),
                 "--action", "copy", "--apply"]) == 1
    output = capsys.readouterr().out
    assert "completed_with_errors" in output and "history full" in output
    assert (destination / "misc/first.log").exists()


def test_existing_phase1_database_is_upgraded_without_losing_history(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE file_operations (id TEXT PRIMARY KEY, source TEXT NOT NULL, "
            "destination TEXT, operation TEXT NOT NULL, status TEXT, timestamp TEXT, size_bytes INTEGER, "
            "checksum TEXT, error TEXT)")
        connection.execute("INSERT INTO file_operations (id,source,operation,status) VALUES ('old','x','copy','success')")
    db = Database(str(path))
    old = db.get_file_operations()[0]
    assert old["id"] == "old" and old["filesystem_status"] == "unknown"
    # Initialization is idempotent, including additive columns.
    Database(str(path))
    assert db.get_stats()["file_operations"] == 1


def test_new_history_records_filesystem_outcome(workspace, tmp_path):
    organizer, source, destination = workspace
    db = Database(str(tmp_path / "history.sqlite"))
    plan = organizer.plan_directory(source, destination, all_files=True)
    result = execute_plan(plan, history_recorder=db.log_file_operation)[0]
    record = db.get_file_operations()[0]
    assert result.history_status == record["history_status"] == "recorded"
    assert record["filesystem_status"] == "copied"
    assert record["destination_created"] == 1 and record["source_removed"] == 0


def make_directory_link(link, target):
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            pytest.skip(f"Junction creation unavailable: {result.stderr}")
    else:
        link.symlink_to(target, target_is_directory=True)


def remove_directory_link(link):
    if os.name == "nt":
        os.rmdir(link)  # Removes only the junction entry, never recurses into target.
    else:
        link.unlink()


def test_source_directory_link_is_rejected(workspace, tmp_path):
    organizer, source, destination = workspace
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.log").write_text("keep")
    link = source / "linked"
    make_directory_link(link, outside)
    try:
        with pytest.raises(PlanValidationError, match="junctions"):
            organizer.plan_directory(source, destination, all_files=True)
        assert (outside / "keep.log").read_text() == "keep"
    finally:
        remove_directory_link(link)


def test_destination_parent_link_introduced_after_plan_is_rejected(workspace, tmp_path):
    organizer, source, destination = workspace
    organizer.rules[0].destination_template = "nested/{filename}"
    plan = organizer.plan_directory(source, destination, all_files=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    destination.mkdir()
    link = destination / "nested"
    make_directory_link(link, outside)
    try:
        result = organizer.apply(plan)[0]
        assert result.status == "failed" and "junctions" in result.error
        assert not list(outside.iterdir())
        assert (source / "first.log").exists()
    finally:
        remove_directory_link(link)


def test_file_symlink_is_rejected_when_platform_allows_it(workspace):
    organizer, source, destination = workspace
    link = source / "linked.log"
    try:
        link.symlink_to(source / "first.log")
    except OSError as error:
        pytest.skip(f"File symlink creation unavailable: {error}")
    try:
        with pytest.raises(PlanValidationError, match="Symlinks"):
            organizer.plan_directory(source, destination, all_files=True)
    finally:
        link.unlink()


def test_unplanned_cleanup_cannot_bypass_preview(workspace):
    organizer, source, _ = workspace
    empty = source / "empty"
    empty.mkdir()
    organizer.dry_run = True
    with pytest.raises(PlanValidationError, match="Unplanned"):
        organizer.clean_empty_directories(source)
    assert empty.exists()


def test_source_reparse_point_introduced_after_plan_is_rejected(workspace, monkeypatch):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True)
    real_lstat = Path.lstat

    def reparse_lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == source / "first.log":
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    result = organizer.apply(plan)[0]
    assert result.status == "failed" and "reparse points" in result.error
    assert not destination.exists()


def test_apply_read_denial_is_reported_without_destination(workspace, monkeypatch):
    organizer, source, destination = workspace
    plan = organizer.plan_directory(source, destination, all_files=True)
    real_open = Path.open

    def denied_open(path, mode="r", *args, **kwargs):
        if path == source / "first.log" and mode == "rb":
            raise PermissionError("source read denied")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    result = organizer.apply(plan)[0]
    assert result.status == "failed" and "source read denied" in result.error
    assert not result.destination_created and not destination.exists()


def test_source_mutation_during_copy_prevents_source_removal(workspace, monkeypatch):
    organizer, source, destination = workspace
    organizer.rules[0].action = "move"
    plan = organizer.plan_directory(source, destination, all_files=True)
    real_open = Path.open

    class MutatingWriter:
        def __init__(self, writer):
            self.writer = writer
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.writer.close()
        def write(self, data):
            result = self.writer.write(data)
            (source / "first.log").write_bytes(b"changed after read")
            return result

    def mutating_open(path, mode="r", *args, **kwargs):
        file = real_open(path, mode, *args, **kwargs)
        return MutatingWriter(file) if path == destination / "first.log" and mode == "xb" else file

    monkeypatch.setattr(Path, "open", mutating_open)
    result = organizer.apply(plan, confirmed=True)[0]
    assert result.status == "failed" and "changed" in result.error
    assert result.destination_created and not result.source_removed
    assert (source / "first.log").read_bytes() == b"changed after read"


def test_interactive_decline_leaves_files_and_history_unchanged(workspace, tmp_path, monkeypatch):
    _, source, destination = workspace
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("taskmaster.cli.Confirm.ask", lambda *args, **kwargs: False)
    before = contents(tmp_path)
    assert main(["organize", "--all-files", "--source", str(source), "--destination", str(destination), "--apply"]) == 0
    assert contents(tmp_path) == before
    assert not destination.exists()


def test_invalid_conflict_policy_is_actionable(workspace):
    organizer, source, destination = workspace
    with pytest.raises(PlanValidationError, match="conflict policy"):
        organizer.plan_directory(source, destination, all_files=True, conflict_policy="overwrite")


def test_confirmation_cannot_be_a_truthy_string(workspace):
    organizer, source, destination = workspace
    organizer.rules[0].action = "move"
    plan = organizer.plan_directory(source, destination, all_files=True)
    with pytest.raises(PlanValidationError, match="boolean"):
        organizer.apply(plan, confirmed="false")
    assert not destination.exists()


def test_history_file_cannot_be_selected_for_organization(workspace):
    _, source, destination = workspace
    db = Database(str(source / "history.sqlite"))
    organizer = FileOrganizer(db)
    try:
        with pytest.raises(PlanValidationError, match="History database must be outside"):
            organizer.plan_directory(source, destination, all_files=True)
        assert db.get_stats()["file_operations"] == 0
    finally:
        organizer.close()
