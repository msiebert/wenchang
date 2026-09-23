# 0003. Storage interface with in-memory fake and GCS emulator

Date: 2026-09-23

## Status

Accepted

## Context

The spec deliberately assumes GCS as the storage backend rather than
abstracting it — two GCS properties are load-bearing and used directly:
native custom object metadata (carrying the four file metadata fields
atomically with content) and the object generation number plus
`ifGenerationMatch` precondition (backing the opaque version token and
compare-and-swap). The spec keeps the version token opaque in every
signature specifically so that a later storage seam is mechanical, but does
not ask for a swappable backend now.

Testing directly against GCS is impractical for fast unit tests: it
requires network access and real credentials, and makes tests slow and
flaky.

## Decision

We add a thin internal storage protocol that mirrors GCS semantics exactly
(object metadata, generation numbers, generation-match preconditions) —
not a general-purpose storage abstraction, and not a hedge against
switching providers. Two implementations exist behind it:

- An **in-memory fake**, used in unit tests.
- A **GCS implementation**, used in production and exercised by integration
  tests against a `fake-gcs-server` emulator.

Both implementations must pass the same conformance test suite (see
Section 10 of the spec), so the fake cannot silently diverge from real GCS
behavior.

## Consequences

Unit tests run fast, with no network dependency, while still exercising
real generation-conflict and atomicity semantics through the fake.
Integration tests validate the same semantics against a real GCS-compatible
server. The protocol's surface is deliberately narrow — mirroring GCS, not
abstracting away from it — so it does not reopen the "swappable backend"
question the spec explicitly declined to answer.
