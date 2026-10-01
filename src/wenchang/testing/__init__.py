"""Conformance suites adopters run against their implementations.

Requires the `testing` extra: `pip install "wenchang[testing]"`.
"""

from wenchang.testing.resolver_conformance import ResolverConformance

__all__ = ["ResolverConformance"]
