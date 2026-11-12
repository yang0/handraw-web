"""Execute frozen canvas items without a browser or a second billing pathway."""

from __future__ import annotations

import logging
import threading
import uuid

from .db import utc_now_iso

logger = logging.getLogger(__name__)


class CanvasDispatcher:
    def __init__(self, db, workers=2):
        self.db = db
        self.worker_count = workers
        self._stop = threading.Event()
        self._threads = []

    def claim(self):
        with self.db.transaction() as tx:
            item = tx.execute(
                """SELECT i.*,r.user_id,r.canvas_id,r.external_run_id,r.expected_count
                   FROM generation_items i JOIN generation_runs r ON r.id=i.run_id
                   WHERE r.creation_mode='canvas' AND i.status='pending'
                     AND i.dispatch_after<=now() AND (i.dispatch_until IS NULL OR i.dispatch_until<=now())
                   ORDER BY i.dispatch_after,r.created_at,i.ordinal
                   LIMIT 1 FOR UPDATE OF i SKIP LOCKED""",
            ).fetchone()
            if not item:
                return None
            token = uuid.uuid4().hex
            request = item["dispatch_request_id"] or "canvas_" + uuid.uuid4().hex
            tx.execute(
                "UPDATE generation_items SET dispatch_token=?,dispatch_request_id=?,dispatch_until=now()+interval '20 minutes' WHERE id=?",
                (token, request, item["id"]),
            )
            item.update(dispatch_token=token, dispatch_request_id=request)
            return item

    def dispatch_once(self):
        item = self.claim()
        if not item:
            self.db.release_request_connection()
            return False
        failed_code = ""
        delay = 2
        try:
            user = (
                self.db.get_conn()
                .execute(
                    "SELECT * FROM users WHERE id=? AND status='active' AND closed_at=''",
                    (item["user_id"],),
                )
                .fetchone()
            )
            if not user:
                failed_code = "account_unavailable"
                return True
            body = {
                "canvasId": item["canvas_id"],
                "creationSource": "canvas",
                "batchId": item["external_run_id"],
                "batchIndex": item["ordinal"],
                "batchTotal": item["expected_count"],
                "requestId": item["dispatch_request_id"],
                "_canvasDispatchToken": item["dispatch_token"],
                "confirmCost": True,
            }
            self.db.release_request_connection()
            from .server import execute_studio_generation

            payload, status = execute_studio_generation(
                self.db, user, body, request_log_id=body["requestId"]
            )
            if status == 503:
                delay = 30
            elif status >= 400:
                # Definite gateway failures settle through the shared executor.
                # Only a still-unreserved pending item needs a local failure.
                failed_code = str(payload.get("code") or "gateway_failed")
        except Exception as exc:
            from .services import ServiceError

            if isinstance(exc, ServiceError):
                if exc.status == 429:
                    delay = 3
                else:
                    failed_code = exc.code or "invalid_generation_input"
            else:
                # A crash after reservation can mean an accepted upstream task;
                # preserve the attempt and let normal reconciliation determine it.
                delay = 15
                logger.warning(
                    "Canvas dispatch interrupted for item=%s", item["id"], exc_info=True
                )
        finally:
            with self.db.transaction() as tx:
                from .studio_execution import lock_generation_actor

                lock_generation_actor(tx, item["user_id"])
                tx.execute(
                    "SELECT id FROM generation_runs WHERE id=? FOR UPDATE",
                    (item["run_id"],),
                ).fetchone()
                if failed_code:
                    tx.execute(
                        "UPDATE generation_items SET status='failed',error_code=?,updated_at=? "
                        "WHERE id=? AND status='pending' AND dispatch_token=?",
                        (
                            failed_code,
                            utc_now_iso(),
                            item["id"],
                            item["dispatch_token"],
                        ),
                    )
                tx.execute(
                    "UPDATE generation_items SET dispatch_token=NULL,dispatch_until=NULL,"
                    "dispatch_after=now()+(? * interval '1 second') WHERE id=? AND dispatch_token=?",
                    (delay, item["id"], item["dispatch_token"]),
                )
                from .generation_v3 import refresh_run_status

                refresh_run_status(tx, item["run_id"])
            self.db.release_request_connection()
        return True

    def _run(self):
        while not self._stop.is_set():
            try:
                processed = self.dispatch_once()
            except Exception:
                logger.exception("Canvas dispatcher iteration failed")
                processed = False
            finally:
                self.db.close_thread_conn()
            self._stop.wait(0.1 if processed else 0.5)

    def start(self):
        if self._threads:
            return self
        self._stop.clear()
        for index in range(self.worker_count):
            thread = threading.Thread(
                target=self._run, name=f"handraw-canvas-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        return self

    def stop(self, timeout=3):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=max(0.1, timeout / max(1, len(self._threads))))
        self._threads = [thread for thread in self._threads if thread.is_alive()]


_LOCK = threading.Lock()


def get_canvas_dispatcher(db):
    with _LOCK:
        dispatcher = getattr(db, "_canvas_dispatcher", None)
        if dispatcher is None:
            dispatcher = CanvasDispatcher(db)
            db._canvas_dispatcher = dispatcher
        return dispatcher
