"""Fair PostgreSQL claims for gateway reconciliation across workers."""

from __future__ import annotations

import uuid
from contextlib import contextmanager


@contextmanager
def polling_claims(db, *, limit=50, interval_seconds=15):
    """Claim just before each poll, releasing the connection during network I/O."""

    def rows():
        visited = []
        for _ in range(limit):
            token = uuid.uuid4().hex
            with db.transaction() as tx:
                row = tx.execute(
                    """SELECT * FROM studio_generations
                       WHERE engine='live' AND deleted_at=''
                         AND status IN ('queued','running') AND next_poll_at<=now()
                         AND (poll_claim_until IS NULL OR poll_claim_until<=now())
                         AND NOT(id=ANY(?))
                       ORDER BY next_poll_at,created_at,id
                       LIMIT 1 FOR UPDATE SKIP LOCKED""",
                    (visited,),
                ).fetchone()
                if not row:
                    break
                tx.execute(
                    "UPDATE studio_generations SET poll_claim_token=?,poll_claim_until=now()+interval '10 minutes' WHERE id=?",
                    (token, row["id"]),
                )
            visited.append(row["id"])
            row["poll_claim_token"] = token
            db.release_request_connection()
            try:
                yield row
            finally:
                with db.transaction() as tx:
                    failures = (
                        min(5, int(row["poll_failures"]) + 1)
                        if row.get("_poll_failed")
                        else 0
                    )
                    delay = min(300, max(1, interval_seconds) * (2**failures))
                    tx.execute(
                        """UPDATE studio_generations SET poll_claim_token=NULL,poll_claim_until=NULL,
                                  next_poll_at=now()+(? * interval '1 second'),poll_failures=?
                           WHERE id=? AND poll_claim_token=?""",
                        (delay, failures, row["id"], token),
                    )
                db.release_request_connection()

    iterator = rows()
    try:
        yield iterator
    finally:
        iterator.close()
        db.release_request_connection()
