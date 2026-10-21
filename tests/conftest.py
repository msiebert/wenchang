"""Shared pytest fixtures for unit tests."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

FAKE_NAME = "Grace Hopper"
FAKE_EMAIL = "grace.hopper@example.com"
FAKE_LOGIN = "ghopper"

SetIdentity = Callable[..., None]


def _apply_identity(
    monkeypatch: pytest.MonkeyPatch,
    empty_config: Path,
    *,
    name: str | None,
    email: str | None,
    user: str | None,
    home: str | None,
) -> None:
    """Point git, $USER, and $HOME at the given identity through os.environ, so
    in-process calls and subprocess CLI calls resolve the same one.
    """
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    pairs = [(key, value) for key, value in (("user.name", name), ("user.email", email)) if value]
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(len(pairs)))
    for n, (key, value) in enumerate(pairs):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{n}", key)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{n}", value)
    for variable, value in (("USER", user), ("HOME", home)):
        if value is None:
            monkeypatch.delenv(variable, raising=False)
        else:
            monkeypatch.setenv(variable, value)


@pytest.fixture(autouse=True)
def fake_operator_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Every test sees the fake operator, never the machine's identity."""
    empty_config = tmp_path_factory.mktemp("gitconfig") / "empty"
    empty_config.write_text("")
    # The home basename equals $USER, so it resolves as the login wherever the
    # directory lives; a real directory keeps tools that write under $HOME working.
    home = tmp_path_factory.mktemp("home") / FAKE_LOGIN
    home.mkdir()
    # uv locates its cache and managed Pythons under $HOME; pin them first.
    for variable, default in (
        ("UV_CACHE_DIR", Path.home() / ".cache" / "uv"),
        ("UV_PYTHON_INSTALL_DIR", Path.home() / ".local" / "share" / "uv" / "python"),
    ):
        monkeypatch.setenv(variable, os.environ.get(variable, str(default)))
    _apply_identity(
        monkeypatch,
        empty_config,
        name=FAKE_NAME,
        email=FAKE_EMAIL,
        user=FAKE_LOGIN,
        home=str(home),
    )


@pytest.fixture
def set_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> SetIdentity:
    """Replace the fake identity's sources; an omitted source is absent."""
    empty_config = tmp_path_factory.mktemp("gitconfig-override") / "empty"
    empty_config.write_text("")

    def apply(
        *,
        name: str | None = None,
        email: str | None = None,
        user: str | None = None,
        home: str | None = None,
    ) -> None:
        _apply_identity(monkeypatch, empty_config, name=name, email=email, user=user, home=home)

    return apply
