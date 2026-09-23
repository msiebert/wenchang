"""Smoke test confirming the package imports and the pipeline is green."""

import pytest

import wenchang


@pytest.mark.unit
def test_import() -> None:
    assert wenchang.__version__
