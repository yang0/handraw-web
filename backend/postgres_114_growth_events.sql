SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE OR REPLACE FUNCTION public.capture_growth_milestone() RETURNS trigger
LANGUAGE plpgsql SET search_path TO public, pg_catalog AS $$
DECLARE
    account_id bigint;
    event_name text := TG_ARGV[0];
    event_time text;
BEGIN
    CASE event_name
        WHEN 'first_work', 'first_topic' THEN
            SELECT id INTO account_id FROM public.users WHERE username = NEW.author_username;
            event_time := NEW.created_at;
        WHEN 'email_verified' THEN
            account_id := NEW.user_id;
            event_time := NEW.verified_at;
        ELSE
            account_id := NEW.user_id;
            event_time := NEW.created_at;
    END CASE;

    IF TG_OP = 'UPDATE' AND event_name <> 'email_verified' THEN
        event_time := to_char(statement_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
    END IF;

    IF account_id IS NOT NULL AND length(event_time) >= 10 THEN
        INSERT INTO public.growth_events (user_id, event_name, event_day, happened_at)
        VALUES (account_id, event_name, left(event_time, 10), event_time)
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER growth_collection_insert AFTER INSERT ON public.collections
    FOR EACH ROW EXECUTE FUNCTION public.capture_growth_milestone('first_collection');

CREATE OR REPLACE TRIGGER growth_work_insert AFTER INSERT ON public.works
    FOR EACH ROW WHEN (NEW.status = 'published')
    EXECUTE FUNCTION public.capture_growth_milestone('first_work');

CREATE OR REPLACE TRIGGER growth_work_publish AFTER UPDATE OF status ON public.works
    FOR EACH ROW WHEN (NEW.status = 'published' AND OLD.status <> 'published')
    EXECUTE FUNCTION public.capture_growth_milestone('first_work');

CREATE OR REPLACE TRIGGER growth_topic_insert AFTER INSERT ON public.forum_topics
    FOR EACH ROW WHEN (NEW.status = 'published')
    EXECUTE FUNCTION public.capture_growth_milestone('first_topic');

CREATE OR REPLACE TRIGGER growth_topic_publish AFTER UPDATE OF status ON public.forum_topics
    FOR EACH ROW WHEN (NEW.status = 'published' AND OLD.status <> 'published')
    EXECUTE FUNCTION public.capture_growth_milestone('first_topic');

CREATE OR REPLACE TRIGGER growth_studio_insert AFTER INSERT ON public.studio_generations
    FOR EACH ROW WHEN (NEW.status = 'success')
    EXECUTE FUNCTION public.capture_growth_milestone('first_generation');

CREATE OR REPLACE TRIGGER growth_studio_success AFTER UPDATE OF status ON public.studio_generations
    FOR EACH ROW WHEN (NEW.status = 'success' AND OLD.status <> 'success')
    EXECUTE FUNCTION public.capture_growth_milestone('first_generation');

CREATE OR REPLACE TRIGGER growth_run_insert AFTER INSERT ON public.generation_runs
    FOR EACH ROW WHEN (NEW.status IN ('success', 'partial'))
    EXECUTE FUNCTION public.capture_growth_milestone('first_generation');

CREATE OR REPLACE TRIGGER growth_run_success AFTER UPDATE OF status ON public.generation_runs
    FOR EACH ROW WHEN (NEW.status IN ('success', 'partial') AND OLD.status NOT IN ('success', 'partial'))
    EXECUTE FUNCTION public.capture_growth_milestone('first_generation');

CREATE OR REPLACE TRIGGER growth_email_verified AFTER INSERT OR UPDATE OF verified_at ON public.verified_emails
    FOR EACH ROW EXECUTE FUNCTION public.capture_growth_milestone('email_verified');

CREATE INDEX IF NOT EXISTS idx_growth_activation_user_time
    ON public.growth_events (user_id, happened_at)
    WHERE event_name IN ('first_collection', 'first_work', 'first_topic', 'first_generation');

CREATE INDEX IF NOT EXISTS idx_growth_registered_users_time
    ON public.users (created_at)
    WHERE role = 'user' AND discourse_user_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_auth_funnel_time_event
    ON public.auth_funnel_events (created_at, event_name);

INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES (114, '114_growth_events', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
