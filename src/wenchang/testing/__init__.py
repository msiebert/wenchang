"""Conformance suites adopters run against their implementations.

Requires the `testing` extra: `pip install "wenchang[testing]"`.
"""

from wenchang.testing.resolver_conformance import ResolverConformance
from wenchang.testing.transport_conformance import TransportConformance

__all__ = ["ResolverConformance", "TransportConformance"]
