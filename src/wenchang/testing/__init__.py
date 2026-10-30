"""Conformance suites adopters run against their implementations.

Requires the `testing` extra: install `wenchang[testing]`; see docs/releasing.md.
"""

from wenchang.testing.resolver_conformance import ResolverConformance
from wenchang.testing.transport_conformance import TransportConformance

__all__ = ["ResolverConformance", "TransportConformance"]
