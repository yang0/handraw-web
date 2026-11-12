-- Notify only after a supported income ledger entry is inserted.
-- Replayed wallet events do not insert another ledger row or notification.
CREATE OR REPLACE FUNCTION public.notify_wallet_income() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.notifications
        (user_id, kind, title, target_type, target_id, created_at)
    VALUES
        (NEW.user_id, 'wallet', NEW.reason,
         CASE WHEN NEW.ref_type <> '' THEN NEW.ref_type ELSE 'wallet' END,
         NEW.ref_id, NEW.created_at);
    RETURN NEW;
END $$;

CREATE OR REPLACE TRIGGER notify_wallet_income AFTER INSERT ON public.ledgers
    FOR EACH ROW WHEN (
        NEW.delta > 0 AND NEW.kind IN (
            'unlock_income', 'tip_income', 'bounty_reward', 'studio_refund',
            'refund', 'tip_in', 'tip_official_in', 'unlock_royalty',
            'bounty_win', 'unlock_refund', 'bounty_admin_award',
            'bounty_admin_refund', 'admin_grant'
        )
    ) EXECUTE FUNCTION public.notify_wallet_income();

INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES (116, '116_wallet_notifications', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
