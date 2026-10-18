from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
from unittest.mock import Mock

import pytest

from taskmaster.cli import TaskMasterCLI, main
from taskmaster.config import load_workflow, parse_workflow, validate_workflow
from taskmaster.database import Database
from taskmaster.errors import ConfirmationRequired, PlanValidationError
from taskmaster.operations import normalize_parameters, prepare_operation, run_prepared
from taskmaster.workflows import run_workflow


def document(steps=None, policy="stop"):
    return {"version": 1, "name": "Artifact review", "on_failure": policy,
            "steps": steps if steps is not None else [
                {"id": "inspect", "operation": "inspect", "parameters": {"source": ".", "includes": ["*.log"]}},
                {"id": "duplicates", "operation": "duplicates", "parameters": {"source": ".", "includes": ["*.log"]}},
                {"id": "copy", "operation": "organize", "parameters": {"source": ".", "destination": "../output",
                    "includes": ["*.log"], "action": "copy"}}]}


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.log").write_bytes(b"same log\n")
    (root / "b.log").write_bytes(b"same log\n")
    path = root / "workflow.json"
    path.write_text(json.dumps(document()), encoding="utf-8")
    return root, path, tmp_path / "history.sqlite"


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_configuration_round_trip_normalizes_without_mutating_input():
    value = document()
    before = deepcopy(value)
    workflow = validate_workflow(value)
    assert value == before
    assert parse_workflow(workflow.to_json()) == workflow
    assert len(workflow.fingerprint) == 64
    parameters = workflow.steps[0].parameters
    parameters["includes"].append("*.py")
    assert workflow.steps[0].parameters["includes"] == ["*.log"]


@pytest.mark.parametrize("text", ["{", "[]", '{"version":true}', '{"version":1,"version":1}',
    '{"version":1,"name":"a","steps":NaN}', '{"secret":"never-echo-this",', "[" * 2000])
def test_invalid_json_does_not_echo_document_values(text):
    with pytest.raises(PlanValidationError) as error:
        parse_workflow(text)
    assert "never-echo-this" not in str(error.value)


@pytest.mark.parametrize("change", [
    lambda d: d.update(version=2), lambda d: d.update(version=True), lambda d: d.update(name=""),
    lambda d: d.update(on_failure="retry"), lambda d: d.update(steps=[]), lambda d: d.update(steps={}),
    lambda d: d.update(secret="never-echo-this"), lambda d: d["steps"][0].update(operation="shell"),
    lambda d: d["steps"][0].update(id="../unsafe"), lambda d: d["steps"][1].update(id="inspect"),
    lambda d: d["steps"][0].pop("parameters"),
    lambda d: d["steps"][0].update(parameters={"source": ".", "api_key": "never-echo-this"}),
])
def test_invalid_workflow_shapes_are_rejected(change):
    value = document()
    change(value)
    with pytest.raises(PlanValidationError) as error:
        validate_workflow(value)
    assert "never-echo-this" not in str(error.value)


@pytest.mark.parametrize("operation,parameters", [
    ("inspect", {"source": ".", "top": True}), ("inspect", {"source": ".", "top": -1}),
    ("inspect", {"source": ".", "min_size": 1.5}), ("inspect", {"source": ".", "recursive": "true"}),
    ("duplicates", {"source": ".", "includes": "*.log"}),
    ("duplicates", {"source": ".", "exclusions": [None]}),
    ("duplicates", {"source": "https://user:never-echo-this@example.test"}),
    ("duplicates", {"source": ".", "command": "never-echo-this"}),
    ("organize", {"source": ".", "destination": "../out"}),
    ("organize", {"source": ".", "destination": "../out", "all_files": "true"}),
    ("organize", {"source": ".", "destination": "../out", "all_files": True, "includes": ["*.log"]}),
    ("organize", {"source": ".", "destination": "../out", "all_files": True, "action": "delete"}),
    ("organize", {"source": ".", "destination": "../out", "all_files": True, "conflict_policy": "overwrite"}),
    ("organize", {"source": ".", "destination": "../out", "all_files": True, "template": "{unknown}"}),
])
def test_shared_parameter_validation_rejects_bad_types_and_unsafe_options(operation, parameters):
    with pytest.raises(PlanValidationError) as error:
        normalize_parameters(operation, parameters)
    assert "never-echo-this" not in str(error.value)


def test_bom_and_configuration_size_limit(workspace):
    _, path, _ = workspace
    path.write_text(json.dumps(document()), encoding="utf-8-sig")
    assert load_workflow(path).name == "Artifact review"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(PlanValidationError, match="1 MiB"):
        load_workflow(path)


def test_entire_configuration_is_validated_before_any_execution(workspace, tmp_path):
    root, _, history = workspace
    value = document()
    value["steps"].append({"id": "invalid", "operation": "shell", "parameters": {}})
    before = snapshot(tmp_path)
    with pytest.raises(PlanValidationError):
        validate_workflow(value)
    assert snapshot(tmp_path) == before and not history.exists()


def test_preview_is_read_only_with_uuid_and_complete_step_reports(workspace, tmp_path):
    root, path, history = workspace
    before = snapshot(tmp_path)
    factory = Mock(side_effect=AssertionError("Preview must never initialize persistence"))
    report = run_workflow(load_workflow(path), base_dir=root, history_path=history, config_path=path,
                          database_factory=factory)
    assert report["complete"] and report["mode"] == "preview"
    assert str(uuid.UUID(report["run_id"])) == report["run_id"]
    assert report["summary"]["successful_steps"] == 3
    assert report["steps"][1]["report"]["summary"]["duplicate_groups"] == 1
    assert report["steps"][2]["report"]["mode"] == "preview"
    assert report["history"]["status"] == "not_requested"
    factory.assert_not_called()
    assert snapshot(tmp_path) == before


def test_apply_persists_runs_steps_and_linked_file_outcomes(workspace, tmp_path):
    root, path, history = workspace
    workflow = load_workflow(path)
    report = run_workflow(workflow, base_dir=root, history_path=history, config_path=path, apply=True)
    assert report["complete"] and report["status"] == "success"
    assert (tmp_path / "output/misc/a.log").read_bytes() == b"same log\n"
    assert (root / "a.log").exists()
    stored = Database.read_runs(str(history), run_id=report["run_id"])
    assert stored == report
    db = Database(str(history))
    operations = db.get_file_operations()
    assert len(operations) == 2
    assert {entry["run_id"] for entry in operations} == {report["run_id"]}
    assert {entry["step_id"] for entry in operations} == {"copy"}
    assert all(str(uuid.UUID(entry["id"])) == entry["id"] for entry in operations)
    with sqlite3.connect(history) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_steps").fetchone()[0] == 3
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    second = run_workflow(workflow, base_dir=root, history_path=history, apply=True)
    assert second["run_id"] != report["run_id"]
    assert not second["complete"]  # Copy conflicts remain failures, never overwrites.


@pytest.mark.parametrize("policy,expected", [("stop", ["failed", "not_run"]), ("continue", ["failed", "success"])])
def test_step_failure_policy_uses_actual_outcomes(workspace, policy, expected):
    root, _, history = workspace
    config = document([
        {"id": "missing", "operation": "inspect", "parameters": {"source": "missing"}},
        {"id": "valid", "operation": "inspect", "parameters": {"source": "."}}], policy)
    report = run_workflow(validate_workflow(config), base_dir=root, history_path=history, apply=True)
    assert not report["complete"] and [step["status"] for step in report["steps"]] == expected
    assert Database.read_runs(str(history), run_id=report["run_id"])["steps"] == report["steps"]


def test_later_steps_see_outputs_of_earlier_steps(workspace, tmp_path):
    root, _, history = workspace
    copy_step = document()["steps"][2]
    value = document([copy_step, {"id": "inspect_output", "operation": "inspect", "parameters": {"source": "../output"}}])
    preview = run_workflow(validate_workflow(value), base_dir=root, history_path=history)
    assert not preview["complete"] and not history.exists()  # Preview does not simulate copies.
    applied = run_workflow(validate_workflow(value), base_dir=root, history_path=history, apply=True)
    assert applied["complete"] and applied["steps"][1]["report"]["summary"]["file_count"] == 2


def test_move_approval_happens_before_history_or_any_step(workspace, tmp_path):
    root, _, history = workspace
    value = document()
    value["steps"][2]["parameters"]["action"] = "move"
    workflow = validate_workflow(value)
    before = snapshot(tmp_path)
    with pytest.raises(ConfirmationRequired):
        run_workflow(workflow, base_dir=root, history_path=history, apply=True)
    assert snapshot(tmp_path) == before
    applied = run_workflow(workflow, base_dir=root, history_path=history, apply=True, confirmed=True)
    assert applied["complete"] and not (root / "a.log").exists()


def test_start_journal_failure_prevents_file_changes(workspace, tmp_path, monkeypatch):
    root, _, history = workspace
    monkeypatch.setattr(Database, "start_run", Mock(side_effect=sqlite3.OperationalError("start denied")))
    report = run_workflow(validate_workflow(document()), base_dir=root, history_path=history, apply=True)
    assert not report["complete"] and report["history"]["errors"][0]["code"] == "history_start_failed"
    assert all(step["status"] == "not_run" for step in report["steps"])
    assert not (tmp_path / "output").exists()


def test_file_history_failure_retains_success_and_stops_later_step(workspace, tmp_path, monkeypatch):
    root, _, history = workspace
    value = document([document()["steps"][2], {"id": "after", "operation": "inspect", "parameters": {"source": "."}}])
    monkeypatch.setattr(Database, "log_file_operation", Mock(side_effect=sqlite3.OperationalError("file history full")))
    report = run_workflow(validate_workflow(value), base_dir=root, history_path=history, apply=True)
    assert [step["status"] for step in report["steps"]] == ["failed", "not_run"]
    outcomes = report["steps"][0]["report"]["operations"]
    assert all(entry["status"] == "completed_with_errors" and entry["filesystem_status"] == "copied" for entry in outcomes)
    assert (tmp_path / "output/misc/a.log").exists()
    assert report["summary"]["history_failures"] == 2


def test_step_journal_failure_is_not_a_file_rollback(workspace, tmp_path, monkeypatch):
    root, _, history = workspace
    actual = Database.save_run_step

    def denied_finish(database, run_id, position, step):
        if step["status"] != "running":
            raise sqlite3.OperationalError("step history denied")
        return actual(database, run_id, position, step)

    monkeypatch.setattr(Database, "save_run_step", denied_finish)
    value = document([document()["steps"][2]])
    report = run_workflow(validate_workflow(value), base_dir=root, history_path=history, apply=True)
    assert not report["complete"] and report["steps"][0]["status"] == "failed"
    assert report["steps"][0]["report"]["summary"]["successful"] == 2
    assert (tmp_path / "output/misc/a.log").exists()


def test_step_start_history_failure_prevents_the_step(workspace, tmp_path, monkeypatch):
    root, _, history = workspace
    monkeypatch.setattr(Database, "save_run_step", Mock(side_effect=sqlite3.OperationalError("start denied")))
    report = run_workflow(validate_workflow(document([document()["steps"][2]])),
                          base_dir=root, history_path=history, apply=True)
    assert not report["complete"] and report["steps"][0]["status"] == "not_run"
    assert report["history"]["errors"][0]["code"] == "history_step_start_failed"
    assert not (tmp_path / "output").exists()


def test_interrupted_step_remains_running_in_history(workspace, monkeypatch):
    root, _, history = workspace
    monkeypatch.setattr("taskmaster.workflows.run_prepared", Mock(side_effect=KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        run_workflow(validate_workflow(document()), base_dir=root, history_path=history, apply=True)
    run_id = Database.read_runs(str(history))[0]["run_id"]
    stored = Database.read_runs(str(history), run_id=run_id)
    assert stored["status"] == "running" and not stored["complete"]
    assert stored["steps"][0]["status"] == "running"
    assert stored["summary"]["running_steps"] == 1


@pytest.mark.parametrize("policy,last_status", [("stop", "not_run"), ("continue", "success")])
def test_partial_file_batch_is_reported_before_next_step_policy(workspace, tmp_path, policy, last_status):
    root, _, history = workspace
    existing = tmp_path / "output/misc/a.log"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"preserve")
    value = document([document()["steps"][2],
        {"id": "after", "operation": "inspect", "parameters": {"source": ".", "includes": ["*.log"]}}], policy)
    report = run_workflow(validate_workflow(value), base_dir=root, history_path=history, apply=True)
    assert not report["complete"]
    assert report["steps"][0]["report"]["summary"]["successful"] == 1
    assert report["steps"][0]["report"]["summary"]["failed"] == 1
    assert report["steps"][1]["status"] == last_status
    assert existing.read_bytes() == b"preserve"
    assert (tmp_path / "output/misc/b.log").read_bytes() == b"same log\n"


def test_final_journal_failure_leaves_running_record_and_reports_file_success(workspace, tmp_path, monkeypatch):
    root, _, history = workspace
    monkeypatch.setattr(Database, "finish_run", Mock(side_effect=sqlite3.OperationalError("final history denied")))
    report = run_workflow(validate_workflow(document()), base_dir=root, history_path=history, apply=True)
    assert not report["complete"] and report["status"] == "completed_with_errors"
    assert all(step["status"] == "success" for step in report["steps"])
    stored = Database.read_runs(str(history), run_id=report["run_id"])
    assert stored["status"] == "running" and not stored["complete"]
    assert stored["steps"][2]["report"]["summary"]["successful"] == 2
    assert (tmp_path / "output/misc/a.log").exists()


def test_common_secret_diagnostics_are_redacted_from_history_and_logs(workspace, monkeypatch, caplog):
    root, _, history = workspace
    secret = "never-echo-this"
    monkeypatch.setattr(Database, "log_file_operation", Mock(side_effect=OSError(f"api_key={secret} token={secret}")))
    caplog.set_level(logging.INFO)
    report = run_workflow(validate_workflow(document()), base_dir=root, history_path=history, apply=True)
    assert secret not in json.dumps(report) and secret not in caplog.text
    assert "[REDACTED]" in json.dumps(report)
    assert secret.encode() not in history.read_bytes()


def test_workflow_file_cannot_be_selected_as_an_artifact(workspace, tmp_path):
    root, path, history = workspace
    value = document([{"id": "unsafe", "operation": "organize", "parameters": {
        "source": ".", "destination": "../output", "includes": ["workflow.json"], "action": "move"}}])
    before = path.read_bytes()
    report = run_workflow(validate_workflow(value), base_dir=root, config_path=path,
                          history_path=history, apply=True, confirmed=True)
    assert not report["complete"] and "configuration file" in report["steps"][0]["diagnostics"][0]["message"]
    assert path.read_bytes() == before and not (tmp_path / "output").exists()


def test_history_read_does_not_create_or_migrate_databases(tmp_path):
    path = tmp_path / "history.sqlite"
    assert Database.read_runs(str(path)) == [] and not path.exists()
    with pytest.raises(ValueError, match="Run ID"):
        Database.read_runs(str(path), run_id="")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE old_data (value TEXT)")
        connection.execute("INSERT INTO old_data VALUES ('keep')")
    before = path.read_bytes()
    assert Database.read_runs(str(path)) == []
    assert Database.read_runs(str(path), run_id="missing") is None
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


def test_future_database_schema_is_rejected_without_changes(tmp_path):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="newer"):
        Database(str(path))
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="newer"):
        Database.read_runs(str(path))


def test_version_zero_file_history_is_migrated_without_rewriting_old_outcomes(tmp_path):
    path = tmp_path / "phase3.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE file_operations (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, destination TEXT, operation TEXT NOT NULL,
            status TEXT, timestamp TEXT, size_bytes INTEGER, checksum TEXT, error TEXT,
            filesystem_status TEXT, destination_created INTEGER, source_removed INTEGER,
            history_status TEXT, history_error TEXT)""")
        connection.execute("""INSERT INTO file_operations (id,source,operation,status,filesystem_status)
            VALUES ('old-id','source','copy','success','copied')""")
    db = Database(str(path))
    old = db.get_file_operations()[0]
    assert old["id"] == "old-id" and old["filesystem_status"] == "copied"
    assert old["run_id"] is None and old["step_id"] is None
    Database(str(path))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert db.get_stats()["file_operations"] == 1


def test_direct_command_and_workflow_share_path_validation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    bad = "https://user:never-echo-this@example.test"
    assert main(["inspect", "--source", bad, "--format", "json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    with pytest.raises(PlanValidationError) as invalid:
        validate_workflow(document([{"id": "x", "operation": "inspect", "parameters": {"source": bad}}]))
    assert error in str(invalid.value) and "never-echo-this" not in error


def test_human_workflow_report_shows_actionable_file_failure(workspace, tmp_path, capsys):
    root, path, history = workspace
    target = tmp_path / "output/misc/a.log"
    target.parent.mkdir(parents=True)
    target.write_text("keep")
    assert main(["--database", str(history), "workflow", "run", str(path), "--apply"]) == 1
    output = " ".join(capsys.readouterr().out.split())
    assert "Destination already exists" in output and "a.log" in output


def test_interactive_organizer_uses_tracked_captured_plan(workspace, tmp_path, monkeypatch):
    root, _, history = workspace
    answers = iter([str(root), str(tmp_path / "output"), "*.log", "type", "copy", "error"])
    monkeypatch.setattr("taskmaster.cli.Prompt.ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr("taskmaster.cli.Confirm.ask", lambda *args, **kwargs: True)
    cli = TaskMasterCLI(str(history))
    try:
        assert cli.organize_files_interactive() == 0
        runs = Database.read_runs(str(history))
        assert len(runs) == 1 and runs[0]["status"] == "success"
        assert (tmp_path / "output/misc/a.log").exists()
    finally:
        cli.close()


def test_home_paths_are_resolved_before_workflow_base_directory(workspace, tmp_path, monkeypatch):
    root, _, _ = workspace
    actual = Path.expanduser

    def expand(path):
        return root if path == Path("~/artifacts") else actual(path)

    monkeypatch.setattr(Path, "expanduser", expand)
    prepared = prepare_operation("inspect", {"source": "~/artifacts", "includes": ["*.log"]}, base_dir=tmp_path / "other")
    assert run_prepared(prepared)["summary"]["file_count"] == 2


def test_cli_validation_preview_apply_and_read_only_history_from_other_cwd(workspace, tmp_path, monkeypatch, capsys):
    root, path, history = workspace
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    prefix = ["--database", str(history)]
    for command in ("validate", "run"):
        assert main([*prefix, "workflow", command, str(path), "--format", "json"]) == 0
        assert json.loads(capsys.readouterr().out)["complete"]
        assert not history.exists()
    assert main([*prefix, "workflow", "run", str(path), "--apply", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["base_dir"] == str(root)
    assert (tmp_path / "output/misc/a.log").exists()
    before = history.read_bytes()
    assert main([*prefix, "history", "list", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["runs"][0]["run_id"] == report["run_id"]
    assert main([*prefix, "history", "show", report["run_id"], "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["run"] == report
    assert history.read_bytes() == before


def test_direct_apply_exposes_run_id_and_preserves_same_captured_plan(workspace, tmp_path, monkeypatch, capsys):
    root, _, history = workspace
    monkeypatch.chdir(tmp_path)
    args = ["--database", str(history), "organize", "--source", str(root), "--destination", "output",
            "--include", "*.log", "--action", "copy", "--apply", "--format", "json"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert str(uuid.UUID(report["run_id"])) == report["run_id"]
    stored = Database.read_runs(str(history), run_id=report["run_id"])
    assert stored["workflow"]["name"] == "direct-organize"
    assert stored["steps"][0]["report"]["operations"] == report["operations"]


def test_cli_invalid_config_never_echoes_unknown_secret_values(workspace, capsys):
    _, path, history = workspace
    value = document()
    value["steps"][0]["parameters"]["password"] = "never-echo-this"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert main(["--database", str(history), "workflow", "validate", str(path), "--format", "json"]) == 1
    report = capsys.readouterr().out
    assert not json.loads(report)["complete"] and "never-echo-this" not in report
    assert not history.exists()


def test_module_workflow_cli_json_is_one_document(workspace, tmp_path):
    _, path, history = workspace
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, "-B", "-m", "taskmaster", "--database", str(history),
        "workflow", "run", str(path), "--apply", "--format", "json"], cwd=tmp_path,
        env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["complete"]
