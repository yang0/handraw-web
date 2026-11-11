-- Apply in one transaction on an existing Handraw V3 database.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE INDEX IF NOT EXISTS idx_works_published_ratio
    ON public.works (ratio) WHERE status = 'published';

INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES (110, '110_home_scenario_ratio', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
