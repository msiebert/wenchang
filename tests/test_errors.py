"""Tests for the error taxonomy: version token, categories, base hierarchy.

Covers AIE-1030.
"""

from collections.abc import Callable

import pytest

from wenchang.errors import (
    BackendUnavailableError,
    ErrorCategory,
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    PermanentError,
    RecoverableError,
    ReplaceFactMatchError,
    ResolverFailureError,
    RestrictedScopeError,
    RestrictionReason,
    TransientError,
    TransientReason,
    VersionConflictError,
    WenchangError,
)
from wenchang.version_token import VersionToken

CATEGORY_CLASSES = (RecoverableError, PermanentError, TransientError)

TAXONOMY_KIND_CATEGORIES = (
    (VersionConflictError, ErrorCategory.RECOVERABLE),
    (OversizeWriteError, ErrorCategory.RECOVERABLE),
    (ReplaceFactMatchError, ErrorCategory.RECOVERABLE),
    (NotFoundError, ErrorCategory.RECOVERABLE),
    (RestrictedScopeError, ErrorCategory.PERMANENT),
    (ResolverFailureError, ErrorCategory.PERMANENT),
    (BackendUnavailableError, ErrorCategory.TRANSIENT),
)

UNICODE_CONTENT = "- [stated] café ✓ naïve\n- [observed] 日本語"

RECOVERABLE_ERROR_FACTORIES = (
    lambda: VersionConflictError("m/a.md", "content", VersionToken("gen-1")),
    lambda: OversizeWriteError("m/a.md", 10, 5),
    lambda: ReplaceFactMatchError("m/a.md", "content", VersionToken("gen-1"), 0),
    lambda: NotFoundError("m/a.md", NotFoundReason.INVALID_PATH),
)

PERMANENT_ERROR_FACTORIES = (
    lambda: RestrictedScopeError(
        "system/config.md", "system/config.md", RestrictionReason.SYSTEM_READ_ONLY
    ),
    lambda: RestrictedScopeError(
        "organization/policy.md",
        "organization",
        RestrictionReason.ROLE_REQUIRED,
        required_role="admin",
    ),
    lambda: ResolverFailureError(),
)


@pytest.mark.unit
def test_error_category_has_exactly_three_members() -> None:
    """ErrorCategory has exactly the three expected members (AIE-1030)."""
    assert {member.value for member in ErrorCategory} == {
        "recoverable",
        "permanent",
        "transient",
    }
    assert len(ErrorCategory) == 3


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "expected_value"),
    [
        (RecoverableError, "recoverable"),
        (PermanentError, "permanent"),
        (TransientError, "transient"),
    ],
)
def test_error_category_value(cls: type[WenchangError], expected_value: str) -> None:
    """Each category class reports the matching category value (AIE-1030)."""
    assert cls.category == ErrorCategory(expected_value)
    assert cls("detail").category == ErrorCategory(expected_value)


@pytest.mark.unit
@pytest.mark.parametrize("cls", CATEGORY_CLASSES)
def test_error_classes_subclass_wenchang_error(cls: type[WenchangError]) -> None:
    """Each category class is a WenchangError and an Exception (AIE-1030)."""
    assert issubclass(cls, WenchangError)
    assert issubclass(cls, Exception)


@pytest.mark.unit
@pytest.mark.parametrize("cls", CATEGORY_CLASSES)
def test_error_classes_are_siblings_not_related(cls: type[WenchangError]) -> None:
    """No category class is a subclass of another category class (AIE-1030)."""
    others = [other for other in CATEGORY_CLASSES if other is not cls]
    for other in others:
        assert not issubclass(cls, other)


@pytest.mark.unit
@pytest.mark.parametrize("cls", CATEGORY_CLASSES)
def test_error_message_format(cls: type[WenchangError]) -> None:
    """str(err) == err.message == f'{detail} {guidance}' for a sample detail (AIE-1030)."""
    detail = "something went wrong"
    err = cls(detail)
    expected = f"{detail} {cls.guidance}"
    assert str(err) == expected
    assert err.message == expected


@pytest.mark.unit
def test_recoverable_guidance_wording() -> None:
    """RecoverableError.guidance avoids 'fail' wording and mentions retry (AIE-1030)."""
    guidance = RecoverableError.guidance.lower()
    assert "fail" not in guidance
    assert "retry" in guidance


@pytest.mark.unit
def test_permanent_guidance_wording() -> None:
    """PermanentError.guidance instructs not to retry (AIE-1030)."""
    assert "do not retry" in PermanentError.guidance.lower()


@pytest.mark.unit
def test_transient_guidance_wording() -> None:
    """TransientError.guidance mentions retry/version conflict/append_line/duplicate (AIE-1030)."""
    guidance = TransientError.guidance.lower()
    assert "retry" in guidance
    assert "version conflict" in guidance
    assert "append_line" in guidance
    assert "duplicate" in guidance


@pytest.mark.unit
def test_version_token_behaves_as_str() -> None:
    """VersionToken is an opaque NewType over str usable as a plain string (AIE-1030)."""
    token = VersionToken("abc")
    assert token == "abc"
    assert isinstance(token, str)


@pytest.mark.unit
@pytest.mark.parametrize(
    "make_error",
    RECOVERABLE_ERROR_FACTORIES,
    ids=["version_conflict", "oversize_write", "replace_fact_match", "not_found"],
)
def test_recoverable_kinds_are_recoverable_not_other_categories(
    make_error: Callable[[], WenchangError],
) -> None:
    """Recoverable kinds are WenchangError, RECOVERABLE, and not permanent/transient (AIE-1030)."""
    err = make_error()
    assert isinstance(err, WenchangError)
    assert isinstance(err, RecoverableError)
    assert err.category == ErrorCategory.RECOVERABLE
    assert not isinstance(err, PermanentError)
    assert not isinstance(err, TransientError)


@pytest.mark.unit
@pytest.mark.parametrize("content", ["", UNICODE_CONTENT])
def test_version_conflict_error_exposes_content_and_version_unchanged(content: str) -> None:
    """VersionConflictError exposes path, content, and version unchanged (AIE-1030)."""
    token = VersionToken("gen-17")
    err = VersionConflictError("m/notes.md", content, token)
    assert err.path == "m/notes.md"
    assert err.content == content
    assert err.version == token
    assert err.version is token


@pytest.mark.unit
def test_oversize_write_error_exposes_size_and_limit() -> None:
    """OversizeWriteError exposes size and limit, and its message includes both (AIE-1030)."""
    err = OversizeWriteError("m/notes.md", 4096, 2048)
    assert err.path == "m/notes.md"
    assert err.size == 4096
    assert err.limit == 2048
    assert "4096" in err.message
    assert "2048" in err.message


@pytest.mark.unit
@pytest.mark.parametrize(("size", "limit"), [(-1, 10), (10, -1), (-1, -1)])
def test_oversize_write_error_rejects_negative_size_or_limit(size: int, limit: int) -> None:
    """OversizeWriteError raises ValueError for a negative size or limit (AIE-1030)."""
    with pytest.raises(ValueError):
        OversizeWriteError("m/notes.md", size, limit)


@pytest.mark.unit
@pytest.mark.parametrize("content", ["", UNICODE_CONTENT])
def test_replace_fact_match_error_exposes_content_and_version_unchanged(content: str) -> None:
    """ReplaceFactMatchError exposes content and version unchanged for count 0 (AIE-1030)."""
    token = VersionToken("gen-17")
    err = ReplaceFactMatchError("m/notes.md", content, token, 0)
    assert err.path == "m/notes.md"
    assert err.content == content
    assert err.version == token
    assert err.version is token
    assert err.match_count == 0


@pytest.mark.unit
def test_replace_fact_match_error_zero_matches_tells_caller_to_widen() -> None:
    """A match count of 0 exposes count 0 and tells the caller to widen the anchor (AIE-1030)."""
    err = ReplaceFactMatchError("m/notes.md", "content", VersionToken("gen-1"), 0)
    assert err.match_count == 0
    message = err.message.lower()
    assert "0" in err.message
    assert "widen" in message


@pytest.mark.unit
def test_replace_fact_match_error_multiple_matches_tells_caller_to_narrow() -> None:
    """A match count >= 2 exposes the count and tells the caller to narrow the anchor (AIE-1030)."""
    err = ReplaceFactMatchError("m/notes.md", "content", VersionToken("gen-1"), 3)
    assert err.match_count == 3
    message = err.message.lower()
    assert "3" in err.message
    assert "narrow" in message
    assert "exactly one" in message


@pytest.mark.unit
@pytest.mark.parametrize("match_count", [-1, 1])
def test_replace_fact_match_error_rejects_negative_or_one(match_count: int) -> None:
    """ReplaceFactMatchError raises ValueError for match_count -1 or 1 (AIE-1030)."""
    with pytest.raises(ValueError):
        ReplaceFactMatchError("m/notes.md", "content", VersionToken("gen-1"), match_count)


@pytest.mark.unit
def test_not_found_reason_has_exactly_two_members() -> None:
    """NotFoundReason has exactly INVALID_PATH and FILE_ABSENT (AIE-1030)."""
    assert {member.value for member in NotFoundReason} == {"invalid_path", "file_absent"}
    assert len(NotFoundReason) == 2


@pytest.mark.unit
def test_not_found_error_invalid_path_tells_caller_to_correct_path() -> None:
    """A NotFoundError for an invalid path exposes it and says to correct the path (AIE-1030)."""
    err = NotFoundError("m/bad path", NotFoundReason.INVALID_PATH)
    assert err.path == "m/bad path"
    assert err.reason == NotFoundReason.INVALID_PATH
    message = err.message.lower()
    assert "m/bad path" in err.message
    assert "correct the path" in message


@pytest.mark.unit
def test_not_found_error_file_absent_tells_caller_it_may_create() -> None:
    """A NotFoundError for an absent file exposes it and says it may be created (AIE-1030)."""
    err = NotFoundError("m/new.md", NotFoundReason.FILE_ABSENT)
    assert err.path == "m/new.md"
    assert err.reason == NotFoundReason.FILE_ABSENT
    message = err.message.lower()
    assert "m/new.md" in err.message
    assert "create" in message


@pytest.mark.unit
@pytest.mark.parametrize(
    "make_error",
    RECOVERABLE_ERROR_FACTORIES,
    ids=["version_conflict", "oversize_write", "replace_fact_match", "not_found"],
)
def test_recoverable_error_message_avoids_fail_wording(
    make_error: Callable[[], WenchangError],
) -> None:
    """Recoverable error messages avoid 'fail' and end with the shared guidance (AIE-1030)."""
    err = make_error()
    message = err.message.lower()
    assert "fail" not in message
    assert err.message.endswith(RecoverableError.guidance)


@pytest.mark.unit
def test_restriction_reason_has_exactly_two_members() -> None:
    """RestrictionReason has exactly SYSTEM_READ_ONLY and ROLE_REQUIRED (AIE-1030)."""
    assert {member.value for member in RestrictionReason} == {
        "system_read_only",
        "role_required",
    }
    assert len(RestrictionReason) == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "make_error",
    PERMANENT_ERROR_FACTORIES,
    ids=["restricted_scope_system", "restricted_scope_role", "resolver_failure"],
)
def test_permanent_kinds_are_permanent_not_other_categories(
    make_error: Callable[[], WenchangError],
) -> None:
    """Permanent kinds are WenchangError, PERMANENT, and not recoverable/transient (AIE-1030)."""
    err = make_error()
    assert isinstance(err, WenchangError)
    assert isinstance(err, PermanentError)
    assert err.category == ErrorCategory.PERMANENT
    assert not isinstance(err, RecoverableError)
    assert not isinstance(err, TransientError)


@pytest.mark.unit
@pytest.mark.parametrize(
    "make_error",
    PERMANENT_ERROR_FACTORIES,
    ids=["restricted_scope_system", "restricted_scope_role", "resolver_failure"],
)
def test_permanent_error_message_says_do_not_retry_and_ends_with_guidance(
    make_error: Callable[[], WenchangError],
) -> None:
    """Every permanent error message says not to retry and ends with the shared guidance,
    without telling the caller to change the call and retry (AIE-1030).
    """
    err = make_error()
    message = err.message.lower()
    assert "do not retry" in message
    assert err.message.endswith(PermanentError.guidance)
    assert "retry the" not in message
    assert "and retry" not in message


@pytest.mark.unit
def test_restricted_scope_error_exposes_attributes_unchanged() -> None:
    """RestrictedScopeError exposes path, scope, reason, and required_role unchanged (AIE-1030)."""
    err = RestrictedScopeError(
        "organization/policy.md",
        "organization",
        RestrictionReason.ROLE_REQUIRED,
        required_role="admin",
    )
    assert err.path == "organization/policy.md"
    assert err.scope == "organization"
    assert err.reason == RestrictionReason.ROLE_REQUIRED
    assert err.required_role == "admin"


@pytest.mark.unit
def test_restricted_scope_error_required_role_defaults_to_none() -> None:
    """RestrictedScopeError.required_role defaults to None (AIE-1030)."""
    err = RestrictedScopeError(
        "system/config.md", "system/config.md", RestrictionReason.SYSTEM_READ_ONLY
    )
    assert err.required_role is None


@pytest.mark.unit
def test_restricted_scope_error_system_read_only_names_scope_and_reason() -> None:
    """A SYSTEM_READ_ONLY restriction names the scope and the read-only reason (AIE-1030)."""
    err = RestrictedScopeError(
        "system/config.md", "system/config.md", RestrictionReason.SYSTEM_READ_ONLY
    )
    message = err.message.lower()
    assert "system/config.md" in err.message
    assert "system/" in message
    assert "read-only" in message


@pytest.mark.unit
def test_restricted_scope_error_role_required_names_scope_and_role() -> None:
    """A ROLE_REQUIRED restriction names the scope and the required role (AIE-1030)."""
    err = RestrictedScopeError(
        "organization/policy.md",
        "organization",
        RestrictionReason.ROLE_REQUIRED,
        required_role="admin",
    )
    message = err.message.lower()
    assert "organization" in message
    assert "admin" in message


@pytest.mark.unit
def test_restricted_scope_error_role_required_without_required_role_rejected() -> None:
    """RestrictedScopeError raises ValueError for ROLE_REQUIRED with no required_role (AIE-1030)."""
    with pytest.raises(ValueError):
        RestrictedScopeError(
            "organization/policy.md", "organization", RestrictionReason.ROLE_REQUIRED
        )


@pytest.mark.unit
def test_resolver_failure_error_default_message_mentions_unavailable_and_no_memory() -> None:
    """A resolver failure with no detail says memory is unavailable this session (AIE-1030)."""
    err = ResolverFailureError()
    message = err.message.lower()
    assert "unavailable" in message
    assert "this session" in message
    assert "without memory" in message


@pytest.mark.unit
def test_resolver_failure_error_detail_appears_in_message() -> None:
    """A resolver failure's detail argument is included in the rendered message (AIE-1030)."""
    err = ResolverFailureError("upstream index unreachable")
    assert "upstream index unreachable" in err.message
    message = err.message.lower()
    assert "unavailable" in message
    assert "this session" in message
    assert "without memory" in message


@pytest.mark.unit
def test_transient_reason_has_exactly_two_members() -> None:
    """TransientReason has exactly TIMEOUT and UNAVAILABLE (AIE-1030)."""
    assert {member.value for member in TransientReason} == {"timeout", "unavailable"}
    assert len(TransientReason) == 2


@pytest.mark.unit
@pytest.mark.parametrize("reason", list(TransientReason), ids=lambda r: r.value)
def test_backend_unavailable_error_is_transient_not_other_categories(
    reason: TransientReason,
) -> None:
    """BackendUnavailableError is a WenchangError, TRANSIENT, and not recoverable/permanent
    for either reason (AIE-1030).
    """
    err = BackendUnavailableError(reason, "detail")
    assert isinstance(err, WenchangError)
    assert isinstance(err, TransientError)
    assert err.category == ErrorCategory.TRANSIENT
    assert not isinstance(err, RecoverableError)
    assert not isinstance(err, PermanentError)


@pytest.mark.unit
@pytest.mark.parametrize("reason", list(TransientReason), ids=lambda r: r.value)
def test_backend_unavailable_error_message_states_retry_guidance(reason: TransientReason) -> None:
    """Every transient error message mentions retry, version conflict, append_line, and
    duplicate, without saying not to retry, and ends with the shared guidance (AIE-1030).
    """
    err = BackendUnavailableError(reason, "upstream call failed")
    message = err.message.lower()
    assert "retry" in message
    assert "version conflict" in message
    assert "append_line" in message
    assert "duplicate" in message
    assert "do not retry" not in message
    assert err.message.endswith(TransientError.guidance)


@pytest.mark.unit
@pytest.mark.parametrize("detail", ["", "upstream call failed"])
def test_backend_unavailable_error_detail_appears_in_message(detail: str) -> None:
    """A non-empty detail string appears in the rendered message (AIE-1030)."""
    err = BackendUnavailableError(TransientReason.TIMEOUT, detail)
    if detail:
        assert detail in err.message


@pytest.mark.unit
@pytest.mark.parametrize(
    ("reason", "expected_phrase"),
    [
        (TransientReason.TIMEOUT, "timed out"),
        (TransientReason.UNAVAILABLE, "unavailable"),
    ],
    ids=["timeout", "unavailable"],
)
def test_backend_unavailable_error_exposes_reason_and_names_it_in_message(
    reason: TransientReason, expected_phrase: str
) -> None:
    """BackendUnavailableError exposes which of timeout or unavailability occurred, and the
    message names it, differing between the two reasons (AIE-1030).
    """
    err = BackendUnavailableError(reason, "detail")
    assert err.reason == reason
    assert expected_phrase in err.message.lower()

    other_reason = next(r for r in TransientReason if r is not reason)
    other_err = BackendUnavailableError(other_reason, "detail")
    assert err.message != other_err.message


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "expected_category"),
    TAXONOMY_KIND_CATEGORIES,
    ids=[cls.__name__ for cls, _ in TAXONOMY_KIND_CATEGORIES],
)
def test_every_taxonomy_kind_exists_and_reports_its_category(
    cls: type[WenchangError], expected_category: ErrorCategory
) -> None:
    """Every kind in the taxonomy exists, is a WenchangError, and reports its
    category (AIE-1030, SC-001).
    """
    assert issubclass(cls, WenchangError)
    assert cls.category == expected_category
