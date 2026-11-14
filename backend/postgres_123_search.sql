BEGIN;
CREATE TABLE IF NOT EXISTS search_channels (
 channel text PRIMARY KEY CHECK(channel IN ('styles','layouts','colors','works','forum')),
 epoch bigint NOT NULL DEFAULT 0,
 source_digest text NOT NULL DEFAULT '',
 last_success_at timestamptz,
 document_count bigint NOT NULL DEFAULT 0,
 last_error text NOT NULL DEFAULT ''
);
INSERT INTO search_channels(channel) VALUES ('styles'),('layouts'),('colors'),('works'),('forum') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS search_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 channel text NOT NULL REFERENCES search_channels(channel),
 entity_id text NOT NULL,
 epoch bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 processed_at timestamptz,
 attempts integer NOT NULL DEFAULT 0,
 retry_at timestamptz NOT NULL DEFAULT now(),
 error text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS search_events_pending ON search_events(retry_at,id) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS search_events_epoch ON search_events(channel,epoch,id);
CREATE TABLE IF NOT EXISTS search_resource_manifest (
 channel text NOT NULL REFERENCES search_channels(channel),
 entity_id text NOT NULL,
 fingerprint text NOT NULL,
 PRIMARY KEY(channel,entity_id)
);
CREATE TABLE IF NOT EXISTS search_jobs (
 id text PRIMARY KEY,
 channel text NOT NULL CHECK(channel IN ('styles','layouts','colors','works','forum')),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','swapping','succeeded','failed','unknown')),
 phase text NOT NULL DEFAULT '',
 epoch bigint,
 shadow_index text NOT NULL DEFAULT '',
 task_uid bigint,
 done bigint NOT NULL DEFAULT 0,
 total bigint NOT NULL DEFAULT 0,
 requested_by bigint REFERENCES users(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 finished_at timestamptz,
 error text NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS search_jobs_one_active ON search_jobs(channel) WHERE status IN ('queued','running','swapping');

CREATE OR REPLACE FUNCTION search_enqueue(ch text, ref text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF ref IS NULL OR ref='' THEN RETURN; END IF;
 -- Rebuild publication takes the exclusive counterpart. This establishes a
 -- commit barrier; sequence numbers alone do not order transaction commits.
 PERFORM pg_advisory_xact_lock_shared(266,0);
 INSERT INTO search_events(channel,entity_id,epoch)
 SELECT ch,ref,epoch FROM search_channels WHERE channel=ch;
END $$;

CREATE OR REPLACE FUNCTION search_capture_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE oldrow jsonb; newrow jsonb; r jsonb; ch text; ref text;
BEGIN
 IF TG_OP <> 'INSERT' THEN oldrow=to_jsonb(OLD); END IF;
 IF TG_OP <> 'DELETE' THEN newrow=to_jsonb(NEW); END IF;
 -- Ignore counters and other fields that never enter a search document.
 IF TG_OP='UPDATE' AND (oldrow - ARRAY['views','likes','favorites','cheers','tips','forks','stamp_counts_json','updated_at'])
     = (newrow - ARRAY['views','likes','favorites','cheers','tips','forks','stamp_counts_json','updated_at']) THEN RETURN NEW; END IF;
 FOR r IN SELECT value FROM jsonb_array_elements(jsonb_build_array(oldrow,newrow)) WHERE value <> 'null'::jsonb LOOP
  IF TG_TABLE_NAME='catalog_assets' THEN
   ch=CASE r->>'kind' WHEN 'style' THEN 'styles' WHEN 'layout' THEN 'layouts' WHEN 'color' THEN 'colors' ELSE NULL END;
   IF ch IS NOT NULL THEN PERFORM search_enqueue(ch,r->>'code'); END IF;
  ELSIF TG_TABLE_NAME='works' THEN
   PERFORM search_enqueue('works',r->>'id');
   FOR ref IN SELECT id FROM forum_topics WHERE work_id=r->>'id' LOOP PERFORM search_enqueue('forum',ref); END LOOP;
  ELSIF TG_TABLE_NAME='work_comments' THEN PERFORM search_enqueue('works',r->>'work_id');
  ELSIF TG_TABLE_NAME='forum_topics' THEN
   PERFORM search_enqueue('forum',r->>'id');
   IF COALESCE(r->>'work_id','')<>'' THEN PERFORM search_enqueue('works',r->>'work_id'); END IF;
  ELSIF TG_TABLE_NAME='forum_replies' THEN
   PERFORM search_enqueue('forum',r->>'topic_id');
   FOR ref IN
    SELECT work_id FROM forum_topics WHERE id=r->>'topic_id' AND work_id IS NOT NULL AND work_id<>''
    UNION
    SELECT target_id FROM curation_resource_topics WHERE kind='work' AND topic_id=r->>'topic_id'
   LOOP PERFORM search_enqueue('works',ref); END LOOP;
  ELSIF TG_TABLE_NAME='forum_boards' THEN
   FOR ref IN SELECT id FROM forum_topics WHERE category=r->>'key' LOOP PERFORM search_enqueue('forum',ref); END LOOP;
  END IF;
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['catalog_assets','works','work_comments','forum_topics','forum_replies','forum_boards'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS handraw_search_change ON %I',tab);
  EXECUTE format('CREATE TRIGGER handraw_search_change BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION search_capture_change()',tab);
 END LOOP;
END $$;
INSERT INTO schema_migrations(version,name,applied_at) VALUES(123,'search_outbox',CURRENT_TIMESTAMP::text) ON CONFLICT DO NOTHING;
COMMIT;
