"""Fixtures for integration tests that require a fake-gcs-server emulator.

No tests exist yet; this provides the fixture skeleton that future
integration tests (see `make emulator-up`) will build on.
"""

import os

import pytest


@pytest.fixture
def storage_emulator_host() -> str:
    """Base URL of the fake-gcs-server emulator used by integration tests."""
    return os.environ.get("STORAGE_EMULATOR_HOST", "http://localhost:4443")
