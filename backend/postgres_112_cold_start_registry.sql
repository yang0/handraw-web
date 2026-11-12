SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS public.cold_start_registry (
    pack_id text NOT NULL,
    kind text NOT NULL,
    item_id text NOT NULL,
    created_at text NOT NULL,
    UNIQUE (kind, item_id)
);

CREATE INDEX IF NOT EXISTS idx_cold_start_registry_pack
    ON public.cold_start_registry (pack_id, kind, item_id);

INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES (112, '112_cold_start_registry', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
