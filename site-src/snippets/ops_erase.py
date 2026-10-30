# pyright: basic
import logging

from wenchang.core import ExportedObject, MemoryStore, PurgeIncompleteError

log = logging.getLogger("erasure")


def revoke_grant(user_id: str) -> None:
    """Your auth layer: stop resolving any caller to this user's grant."""
    ...


def erase_user(store: MemoryStore, user_id: str) -> tuple[ExportedObject, ...]:
    revoke_grant(user_id)  # 1. stop writers, and let in-flight sessions end
    backup = store.export("user", user_id)  # 2. optional: hand over or archive
    try:
        deleted = store.purge("user", user_id)  # 3. everything under user/{user_id}/
    except PurgeIncompleteError as exc:
        # Objects kept reappearing: a writer is still active. Stop it and re-run.
        log.error("erasure incomplete in scope %r after %d passes", exc.scope, exc.passes)
        raise
    log.info("purged %d objects", deleted)
    return backup
