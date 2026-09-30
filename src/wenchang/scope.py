"""Write restrictions enforced at the tool layer.

The `system/` area of every scope holds curated content and is read-only to
every caller of these checks. `MemoryStore` deliberately does not apply them,
so the seeding job can rewrite `system/` through core.
"""

from typing import Final

from wenchang.errors import NotFoundError, NotFoundReason, RestrictedScopeError, RestrictionReason
from wenchang.paths import is_valid_path, parse_path

SYSTEM_AREA: Final = "system"


def is_system_path(path: str) -> bool:
    """Return True iff path is a valid memory path whose area is exactly `system`.

    Never raises for any str input.
    """
    return is_valid_path(path) and parse_path(path).area == SYSTEM_AREA


def check_not_system(path: str) -> None:
    """Reject a write to the read-only `system/` area of any scope.

    Raises NotFoundError(INVALID_PATH) for a malformed path, and
    RestrictedScopeError(SYSTEM_READ_ONLY) naming the path's scope if its
    area is `system`.
    """
    try:
        parts = parse_path(path)
    except ValueError:
        raise NotFoundError(path, NotFoundReason.INVALID_PATH) from None
    if parts.area == SYSTEM_AREA:
        raise RestrictedScopeError(path, parts.scope, RestrictionReason.SYSTEM_READ_ONLY)
