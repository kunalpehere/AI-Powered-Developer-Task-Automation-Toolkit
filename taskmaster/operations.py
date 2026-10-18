"""Closed operation registry and shared direct-command/workflow validation."""
from dataclasses import dataclass
from pathlib import Path

from .errors import PlanValidationError
from .inspection import inspect_project
from .duplicates import duplicate_report
from .models import FileRule, OperationPlan
from .organizer import FileOrganizer
from .planning import absolute_path, validate_template
from .reporting import organization_report
from .scanning import patterns

OPERATION_REGISTRY = frozenset({"inspect", "duplicates", "organize"})
TEMPLATES = {"type": "{type}/{relative_dir}/{filename}",
             "date": "{year}/{month}/{relative_dir}/{filename}",
             "size": "{size_category}/{relative_dir}/{filename}"}
COMMON = {"source", "includes", "exclusions", "use_default_excludes", "recursive"}
FIELDS = {"inspect": COMMON | {"top", "min_size"}, "duplicates": COMMON,
          "organize": COMMON | {"destination", "action", "strategy", "template", "conflict_policy", "all_files"}}


def normalize_parameters(operation: str, parameters: dict) -> dict:
    if not isinstance(operation, str) or operation not in OPERATION_REGISTRY:
        raise PlanValidationError("Unknown operation; supported names are inspect, duplicates, organize")
    if type(parameters) is not dict:
        raise PlanValidationError("parameters must be an object")
    if parameters.keys() - FIELDS[operation]:
        raise PlanValidationError(f"Unsupported parameter fields for {operation}")
    result = {"includes": [], "exclusions": [], "use_default_excludes": True, "recursive": True, **parameters}
    for field in ("source", "destination") if operation == "organize" else ("source",):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip() or "\0" in value or "://" in value:
            raise PlanValidationError(f"parameters.{field} must be a nonempty filesystem path")
    for field in ("includes", "exclusions"):
        if type(result[field]) is not list:
            raise PlanValidationError(f"parameters.{field} must be an array of relative glob strings")
        try:
            result[field] = list(patterns(result[field]))
        except ValueError as error:
            # Do not echo arbitrary configuration values in validation errors.
            raise PlanValidationError(f"parameters.{field} contains an invalid relative glob") from error
    for field in ("use_default_excludes", "recursive"):
        if type(result[field]) is not bool:
            raise PlanValidationError(f"parameters.{field} must be a boolean")
    if operation == "inspect":
        result = {"top": 10, "min_size": 0, **result}
        for field in ("top", "min_size"):
            if type(result[field]) is not int or result[field] < 0:
                raise PlanValidationError(f"parameters.{field} must be a nonnegative integer")
    if operation == "organize":
        result = {"action": "move", "strategy": "type", "template": None,
                  "conflict_policy": "error", "all_files": False, **result}
        for field, choices in (("action", {"copy", "move"}), ("strategy", set(TEMPLATES)),
                               ("conflict_policy", {"error", "skip"})):
            if not isinstance(result[field], str) or result[field] not in choices:
                raise PlanValidationError(f"parameters.{field} must be one of {', '.join(sorted(choices))}")
        if type(result["all_files"]) is not bool:
            raise PlanValidationError("parameters.all_files must be a boolean")
        if bool(result["includes"]) == result["all_files"]:
            raise PlanValidationError("Select include patterns or explicitly choose all_files=true (not both)")
        if result["template"] is not None:
            try:
                validate_template(result["template"])
            except ValueError as error:
                raise PlanValidationError("parameters.template contains an invalid or unsupported placeholder") from error
    return result


@dataclass
class PreparedOperation:
    operation: str
    parameters: dict
    base_dir: Path
    organizer: FileOrganizer | None = None
    plan: OperationPlan | None = None
    results: list | None = None


def resolve_local_path(base_dir: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return absolute_path(candidate if candidate.is_absolute() else base_dir / candidate)


def prepare_operation(operation: str, parameters: dict, *, base_dir: Path,
                      organizer: FileOrganizer | None = None) -> PreparedOperation:
    values = normalize_parameters(operation, parameters)
    base_dir = absolute_path(base_dir)
    prepared = PreparedOperation(operation, values, base_dir)
    if operation == "organize":
        organizer = organizer or FileOrganizer()
        organizer.rules.clear()
        organizer.add_rule(FileRule("named_organize", "*", values["template"] if values["template"] is not None
                                    else TEMPLATES[values["strategy"]], action=values["action"]))
        prepared.organizer = organizer
        prepared.plan = organizer.plan_directory(resolve_local_path(base_dir, values["source"]),
            resolve_local_path(base_dir, values["destination"]),
            includes=values["includes"], all_files=values["all_files"], exclusions=values["exclusions"],
            use_default_excludes=values["use_default_excludes"], recursive=values["recursive"],
            conflict_policy=values["conflict_policy"])
    return prepared


def run_prepared(prepared: PreparedOperation, *, apply: bool = False, confirmed: bool = False) -> dict:
    values = prepared.parameters
    source = resolve_local_path(prepared.base_dir, values["source"])
    scope = {key: values[key] for key in ("includes", "exclusions", "use_default_excludes", "recursive")}
    if prepared.operation == "inspect":
        return inspect_project(source, top=values["top"], min_size=values["min_size"], **scope)
    if prepared.operation == "duplicates":
        return duplicate_report(source, **scope)
    if prepared.operation != "organize" or prepared.plan is None:
        raise PlanValidationError("Prepared operation is invalid")
    plan, organizer = prepared.plan, prepared.organizer
    prepared.results = organizer.apply(plan, confirmed=confirmed) if apply else organizer.preview(plan)
    return organization_report(plan, prepared.results, summary=organizer.generate_report(prepared.results),
        mode="apply" if apply else "preview",
        scope={"includes": list(plan.includes), "all_files": plan.all_files, "exclusions": list(plan.exclusions)})
