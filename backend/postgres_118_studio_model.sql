-- Independent authoring documents, stable illustration slots and execution links.
ALTER TABLE public.studio_articles ADD COLUMN IF NOT EXISTS write_seq bigint NOT NULL DEFAULT 0;
ALTER TABLE public.studio_articles ADD COLUMN IF NOT EXISTS settings_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.studio_articles ADD COLUMN IF NOT EXISTS illustrations_ready boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_article_owner_page ON public.studio_articles(user_id,updated_at_ms DESC,id) WHERE deleted_at='';

CREATE TABLE IF NOT EXISTS public.studio_canvases (
    id text PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES public.users(id),
    name text NOT NULL,
    graph_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    write_seq bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CHECK (jsonb_typeof(graph_json) = 'object')
);
CREATE INDEX IF NOT EXISTS idx_canvases_owner_recent ON public.studio_canvases(user_id, updated_at DESC, id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.article_illustrations (
    id text PRIMARY KEY,
    article_id text NOT NULL REFERENCES public.studio_articles(id),
    local_id text NOT NULL,
    role text NOT NULL DEFAULT 'inline' CHECK (role IN ('cover', 'inline')),
    sort_order bigint NOT NULL,
    anchor_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    spec_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    spec_hash text NOT NULL,
    selected_media_id text REFERENCES public.media_assets(id),
    active_attempt_id text REFERENCES public.studio_generations(id),
    result_epoch bigint NOT NULL DEFAULT 0 CHECK (result_epoch >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (article_id, local_id),
    CHECK (jsonb_typeof(spec_json) = 'object' AND jsonb_typeof(anchor_json) = 'object')
);
CREATE INDEX IF NOT EXISTS idx_article_illustrations_order ON public.article_illustrations(article_id, sort_order, id) WHERE deleted_at IS NULL;
ALTER TABLE public.article_illustrations ADD COLUMN IF NOT EXISTS result_epoch bigint NOT NULL DEFAULT 0;

ALTER TABLE public.generation_runs ADD COLUMN IF NOT EXISTS creation_mode text NOT NULL DEFAULT 'other';
ALTER TABLE public.generation_runs ADD COLUMN IF NOT EXISTS article_id text REFERENCES public.studio_articles(id);
ALTER TABLE public.generation_runs ADD COLUMN IF NOT EXISTS canvas_id text REFERENCES public.studio_canvases(id);
ALTER TABLE public.generation_runs ADD COLUMN IF NOT EXISTS plan_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS ordinal bigint;
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS retired_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS idx_generation_plan_ordinal ON public.generation_items(run_id,ordinal) WHERE ordinal IS NOT NULL;
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS spec_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS illustration_id text REFERENCES public.article_illustrations(id);
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS dispatch_request_id text NOT NULL DEFAULT '';
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS dispatch_token text;
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS dispatch_until timestamptz;
ALTER TABLE public.generation_items ADD COLUMN IF NOT EXISTS dispatch_after timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_canvas_dispatch ON public.generation_items(dispatch_after,run_id,ordinal)
    WHERE status='pending';
CREATE INDEX IF NOT EXISTS idx_canvas_runs_recent ON public.generation_runs(canvas_id,user_id,created_at DESC,id)
    WHERE creation_mode='canvas';
CREATE TABLE IF NOT EXISTS public.canvas_run_requests (
    run_id text NOT NULL REFERENCES public.generation_runs(id),
    request_id text NOT NULL,
    payload_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(run_id,request_id)
);
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS run_id text REFERENCES public.generation_runs(id);
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS item_id text REFERENCES public.generation_items(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS attempt_no bigint;
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS input_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS illustration_spec_hash text NOT NULL DEFAULT '';
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS illustration_epoch bigint;
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS next_poll_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS poll_claim_until timestamptz;
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS poll_claim_token text;
ALTER TABLE public.studio_generations ADD COLUMN IF NOT EXISTS poll_failures bigint NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_studio_attempt_item ON public.studio_generations(item_id, created_at, id) WHERE item_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_studio_attempt_run ON public.studio_generations(run_id) WHERE run_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_studio_attempt_number ON public.studio_generations(item_id,attempt_no) WHERE item_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_studio_poll_due ON public.studio_generations(next_poll_at, created_at, id) WHERE engine='live' AND status IN ('queued','running') AND deleted_at='';
CREATE INDEX IF NOT EXISTS idx_studio_owner_pending ON public.studio_generations(user_id,created_at DESC,id)
    WHERE deleted_at='' AND status IN ('queued','running');

ALTER TABLE public.studio_import_jobs ADD COLUMN IF NOT EXISTS input_storage_key text NOT NULL DEFAULT '';
ALTER TABLE public.studio_import_jobs ADD COLUMN IF NOT EXISTS input_sha256 text NOT NULL DEFAULT '';
ALTER TABLE public.studio_import_jobs ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE public.studio_import_jobs ADD COLUMN IF NOT EXISTS lease_until timestamptz;
ALTER TABLE public.studio_import_jobs ADD COLUMN IF NOT EXISTS claim_count bigint NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_import_claim ON public.studio_import_jobs(status,lease_until,created_at,id)
    WHERE status IN ('queued','running') AND input_storage_key<>'';

CREATE TABLE IF NOT EXISTS public.generation_attempt_media (
    attempt_id text NOT NULL REFERENCES public.studio_generations(id),
    media_id text NOT NULL REFERENCES public.media_assets(id),
    ordinal bigint NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (attempt_id, ordinal),
    UNIQUE (attempt_id, media_id)
);

-- Keep source ownership enforced even when callers bypass HTTP validation.
CREATE OR REPLACE FUNCTION public.guard_studio_run_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.creation_mode='article' AND NEW.article_id IS NULL OR NEW.creation_mode='canvas' AND NEW.canvas_id IS NULL
    THEN RAISE EXCEPTION 'missing_studio_run_source'; END IF;
    IF NEW.article_id IS NOT NULL AND (
        NEW.canvas_id IS NOT NULL OR NEW.creation_mode <> 'article' OR NOT EXISTS (
            SELECT 1 FROM public.studio_articles a WHERE a.id=NEW.article_id AND a.user_id=NEW.user_id
        )
    ) THEN RAISE EXCEPTION 'invalid_article_run_owner'; END IF;
    IF NEW.canvas_id IS NOT NULL AND (
        NEW.creation_mode <> 'canvas' OR NOT EXISTS (
            SELECT 1 FROM public.studio_canvases c WHERE c.id=NEW.canvas_id AND c.user_id=NEW.user_id
        )
    ) THEN RAISE EXCEPTION 'invalid_canvas_run_owner'; END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER guard_studio_run_source BEFORE INSERT OR UPDATE OF user_id,article_id,canvas_id,creation_mode ON public.generation_runs FOR EACH ROW EXECUTE FUNCTION public.guard_studio_run_source();

CREATE OR REPLACE FUNCTION public.guard_article_media() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.selected_media_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.media_assets m JOIN public.studio_articles a ON a.user_id=m.owner_user_id
        WHERE m.id=NEW.selected_media_id AND a.id=NEW.article_id
    ) THEN RAISE EXCEPTION 'invalid_article_media_owner'; END IF;
    IF NEW.active_attempt_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.studio_generations g JOIN public.generation_items t ON t.id=g.item_id
        JOIN public.studio_articles a ON a.id=NEW.article_id
        WHERE g.id=NEW.active_attempt_id AND t.illustration_id=NEW.id AND g.user_id=a.user_id AND g.run_id=t.run_id
    ) THEN RAISE EXCEPTION 'invalid_article_active_attempt'; END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER guard_article_media BEFORE INSERT OR UPDATE OF article_id,selected_media_id,active_attempt_id ON public.article_illustrations FOR EACH ROW EXECUTE FUNCTION public.guard_article_media();

CREATE OR REPLACE FUNCTION public.guard_attempt_media_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.studio_generations g JOIN public.media_assets m ON m.owner_user_id=g.user_id
        WHERE g.id=NEW.attempt_id AND m.id=NEW.media_id
    ) THEN RAISE EXCEPTION 'invalid_attempt_media_owner'; END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER guard_attempt_media_owner BEFORE INSERT OR UPDATE ON public.generation_attempt_media FOR EACH ROW EXECUTE FUNCTION public.guard_attempt_media_owner();

CREATE OR REPLACE FUNCTION public.guard_studio_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.item_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.generation_items i JOIN public.generation_runs r ON r.id=i.run_id
        WHERE i.id=NEW.item_id AND r.id=NEW.run_id AND r.user_id=NEW.user_id
    ) THEN RAISE EXCEPTION 'invalid_attempt_item_owner'; END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER guard_studio_attempt BEFORE INSERT OR UPDATE OF user_id,run_id,item_id ON public.studio_generations FOR EACH ROW EXECUTE FUNCTION public.guard_studio_attempt();

CREATE OR REPLACE FUNCTION public.guard_illustration_item() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.illustration_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.article_illustrations i JOIN public.generation_runs r ON r.article_id=i.article_id
        WHERE i.id=NEW.illustration_id AND r.id=NEW.run_id
    ) THEN RAISE EXCEPTION 'invalid_illustration_item_source'; END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER guard_illustration_item BEFORE INSERT OR UPDATE OF run_id,illustration_id ON public.generation_items FOR EACH ROW EXECUTE FUNCTION public.guard_illustration_item();

INSERT INTO public.schema_migrations(version,name,applied_at)
VALUES (118,'118_studio_model',to_char(now() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
