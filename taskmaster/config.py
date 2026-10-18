"""Versioned, strictly validated JSON workflows. No code evaluation/imports."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .errors import PlanValidationError
from .operations import normalize_parameters
from .planning import absolute_path, reject_links

VERSION = 1


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    operation: str
    parameters_json: str

    @property
    def parameters(self) -> dict:
        return json.loads(self.parameters_json)


@dataclass(frozen=True)
class Workflow:
    name: str
    on_failure: str
    steps: tuple[WorkflowStep, ...]
    version: int = VERSION

    def to_dict(self) -> dict:
        return {"version": self.version, "name": self.name, "on_failure": self.on_failure,
                "steps": [{"id": step.id, "operation": step.operation, "parameters": step.parameters}
                          for step in self.steps]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def validate_workflow(document: dict) -> Workflow:
    if type(document) is not dict or document.keys() - {"version", "name", "on_failure", "steps"}:
        raise PlanValidationError("Workflow must be an object with only version, name, on_failure, and steps")
    if type(document.get("version")) is not int or document["version"] != VERSION:
        raise PlanValidationError("Unsupported workflow version; expected integer version 1")
    name = document.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 256:
        raise PlanValidationError("Workflow name must contain 1–256 characters")
    policy = document.get("on_failure", "stop")
    if policy not in ("stop", "continue"):
        raise PlanValidationError("on_failure must be stop or continue")
    steps = document.get("steps")
    if type(steps) is not list or not 1 <= len(steps) <= 100:
        raise PlanValidationError("Workflow steps must be an array containing 1–100 steps")
    validated, names = [], set()
    for index, step in enumerate(steps):
        if type(step) is not dict or set(step) != {"id", "operation", "parameters"}:
            raise PlanValidationError(f"steps[{index}] must contain exactly id, operation, and parameters")
        step_id = step["id"]
        if not isinstance(step_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", step_id) or step_id in names:
            raise PlanValidationError(f"steps[{index}].id must be a unique identifier starting with a letter")
        try:
            parameters = normalize_parameters(step["operation"], step["parameters"])
        except ValueError as error:
            raise PlanValidationError(f"steps[{index}]: {error}") from error
        validated.append(WorkflowStep(step_id, step["operation"], json.dumps(parameters, sort_keys=True)))
        names.add(step_id)
    return Workflow(name, policy, tuple(validated))


def parse_workflow(text: str) -> Workflow:
    if not isinstance(text, str):
        raise PlanValidationError("Workflow JSON must be text")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PlanValidationError("Duplicate JSON object key")
            result[key] = value
        return result

    def constant(_):
        raise PlanValidationError("Non-finite numbers are not valid workflow JSON")

    try:
        document = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as error:
        raise PlanValidationError(f"Malformed workflow JSON at line {error.lineno}, column {error.colno}") from error
    except RecursionError as error:
        raise PlanValidationError("Workflow JSON nesting is too deep") from error
    return validate_workflow(document)


def load_workflow(path: Path) -> Workflow:
    path = absolute_path(path)
    reject_links(path)
    if path.stat().st_size > 1024 * 1024:
        raise PlanValidationError("Workflow file exceeds the 1 MiB configuration limit")
    return parse_workflow(path.read_text(encoding="utf-8-sig"))
