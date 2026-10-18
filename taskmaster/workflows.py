"""Sequential workflow execution with explicit failure and persistence policies."""
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import uuid

from .config import Workflow, validate_workflow
from .database import Database
from .errors import ConfirmationRequired, PlanValidationError
from .operations import PreparedOperation, prepare_operation, run_prepared
from .organizer import FileOrganizer
from .planning import absolute_path

logger = logging.getLogger("taskmaster.workflows")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_message(message: str) -> str:
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1[REDACTED]@", str(message))
    return re.sub(r'''(?ix)\b(password|token|secret|api[_-]?key|authorization)\b["']?\s*[:=]\s*
                     (?:bearer\s+[^\s,;]+|"[^"]*"|'[^']*'|[^\s,;]+)''',
                  lambda match: match.group(1) + "=[REDACTED]", text)


def clean_diagnostics(value):
    if isinstance(value, dict):
        return {key: safe_message(item) if key in {"error", "history_error", "message"} and isinstance(item, str)
                else clean_diagnostics(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_diagnostics(item) for item in value]
    return value


def diagnostic(code, message):
    return {"code": code, "message": safe_message(message)}


def run_workflow(workflow: Workflow, *, base_dir: Path, apply: bool = False, confirmed: bool = False,
                 history_path: Path | None = None, database_factory=None, config_path: Path | None = None,
                 _prepared: dict[str, PreparedOperation] | None = None) -> dict:
    # Revalidate even programmatically constructed objects; parameters are copied
    # from canonical JSON so caller mutations cannot change an in-flight run.
    workflow = validate_workflow(workflow.to_dict())
    if type(apply) is not bool or type(confirmed) is not bool:
        raise PlanValidationError("apply and confirmed must be booleans")
    if apply and not confirmed and any(step.operation == "organize" and step.parameters["action"] == "move"
                                       for step in workflow.steps):
        raise ConfirmationRequired("Workflow move application requires explicit --apply --yes approval")
    base_dir = absolute_path(base_dir)
    history_path = absolute_path(history_path or Path.cwd() / "taskmaster.db")
    config_path = absolute_path(config_path) if config_path is not None else None
    run_id = str(uuid.uuid4())
    report = {"schema_version": 1, "command": "workflow", "run_id": run_id,
              "workflow": {"name": workflow.name, "version": workflow.version, "config_sha256": workflow.fingerprint},
              "mode": "apply" if apply else "preview", "on_failure": workflow.on_failure,
              "base_dir": str(base_dir), "config_path": str(config_path) if config_path else None,
              "started_at": timestamp(), "finished_at": None, "status": "running", "complete": False,
              "history": {"status": "not_requested", "errors": []}, "diagnostics": [],
              "steps": [{"id": step.id, "operation": step.operation, "status": "not_run",
                         "started_at": None, "finished_at": None, "diagnostics": [], "report": None}
                        for step in workflow.steps],
              "summary": {"successful_steps": 0, "failed_steps": 0, "not_run_steps": len(workflow.steps),
                          "running_steps": 0, "history_failures": 0}}
    db = None

    def history_error(code, error, step_id=None):
        entry = diagnostic(code, str(error))
        if step_id:
            entry["step_id"] = step_id
        report["history"]["status"] = "failed"
        report["history"]["errors"].append(entry)
        logger.warning("run=%s step=%s code=%s", run_id, step_id or "-", code)

    if apply:
        try:
            db = database_factory() if database_factory else Database(str(history_path))
            report["history"]["status"] = "recorded"
            db.start_run(report)
        except Exception as error:
            history_error("history_start_failed", error)
            report["status"] = "failed"
            report["finished_at"] = timestamp()
            for step in report["steps"]:
                step["diagnostics"] = [diagnostic("history_unavailable", "Run was not started because its journal could not be written")]
            report["summary"] = {"successful_steps": 0, "failed_steps": 0, "not_run_steps": len(workflow.steps),
                                 "running_steps": 0, "history_failures": len(report["history"]["errors"])}
            return report

    stopped = False
    for index, step in enumerate(workflow.steps):
        result = report["steps"][index]
        prepared = None
        start_failed = False
        may_execute = not stopped
        if stopped:
            result["diagnostics"] = [diagnostic("previous_step_failed", "Not run because an earlier step failed")]
        else:
            result["status"], result["started_at"] = "running", timestamp()
            if db is not None:
                try:
                    db.save_run_step(run_id, index, result)
                except Exception as error:
                    history_error("history_step_start_failed", error, step.id)
                    start_failed, may_execute = True, False
                    result["status"], result["started_at"] = "not_run", None
                    result["diagnostics"] = [diagnostic("history_step_start_failed", "Step was not executed because its start journal failed")]
        if may_execute:
            organizer = FileOrganizer(history_path=history_path)
            try:
                if db is not None:
                    def record_file(operation, step_id=step.id):
                        operation.run_id, operation.step_id = run_id, step_id
                        if operation.error:
                            operation.error = safe_message(operation.error)
                        try:
                            db.log_file_operation(operation)
                        except Exception as error:
                            raise RuntimeError(safe_message(str(error))) from None
                    organizer.history_recorder = record_file
                prepared = (_prepared or {}).get(step.id)
                if prepared is None:
                    prepared = prepare_operation(step.operation, step.parameters, base_dir=base_dir, organizer=organizer)
                elif (prepared.operation != step.operation or prepared.parameters != step.parameters
                      or prepared.base_dir != base_dir):
                    raise PlanValidationError("Captured operation does not match the validated workflow step")
                elif prepared.organizer is not None:
                    prepared.organizer.history_recorder = organizer.history_recorder
                if prepared.plan is not None and config_path is not None and any(
                        item.source == config_path or item.destination == config_path for item in prepared.plan.operations):
                    raise PlanValidationError("The workflow configuration file cannot be selected or replaced")
                result["report"] = clean_diagnostics(run_prepared(prepared, apply=apply, confirmed=confirmed))
                if prepared.results:
                    for outcome in prepared.results:
                        if outcome.error:
                            outcome.error = safe_message(outcome.error)
                        if outcome.history_error:
                            outcome.history_error = safe_message(outcome.history_error)
                            history_error("file_history_failed", outcome.history_error, step.id)
                result["status"] = "success" if result["report"]["complete"] else "failed"
                if result["status"] == "failed":
                    result["diagnostics"] = [diagnostic("operation_incomplete", "Operation reported file, scan, or history failures; see its report")]
            except Exception as error:
                result["status"] = "failed"
                result["diagnostics"] = [diagnostic("operation_failed", str(error))]
            finally:
                organizer.close()
                if prepared is not None and prepared.organizer is not None:
                    prepared.organizer.close()
            result["finished_at"] = timestamp()
        if db is not None and not start_failed:
            try:
                db.save_run_step(run_id, index, result)
            except Exception as error:
                history_error("history_step_failed", error, step.id)
                if result["status"] != "not_run":
                    result["status"] = "failed"
                    result["diagnostics"].append(diagnostic("history_step_failed", "Step journal could not be written"))
        logger.info("run=%s step=%s operation=%s status=%s", run_id, step.id, step.operation, result["status"])
        if (result["status"] == "failed" or start_failed) and workflow.on_failure == "stop":
            stopped = True

    report["summary"] = {"successful_steps": sum(step["status"] == "success" for step in report["steps"]),
                         "failed_steps": sum(step["status"] == "failed" for step in report["steps"]),
                         "not_run_steps": sum(step["status"] == "not_run" for step in report["steps"]),
                         "running_steps": 0,
                         "history_failures": len(report["history"]["errors"])}
    report["complete"] = not report["summary"]["failed_steps"] and not report["history"]["errors"]
    report["status"] = "success" if report["complete"] else "failed"
    report["finished_at"] = timestamp()
    if db is not None:
        try:
            db.finish_run(report)
        except Exception as error:
            history_error("history_finish_failed", error)
            report["summary"]["history_failures"] = len(report["history"]["errors"])
            report["status"] = "failed" if report["summary"]["failed_steps"] else "completed_with_errors"
            report["complete"] = False
    return report
