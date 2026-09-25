"""Opaque version identifier for optimistic concurrency control."""

from typing import NewType

# Callers store and return this value; they never parse, compare, or order it.
VersionToken = NewType("VersionToken", str)
