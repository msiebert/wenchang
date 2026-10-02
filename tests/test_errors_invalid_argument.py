"""Tests for InvalidArgumentError, the recoverable agent-argument error (AIE-1044, US4.4)."""

import pytest

from wenchang.errors import (
    ErrorCategory,
    InvalidArgumentError,
    PermanentError,
    RecoverableError,
    TransientError,
    WenchangError,
)

pytestmark = pytest.mark.unit


class _LyingStr(str):
    """A str subclass whose __str__ and __format__ lie."""

    def __str__(self) -> str:
        return "lie"

    def __format__(self, format_spec: str) -> str:
        return "lie"


def test_invalid_argument_error_is_recoverable() -> None:
    """InvalidArgumentError is a RecoverableError with category RECOVERABLE
    (AIE-1044, US4.4).
    """
    err = InvalidArgumentError("cursor", "bad")
    assert isinstance(err, RecoverableError)
    assert err.category == ErrorCategory.RECOVERABLE
    assert InvalidArgumentError.category == ErrorCategory.RECOVERABLE
    assert not isinstance(err, PermanentError)
    assert not isinstance(err, TransientError)


def test_invalid_argument_error_is_wenchang_error() -> None:
    """InvalidArgumentError is a WenchangError and an Exception (AIE-1044, US4.4)."""
    assert issubclass(InvalidArgumentError, WenchangError)
    assert issubclass(InvalidArgumentError, Exception)


def test_invalid_argument_error_exposes_argument() -> None:
    """InvalidArgumentError exposes the argument name unchanged (AIE-1044, US4.4)."""
    err = InvalidArgumentError("cursor", "bad")
    assert err.argument == "cursor"


def test_invalid_argument_error_detail_is_composed_sentence() -> None:
    """detail holds the composed sentence naming the argument (AIE-1044, US4.4)."""
    err = InvalidArgumentError("cursor", "bad")
    assert err.detail == "Argument cursor is invalid: bad"


def test_invalid_argument_error_str_is_detail_then_guidance() -> None:
    """str(err) starts with the composed sentence and ends with the recoverable
    guidance (AIE-1044, US4.4).
    """
    err = InvalidArgumentError("cursor", "bad")
    assert str(err).startswith("Argument cursor is invalid: bad")
    assert str(err).startswith(err.detail)
    assert str(err).endswith(RecoverableError.guidance)
    assert str(err) == f"Argument cursor is invalid: bad {RecoverableError.guidance}"
    assert err.message == str(err)


def test_invalid_argument_error_rejects_empty_argument() -> None:
    """An empty argument name raises ValueError (AIE-1044, US4.4)."""
    with pytest.raises(ValueError):
        InvalidArgumentError("", "x")


@pytest.mark.parametrize("argument", [1, None, b"cursor", ["cursor"]], ids=repr)
def test_invalid_argument_error_rejects_non_str_argument(argument: object) -> None:
    """A non-str argument name raises TypeError (AIE-1044, US4.4)."""
    with pytest.raises(TypeError):
        InvalidArgumentError(argument, "x")  # pyright: ignore[reportArgumentType]


def test_invalid_argument_error_normalizes_str_subclass_argument() -> None:
    """A str-subclass argument is stored as exact str and composed from its real
    value, not its overridden __str__/__format__ (AIE-1044, US4.4).
    """
    err = InvalidArgumentError(_LyingStr("cursor"), "bad")
    assert type(err.argument) is str
    assert err.argument == "cursor"
    assert err.detail == "Argument cursor is invalid: bad"
