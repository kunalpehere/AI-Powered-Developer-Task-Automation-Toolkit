"""Errors shared by planning, validation, execution, and the CLI."""


class PlanValidationError(ValueError):
    """An input or file state does not satisfy the execution contract."""


class ConfirmationRequired(PlanValidationError):
    """The caller must explicitly approve destructive planned operations."""
