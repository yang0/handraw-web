SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE OR REPLACE FUNCTION public.notify_forum_reply() RETURNS trigger
LANGUAGE plpgsql SET search_path TO public, pg_catalog AS $$
BEGIN
    INSERT INTO public.notifications (user_id, kind, title, target_type, target_id, created_at)
    SELECT u.id, 'reply', '你的帖子有新回复', 'topic', NEW.topic_id, NEW.created_at
    FROM public.forum_topics AS t
    JOIN public.users AS u ON u.username = t.author_username
    WHERE t.id = NEW.topic_id AND u.username <> NEW.author_username;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER notify_forum_reply AFTER INSERT ON public.forum_replies
    FOR EACH ROW WHEN (NEW.status = 'published' AND NEW.legacy_source = '')
    EXECUTE FUNCTION public.notify_forum_reply();

INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES (113, '113_forum_reply_notifications', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
