SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE INDEX IF NOT EXISTS idx_works_published_author_feed
    ON public.works (LOWER(author_username), published_at_ms DESC, id DESC)
    WHERE status = 'published';

INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES (115, '115_published_author_feed', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
