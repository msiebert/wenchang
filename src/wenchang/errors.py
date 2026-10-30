"""Error taxonomy: three categories of failure, each with fixed next-action guidance."""

from enum import StrEnum
from typing import ClassVar, cast

from wenchang.paths import parse_path
from wenchang.version_token import VersionToken


def _location(path: str) -> str | None:
    """Name a memory path as scope, area, and name; None if it does not parse."""
    try:
        parts = parse_path(path)
    except ValueError:
        return None
    return f"scope {parts.scope}, area {parts.area}, name {parts.name}"


class ErrorCategory(StrEnum):
    """The three ways a wenchang operation can fail."""

    RECOVERABLE = "recoverable"
    PERMANENT = "permanent"
    TRANSIENT = "transient"


class WenchangError(Exception):
    """Base of every library error.

    Subclasses set `category` and `guidance`; `message` combines the
    instance-specific `detail` with the class's fixed guidance text.
    """

    category: ClassVar[ErrorCategory]
    guidance: ClassVar[str]

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return f"{self.detail} {type(self).guidance}"

    def __str__(self) -> str:
        return self.message


class RecoverableError(WenchangError):
    """Normal coordination signal, not something to surface to the user."""

    category = ErrorCategory.RECOVERABLE
    guidance = (
        "This is normal coordination, not an error the user needs to know about. "
        "Use the details above to correct the call and retry in the same turn, "
        "without asking the user."
    )


class PermanentError(WenchangError):
    """The call cannot succeed as given; retrying will not help."""

    category = ErrorCategory.PERMANENT
    guidance = "Do not retry: retrying will not succeed."


class TransientError(WenchangError):
    """A temporary condition; retrying is appropriate."""

    category = ErrorCategory.TRANSIENT
    guidance = (
        "Retrying is appropriate. Version-guarded calls are safe to retry because "
        "an attempt that already landed comes back as a version conflict on retry. "
        "A retried append_line may duplicate a line, which can be removed by "
        "ordinary editing."
    )


class VersionConflictError(RecoverableError):
    """The file changed since it was read; the caller must merge and retry."""

    def __init__(self, path: str, content: str, version: VersionToken) -> None:
        self.path = path
        self.content = content
        self.version = version
        loc = _location(path)
        subject = f"The file at {loc}" if loc else "The file"
        detail = (
            f"{subject} changed since it was read; the current content "
            "and version are attached; merge your change into the current content "
            "and retry with the current version."
        )
        super().__init__(detail)


class OversizeWriteError(RecoverableError):
    """A write exceeded the byte-size limit for a single file."""

    def __init__(self, path: str, size: int, limit: int) -> None:
        if size < 0 or limit < 0:
            raise ValueError("size and limit must be non-negative")
        self.path = path
        self.size = size
        self.limit = limit
        detail = (
            f"The write to {_location(path) or 'the file'} is {size} bytes, "
            f"over the {limit}-byte limit; "
            "split the content across multiple files."
        )
        super().__init__(detail)


class FileQuotaExceededError(RecoverableError):
    """A create would put an entity over its file-count limit."""

    def __init__(self, path: str, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        self.path = path
        self.limit = limit
        advice = (
            f"is at its limit of {limit} files (system/ files not counted). "
            "Add this content to an existing file instead (append_line, replace_fact, "
            "or write_file with that file's version), or merge related files into one "
            "and delete the merged ones with delete_file, then retry."
        )
        loc = _location(path)
        if loc is None:
            detail = f"Cannot create a new file: memory for this entity {advice}"
        else:
            scope = parse_path(path).scope
            detail = f"Cannot create a new file at {loc}: memory in scope {scope} {advice}"
        super().__init__(detail)


class ReplaceFactMatchError(RecoverableError):
    """A replace_fact anchor matched zero or more than one span."""

    def __init__(self, path: str, content: str, version: VersionToken, match_count: int) -> None:
        if match_count < 0 or match_count == 1:
            raise ValueError("match_count must be 0 or 2 or greater")
        self.path = path
        self.content = content
        self.version = version
        self.match_count = match_count
        where = _location(path) or "the file"
        if match_count == 0:
            detail = (
                f"old_string matched {match_count} spans in {where}; widen or correct "
                "old_string using the attached current content so it matches."
            )
        else:
            detail = (
                f"old_string matched {match_count} spans in {where}; narrow old_string "
                "(include surrounding text) so it matches exactly one span."
            )
        super().__init__(detail)


class InvalidArgumentError(RecoverableError):
    """An agent-supplied argument was rejected; correct it and retry."""

    def __init__(self, argument: str, detail: str) -> None:
        # type() rather than isinstance, which consults a spoofable __class__.
        if not issubclass(type(cast(object, argument)), str):
            raise TypeError("argument must be a str")
        # Exact str, so an overridden __str__/__format__ cannot alter the message.
        argument = str.__str__(argument)
        if not argument:
            raise ValueError("argument must be non-empty")
        self.argument = argument
        super().__init__(f"Argument {argument} is invalid: {detail}")


class NotFoundReason(StrEnum):
    """Why a memory location could not be resolved to an existing file."""

    INVALID_PATH = "invalid_path"
    FILE_ABSENT = "file_absent"


class NotFoundError(RecoverableError):
    """A path is invalid, or is valid but no file exists there yet."""

    def __init__(self, path: str, reason: NotFoundReason) -> None:
        self.path = path
        self.reason = reason
        if reason is NotFoundReason.INVALID_PATH:
            detail = "That is not a valid memory location; correct the scope, area, and name."
        else:
            detail = f"No file exists at {_location(path) or 'the file'} yet; you may create it."
        super().__init__(detail)


class RestrictionReason(StrEnum):
    """Why a scope is closed to the write the caller attempted."""

    SYSTEM_READ_ONLY = "system_read_only"
    ROLE_REQUIRED = "role_required"
    NOT_GRANTED = "not_granted"


class RestrictedScopeError(PermanentError):
    """A path falls within a scope the caller cannot write to.

    `required_roles` is the set of roles permitted to write the scope. It is
    required and non-empty for ROLE_REQUIRED and must be None otherwise.
    """

    def __init__(
        self,
        path: str,
        scope: str,
        reason: RestrictionReason,
        required_roles: frozenset[str] | None = None,
    ) -> None:
        if required_roles is not None:
            # type() rather than isinstance, which consults a spoofable __class__.
            if not issubclass(type(required_roles), frozenset):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise TypeError("required_roles must be a frozenset or None")
            members = frozenset(cast(frozenset[object], required_roles))
            if not all(isinstance(role, str) for role in members):
                raise TypeError("required_roles must contain only str")
            # Exact strs, so overridden str-subclass methods cannot mislead sorting.
            required_roles = frozenset(str.__str__(cast(str, role)) for role in members)
        if reason is RestrictionReason.ROLE_REQUIRED and not required_roles:
            raise ValueError("required_roles must be non-empty when reason is ROLE_REQUIRED")
        if reason is not RestrictionReason.ROLE_REQUIRED and required_roles is not None:
            raise ValueError("required_roles is only allowed when reason is ROLE_REQUIRED")
        self.path = path
        self.scope = scope
        self.reason = reason
        self.required_roles = required_roles
        loc = _location(path) or f"scope {scope}"
        if reason is RestrictionReason.SYSTEM_READ_ONLY:
            detail = (
                f"The file at {loc} cannot be written: the system/ area of scope {scope} is "
                "read-only (curated content)."
            )
        elif reason is RestrictionReason.NOT_GRANTED:
            detail = (
                f"The file at {loc} cannot be written: the caller's identity does not include "
                f"this entity in scope {scope}."
            )
        else:
            roles = ", ".join(sorted(required_roles or ()))
            detail = (
                f"The file at {loc} cannot be written: scope {scope} is role-gated and "
                f"the caller lacks a permitted role ({roles})."
            )
        super().__init__(detail)


class TransientReason(StrEnum):
    """Why the storage backend could not complete a call."""

    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class BackendUnavailableError(TransientError):
    """The storage backend did not respond in time or is unreachable."""

    def __init__(self, reason: TransientReason, detail: str = "") -> None:
        self.reason = reason
        prefix = f"{detail} " if detail else ""
        if reason is TransientReason.TIMEOUT:
            message = f"{prefix}The storage backend timed out."
        else:
            message = f"{prefix}The storage backend is unavailable."
        super().__init__(message)


class ResolverFailureError(PermanentError):
    """Identity resolution failed, so memory is unavailable for this session."""

    def __init__(self, detail: str = "") -> None:
        prefix = f"{detail} " if detail else ""
        message = (
            f"{prefix}Identity could not be resolved; memory is unavailable for "
            "this session; continue working without memory."
        )
        super().__init__(message)
