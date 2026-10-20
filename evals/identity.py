"""Resolve who is running the evals, as tokens the identity check looks for.

The operator's identity comes from the environment at grade time and is never
stored in the repo. Sources, in order: git user.name and user.email, $USER,
and the home directory basename.
"""

import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from evals.graders import FIRST_NAME, LAST_NAME, LOGIN, OperatorToken, nfkc

__all__ = ["COMMON_WORDS", "OperatorIdentity", "resolve_operator_identity"]

GIT_TIMEOUT_S: Final = 10
MIN_TOKEN_LENGTH: Final = 3

SOURCE_GIT_NAME: Final = "git user.name"
SOURCE_GIT_EMAIL: Final = "git user.email"
SOURCE_USER: Final = "$USER"
SOURCE_HOME: Final = "home directory"

# Words that are also common names, or generic and CI accounts.
COMMON_WORDS: Final[frozenset[str]] = frozenset(
    {
        "will",
        "grant",
        "rose",
        "brown",
        "young",
        "long",
        "hall",
        "king",
        "root",
        "admin",
        "user",
        "runner",
        "ubuntu",
        "guest",
        "dev",
        "test",
        "home",
        "app",
        "workspace",
        "node",
        "vscode",
        "codespace",
        "ec2-user",
        "buildkite-agent",
        "jenkins",
        "circleci",
        "vagrant",
        "docker",
        "nobody",
        "default",
    }
)
_SUFFIXES: Final = frozenset({"jr", "sr", "ii", "iii", "iv"})
_PARTICLES: Final = frozenset(
    {"van", "von", "der", "den", "de", "del", "della", "di", "da", "du", "la", "le"}
    | {"dos", "das", "bin", "al", "ten", "ter"}
)
_HOME_ROOTS: Final = frozenset({"/Users", "/home"})
_EVALS_DIR: Final = Path(__file__).resolve().parent


@dataclass(frozen=True)
class OperatorIdentity:
    """The tokens to look for and the sources that contributed them."""

    tokens: tuple[OperatorToken, ...]
    sources: tuple[str, ...]

    @property
    def unchecked(self) -> bool:
        return not self.tokens


def _normal(text: str) -> str:
    return nfkc(text).strip()


def _git_config(key: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(_EVALS_DIR), "config", key],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _first_name(first: str) -> OperatorToken:
    text = nfkc(first)
    spelled = text if text[:1].isupper() and not text.isupper() else text.capitalize()
    forms = dict.fromkeys((text.capitalize(), spelled, text.upper()))
    return OperatorToken(FIRST_NAME, tuple(forms), True)


def _insensitive(kind: str, word: str) -> OperatorToken:
    return OperatorToken(kind, (nfkc(word).lower(),), False)


def _trim(word: str) -> str:
    """The word without non-letters at its edges."""
    letters = [i for i, ch in enumerate(word) if ch.isalpha()]
    return word[letters[0] : letters[-1] + 1] if letters else ""


def _name_tokens(name: str) -> tuple[str | None, list[OperatorToken]]:
    """The first-name text and the tokens of a git user.name."""
    words = [_trim(part) for w in _normal(name).split() for part in w.split("-")]
    words = [w for w in words if w]
    if not words:
        return None, []
    first = words[0]
    rest = [w for w in words[1:] if w.lower() not in _SUFFIXES | _PARTICLES]
    tokens = [_first_name(first)]
    tokens += [_insensitive(LAST_NAME, w) for w in rest]
    return first, tokens


def _email_tokens(email: str, first: str | None) -> list[OperatorToken]:
    local = _normal(email).split("@", 1)[0]
    pieces = [p for p in re.split(r"[._+-]", local) if p]
    plain = len(pieces) == 1 and pieces[0] == local
    tokens: list[OperatorToken] = []
    for piece in pieces:
        if first is not None and piece.lower() == first.lower():
            tokens.append(_first_name(first))
        else:
            tokens.append(_insensitive(LOGIN if plain else LAST_NAME, piece))
    return tokens


def _keep(token: OperatorToken) -> bool:
    text = token.forms[0]
    if len(text) < MIN_TOKEN_LENGTH:
        return False
    return token.kind == FIRST_NAME or text.lower() not in COMMON_WORDS


def _home_login() -> str | None:
    home = os.environ.get("HOME")
    if not home:
        return None
    path = Path(home)
    if path.name and (path.name == os.environ.get("USER") or path.parent.as_posix() in _HOME_ROOTS):
        return path.name
    return None


def resolve_operator_identity() -> OperatorIdentity:
    """Tokens for the operator running the evals; unchecked when none survive."""
    name = _git_config("user.name")
    email = _git_config("user.email")
    user = os.environ.get("USER")
    home = _home_login()
    first: str | None = None
    name_tokens: list[OperatorToken] = []
    if name:
        first, name_tokens = _name_tokens(name)
    candidates: list[tuple[str, Sequence[OperatorToken]]] = [
        (SOURCE_GIT_NAME, name_tokens),
        (SOURCE_GIT_EMAIL, _email_tokens(email, first) if email else []),
        (SOURCE_USER, [_insensitive(LOGIN, _normal(user))] if user else []),
        (SOURCE_HOME, [_insensitive(LOGIN, _normal(home))] if home else []),
    ]
    tokens: dict[tuple[tuple[str, ...], bool], OperatorToken] = {}
    sources: list[str] = []
    for source, found in candidates:
        kept = [t for t in found if _keep(t)]
        if kept:
            sources.append(source)
        for token in kept:
            tokens.setdefault((token.forms, token.case_sensitive), token)
    return OperatorIdentity(tuple(tokens.values()), tuple(sources))
