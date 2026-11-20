"""Exception types for the reconciliation run.

Each type maps to a distinct failure so the CLI can report it clearly.
A run that raises any of these is incomplete and must not be treated as passed.
"""


class ReconciliationError(Exception):
    """Base class for all reconciliation failures."""


class ConfigError(ReconciliationError):
    """The configuration file is missing or invalid."""


class SourceMissingError(ReconciliationError):
    """A required source feed has no matching file in the input folder."""


class SourceFormatError(ReconciliationError):
    """A source file exists but Claude's extraction of it failed validation."""


class LLMError(ReconciliationError):
    """The Claude API call failed, was refused, or returned unusable output."""


class ReportError(ReconciliationError):
    """A generated report failed its grounding checks."""
