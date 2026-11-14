"""Durable search index worker. Run independently of HTTP request processes."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import threading
import time
import uuid
from collections import defaultdict

from .search_engine import SearchEngine, index_name
from .search_sources import CHANNELS, KINDS, entity_ids, entity_documents, identity, resource_map

log = logging.getLogger('handraw.search')


class SearchWorker:
    def __init__(self, db, engine=None):
        self.db = db
        self.engine = engine or SearchEngine(write=True)
        self.last_manifest = 0
        self.after_snapshot = None  # Used by concurrency integration tests.

    def initialize(self):
        from .search_service import request_rebuild
        conn = self.db.get_conn()
        if not conn.execute('SELECT pg_try_advisory_lock(266,1)').fetchone()[0]:
            raise RuntimeError('Another search worker is running')
        # A swap cannot be blindly retried: doing it twice would restore stale data.
        conn.execute("UPDATE search_jobs SET status=CASE WHEN status='swapping' THEN 'unknown' ELSE 'failed' END, error='Worker interrupted; live index retained. Start a new rebuild.',finished_at=now() WHERE status IN ('running','swapping')")
        for channel in CHANNELS:
            created = self.engine.ensure_index(index_name(channel))
            state = conn.execute('SELECT last_success_at FROM search_channels WHERE channel=?',(channel,)).fetchone()
            if created or not state['last_success_at']:
                request_rebuild(self.db,channel)

    def sync_manifest(self):
        conn = self.db.get_conn()
        resources = resource_map(conn)
        current = {}
        for code,r in resources.items():
            channel = KINDS.get(r.get('kind'))
            if channel:
                docs = entity_documents(conn,channel,code,indexing=True,resources=resources)
                current[channel,code] = hashlib.sha256(json.dumps(docs,sort_keys=True).encode()).hexdigest()
        stored = {(r['channel'],r['entity_id']):r['fingerprint'] for r in conn.execute('SELECT * FROM search_resource_manifest').fetchall()}
        with self.db.transaction() as tx:
            queued = {r['channel'] for r in tx.execute("SELECT channel FROM search_jobs WHERE status='queued'").fetchall()}
            for (channel,code), fingerprint in current.items():
                if stored.get((channel,code)) != fingerprint:
                    if channel not in queued:
                        tx.execute('SELECT search_enqueue(?,?)',(channel,code))
                    tx.execute('INSERT INTO search_resource_manifest(channel,entity_id,fingerprint) VALUES(?,?,?) ON CONFLICT(channel,entity_id) DO UPDATE SET fingerprint=excluded.fingerprint',(channel,code,fingerprint))
            for channel,code in stored.keys() - current.keys():
                if channel not in queued:
                    tx.execute('SELECT search_enqueue(?,?)',(channel,code))
                tx.execute('DELETE FROM search_resource_manifest WHERE channel=? AND entity_id=?',(channel,code))
        self.last_manifest = time.monotonic()

    def process_events(self, limit=100):
        conn = self.db.get_conn()
        rows = conn.execute('SELECT * FROM search_events WHERE processed_at IS NULL AND retry_at<=now() ORDER BY id LIMIT ?', (limit,)).fetchall()
        groups = defaultdict(list)
        for row in rows:
            groups[row['channel'],row['entity_id']].append(row)
        resources = resource_map(conn) if any(k[0] in ('styles','layouts','colors') for k in groups) else None
        for (channel,entity), events in groups.items():
            try:
                docs = entity_documents(conn,channel,entity,indexing=True,resources=resources)
                self.engine.replace_entity(index_name(channel),identity(channel,entity),docs)
                with self.db.transaction() as tx:
                    for event in events:
                        tx.execute("UPDATE search_events SET processed_at=now(),error='' WHERE id=?",(event['id'],))
                    tx.execute("UPDATE search_channels SET last_success_at=now(),last_error='' WHERE channel=?",(channel,))
            except Exception as exc:
                error = type(exc).__name__ + ': ' + str(exc)[:250]
                with self.db.transaction() as tx:
                    for event in events:
                        tx.execute("UPDATE search_events SET attempts=attempts+1,error=?,retry_at=now()+LEAST(60,POWER(2,LEAST(attempts,6))) * interval '1 second' WHERE id=?",(error,event['id']))
                    tx.execute('UPDATE search_channels SET last_error=? WHERE channel=?',(error,channel))
                log.warning('Search update failed: channel=%s error=%s',channel,type(exc).__name__)
        return len(rows)

    def _replay(self, channel, epoch, shadow, seen):
        conn = self.db.get_conn()
        rows = conn.execute('SELECT id,entity_id FROM search_events WHERE channel=? AND epoch>=? ORDER BY id',(channel,epoch)).fetchall()
        pending = [r for r in rows if r['id'] not in seen]
        resources = resource_map(conn) if channel in ('styles','layouts','colors') else None
        for entity in dict.fromkeys(r['entity_id'] for r in pending):
            docs = entity_documents(conn,channel,entity,indexing=True,resources=resources)
            self.engine.replace_entity(shadow,identity(channel,entity),docs)
            # Keep the live index current while the replacement is being built.
            self.engine.replace_entity(index_name(channel),identity(channel,entity),docs)
        seen.update(r['id'] for r in pending)

    def rebuild(self, job):
        conn = self.db.get_conn()
        channel, jid = job['channel'], job['id']
        self.engine.ensure_index(index_name(channel))
        shadow = index_name(channel) + '_build_' + uuid.uuid4().hex
        swapping = False
        swap_task_uid = None
        try:
            # Existing modifying transactions commit before the epoch changes;
            # all later mutations retain this epoch until the final barrier.
            with self.db.transaction() as tx:
                tx.execute('SELECT pg_advisory_xact_lock(266,0)')
                row = tx.execute('UPDATE search_channels SET epoch=epoch+1 WHERE channel=? RETURNING epoch',(channel,)).fetchone()
                epoch = row['epoch']
                tx.execute("UPDATE search_jobs SET status='running',phase='building',epoch=?,shadow_index=?,started_at=now() WHERE id=?",(epoch,shadow,jid))
            self.engine.ensure_index(shadow)
            ids = entity_ids(conn,channel)
            conn.execute('UPDATE search_jobs SET total=? WHERE id=?',(len(ids),jid))
            resources = resource_map(conn) if channel in ('styles','layouts','colors') else None
            docs = []
            for i,entity in enumerate(ids):
                docs.extend(entity_documents(conn,channel,entity,indexing=True,resources=resources))
                if len(docs) >= 64 or i == len(ids)-1:
                    for start in range(0,len(docs),64):
                        self.engine.wait(self.engine.request('POST',f'/indexes/{shadow}/documents',docs[start:start+64]))
                    docs = []
                    conn.execute('UPDATE search_jobs SET done=? WHERE id=?',(i+1,jid))
                    self.process_events(32)
            if self.after_snapshot:
                self.after_snapshot(channel)
            seen = set()
            conn.execute("UPDATE search_jobs SET phase='catching_up' WHERE id=?",(jid,))
            self._replay(channel,epoch,shadow,seen)
            # Store swapping BEFORE submitting the non-idempotent operation.
            # If its response is lost, record unknown rather than swap again.
            conn.execute("UPDATE search_jobs SET status='swapping',phase='publishing' WHERE id=?",(jid,))
            with self.db.transaction() as tx:
                tx.execute('SELECT pg_advisory_xact_lock(266,0)')
                self._replay(channel,epoch,shadow,seen)
                swapping = True
                task = self.engine.request('POST','/swap-indexes',[{'indexes':[index_name(channel),shadow]}])
                swap_task_uid = task.get('taskUid') if isinstance(task, dict) else None
                tx.execute('UPDATE search_jobs SET task_uid=? WHERE id=?',(swap_task_uid,jid))
                self.engine.wait(task)
                stats = self.engine.request('GET',f'/indexes/{index_name(channel)}/stats')
                tx.execute("UPDATE search_jobs SET status='succeeded',phase='complete',finished_at=now() WHERE id=?",(jid,))
                tx.execute("UPDATE search_channels SET last_success_at=now(),document_count=?,last_error='' WHERE channel=?",(stats['numberOfDocuments'],channel))
            # The shadow now contains the superseded data, not the serving index.
            self.engine.wait(self.engine.request('DELETE',f'/indexes/{shadow}'))
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)[:250]
            if not swapping:
                try:
                    self.engine.wait(self.engine.request('DELETE',f'/indexes/{shadow}'))
                except Exception:
                    pass
            conn.execute('UPDATE search_jobs SET status=?,task_uid=COALESCE(?,task_uid),error=?,finished_at=now() WHERE id=?',('unknown' if swapping else 'failed',swap_task_uid,error,jid))
            conn.execute('UPDATE search_channels SET last_error=? WHERE channel=?',(error,channel))
            log.warning('Search rebuild failed: channel=%s error=%s',channel,type(exc).__name__)

    def tick(self):
        if time.monotonic()-self.last_manifest >= 30:
            self.sync_manifest()
        self.process_events()
        conn = self.db.get_conn()
        job = conn.execute("SELECT * FROM search_jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
        if job:
            self.rebuild(job)
        # Retention never removes events required by an in-progress rebuild.
        conn.execute("""DELETE FROM search_events e WHERE processed_at IS NOT NULL AND created_at<now()-interval '7 days'
            AND NOT EXISTS(SELECT 1 FROM search_jobs j WHERE j.channel=e.channel AND j.status IN ('running','swapping'))""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    args = parser.parse_args()
    from .postgres_db import PostgresDatabase
    db = PostgresDatabase(os.environ['HANDRAW_DATABASE_URL'])
    stop = threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,lambda *_:stop.set())
    logging.basicConfig(level=logging.INFO)
    try:
        worker = SearchWorker(db)
        worker.initialize()
        while not stop.is_set():
            try: worker.tick()
            except Exception: log.exception('Search worker iteration failed; retrying')
            if args.once: break
            stop.wait(1)
    finally:
        db.get_conn().execute('SELECT pg_advisory_unlock(266,1)')
        db.close()


if __name__ == '__main__':
    main()
