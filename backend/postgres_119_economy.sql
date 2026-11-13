-- Additive separation of cash, points and specification-scoped entitlements.
SET LOCAL lock_timeout='5s';
SELECT pg_advisory_xact_lock(186,119);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version=119)
 AND EXISTS(SELECT 1 FROM payment_orders WHERE test_mode=0 AND status NOT IN ('failed','expired','cancelled')) THEN
  RAISE EXCEPTION 'Real payment history exists: reconcile purchased balances before economy cutover';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS cash_accounts (
 user_id bigint PRIMARY KEY REFERENCES users(id), balance_cents bigint NOT NULL DEFAULT 0,
 held_cents bigint NOT NULL DEFAULT 0 CHECK(held_cents>=0), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS cash_entries (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id),
 event_key text NOT NULL UNIQUE, kind text NOT NULL, delta_cents bigint NOT NULL,
 held_delta_cents bigint NOT NULL DEFAULT 0, balance_after_cents bigint NOT NULL,
 ref_id text NOT NULL DEFAULT '', reason text NOT NULL DEFAULT '', actor_id bigint REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cash_entries_user ON cash_entries(user_id,id DESC);
CREATE TABLE IF NOT EXISTS cash_lots (
 order_id text PRIMARY KEY REFERENCES payment_orders(id), user_id bigint NOT NULL REFERENCES users(id),
 remaining_cents bigint NOT NULL CHECK(remaining_cents>=0), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS generation_specs (
 id text PRIMARY KEY, name text NOT NULL, model text NOT NULL, resolution text NOT NULL,
 quality text NOT NULL DEFAULT 'auto', sizes_json jsonb NOT NULL, price_cents bigint CHECK(price_cents>0),
 cost_cents bigint CHECK(cost_cents>=0), version bigint NOT NULL DEFAULT 1,
 enabled boolean NOT NULL DEFAULT false, verified boolean NOT NULL DEFAULT false
);
INSERT INTO generation_specs(id,name,model,resolution,sizes_json,enabled,verified)
VALUES('standard-1k','标准 1K','gpt-image-2','1k',
 '{"1:1":"1024x1024","3:4":"1152x1536","4:3":"1536x1152","9:16":"864x1536","16:9":"1536x864","2.35:1":"1536x656","3:2":"1536x1024","2:3":"1024x1536"}',true,false)
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS generation_quota_policy (
 resolution text PRIMARY KEY, base_units bigint NOT NULL CHECK(base_units>=0), version bigint NOT NULL DEFAULT 1
);
INSERT INTO generation_quota_policy VALUES('1k',10,1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS generation_quota_grants (
 id text PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id), resolution text NOT NULL,
 units bigint NOT NULL CHECK(units>0), event_key text NOT NULL, reason text NOT NULL,
 actor_id bigint NOT NULL REFERENCES users(id), expires_at timestamptz,
 revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(user_id,event_key)
);
CREATE INDEX IF NOT EXISTS quota_grants_owner ON generation_quota_grants(user_id,resolution);
CREATE TABLE IF NOT EXISTS generation_quotes (
 id text PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id), items_json jsonb NOT NULL,
 total_cents bigint NOT NULL CHECK(total_cents>=0), expires_at timestamptz NOT NULL,
 reserved_at timestamptz, request_key text, batch_key text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(user_id,request_key)
);
CREATE TABLE IF NOT EXISTS generation_charges (
 id text PRIMARY KEY, quote_id text NOT NULL REFERENCES generation_quotes(id), position integer NOT NULL,
 user_id bigint NOT NULL REFERENCES users(id), generation_id text UNIQUE REFERENCES studio_generations(id),
 item_id text REFERENCES generation_items(id), spec_json jsonb NOT NULL, resolution text NOT NULL,
 slot_position integer,
 quota_source text, amount_cents bigint NOT NULL CHECK(amount_cents>=0),
 status text NOT NULL DEFAULT 'reserved' CHECK(status IN ('reserved','settled','released')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(quote_id,position)
);
CREATE INDEX IF NOT EXISTS charges_quota_usage ON generation_charges(user_id,resolution,status) WHERE quota_source IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS charges_item_active ON generation_charges(item_id) WHERE status='reserved';
CREATE TABLE IF NOT EXISTS cash_allocations (
 charge_id text NOT NULL REFERENCES generation_charges(id), order_id text NOT NULL REFERENCES cash_lots(order_id),
 amount_cents bigint NOT NULL CHECK(amount_cents>0), PRIMARY KEY(charge_id,order_id)
);
CREATE TABLE IF NOT EXISTS point_lots (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id),
 source_key text NOT NULL UNIQUE, source_kind text NOT NULL, payment_order_id text,
 original_units bigint NOT NULL CHECK(original_units>=0), remaining_units bigint NOT NULL CHECK(remaining_units>=0),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS economy_cutover_state (
 id integer PRIMARY KEY CHECK(id=1), legacy_ledger_id bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO economy_cutover_state(id,legacy_ledger_id) SELECT 1,COALESCE(max(id),0) FROM ledgers ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS point_lots_owner ON point_lots(user_id,id) WHERE remaining_units>0;
CREATE TABLE IF NOT EXISTS point_allocations (
 ledger_id bigint NOT NULL REFERENCES ledgers(id), lot_id bigint NOT NULL REFERENCES point_lots(id),
 units bigint NOT NULL CHECK(units>0), restored_units bigint NOT NULL DEFAULT 0 CHECK(restored_units>=0 AND restored_units<=units),
 PRIMARY KEY(ledger_id,lot_id)
);
CREATE TABLE IF NOT EXISTS creator_point_earnings (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, unlock_id bigint NOT NULL REFERENCES unlocks(id),
 purchase_seq bigint NOT NULL DEFAULT 1,
 author_id bigint NOT NULL REFERENCES users(id), units bigint NOT NULL CHECK(units>=0),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','settled','reversed')),
 available_at timestamptz NOT NULL DEFAULT now()+interval '7 days', settled_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(unlock_id,purchase_seq)
);
CREATE INDEX IF NOT EXISTS creator_earnings_due ON creator_point_earnings(author_id,available_at) WHERE status='pending';
CREATE TABLE IF NOT EXISTS point_price_options (
 kind text PRIMARY KEY, options_json jsonb NOT NULL
);
INSERT INTO point_price_options VALUES('topic','[0,5,10,20,50,100]'),('asset','[0,10,30,50,100,200,500]') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS contribution_rewards (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id),
 kind text NOT NULL, target_id text NOT NULL, month text NOT NULL, units bigint NOT NULL,
 actor_id bigint REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(kind,target_id)
);
CREATE TABLE IF NOT EXISTS billing_refund_requests (
 id text PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id), order_id text NOT NULL REFERENCES payment_orders(id),
 reason text NOT NULL, status text NOT NULL DEFAULT 'pending', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS refund_request_active ON billing_refund_requests(order_id) WHERE status='pending';
ALTER TABLE billing_refund_requests ADD COLUMN IF NOT EXISTS amount_cents bigint NOT NULL DEFAULT 0;
ALTER TABLE billing_refund_requests ADD COLUMN IF NOT EXISTS units bigint NOT NULL DEFAULT 0;
ALTER TABLE billing_refund_requests ADD COLUMN IF NOT EXISTS provider_result jsonb;
ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT 'points';
ALTER TABLE unlocks ADD COLUMN IF NOT EXISTS purchase_seq bigint NOT NULL DEFAULT 1;
ALTER TABLE studio_generations ADD COLUMN IF NOT EXISTS spec_id text;
ALTER TABLE studio_generations ADD COLUMN IF NOT EXISTS amount_cents bigint NOT NULL DEFAULT 0;
ALTER TABLE studio_generations ADD COLUMN IF NOT EXISTS billing_snapshot jsonb;
INSERT INTO creator_point_earnings(unlock_id,purchase_seq,author_id,units,status,settled_at)
SELECT u.id,u.purchase_seq,a.id,u.author_share,CASE WHEN u.status='settled' THEN 'settled' ELSE 'reversed' END,now()
FROM unlocks u JOIN users a ON a.username=u.author_username
WHERE u.author_share>0 AND a.id<>u.user_id AND NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version=119)
ON CONFLICT(unlock_id,purchase_seq) DO NOTHING;
INSERT INTO point_lots(user_id,source_key,source_kind,original_units,remaining_units)
SELECT w.user_id,'cutover:'||w.user_id,'legacy',w.balance,w.balance FROM wallets w WHERE w.balance>0 AND NOT EXISTS(SELECT 1 FROM point_lots l WHERE l.user_id=w.user_id)
ON CONFLICT(source_key) DO NOTHING;

CREATE OR REPLACE FUNCTION award_verified_account_points() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ledger_id bigint; old_balance bigint; new_balance bigint; inserted_id bigint;
BEGIN
 SELECT balance INTO old_balance FROM wallets WHERE user_id=NEW.user_id FOR UPDATE;
 IF NOT FOUND THEN RETURN NEW; END IF;
 INSERT INTO contribution_rewards(user_id,kind,target_id,month,units)
 VALUES(NEW.user_id,'verified',NEW.user_id::text,to_char(now() AT TIME ZONE 'Asia/Shanghai','YYYY-MM'),20)
 ON CONFLICT(kind,target_id) DO NOTHING RETURNING id INTO inserted_id;
 IF inserted_id IS NULL THEN RETURN NEW; END IF;
 UPDATE wallets SET balance=balance+20,updated_at=CURRENT_TIMESTAMP::text WHERE user_id=NEW.user_id RETURNING balance INTO new_balance;
 INSERT INTO ledgers(user_id,delta,balance_after,kind,event_key,reason,ref_type,ref_id,created_at)
 VALUES(NEW.user_id,20,new_balance,'contribution_verified','contribution:verified:'||NEW.user_id,'完成账号验证奖励','verified',NEW.user_id::text,CURRENT_TIMESTAMP::text) RETURNING id INTO ledger_id;
 INSERT INTO point_lots(user_id,source_key,source_kind,original_units,remaining_units)
 VALUES(NEW.user_id,'ledger:'||ledger_id,'earned',20,GREATEST(0,new_balance)-GREATEST(0,old_balance));
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER verified_account_points AFTER INSERT OR UPDATE ON verified_emails
FOR EACH ROW EXECUTE FUNCTION award_verified_account_points();
INSERT INTO schema_migrations(version,name,applied_at) VALUES(119,'119_separate_cash_points_quota',CURRENT_TIMESTAMP::text) ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION reject_economy_ledger_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Financial ledgers are append-only; post a compensating entry';
END $$;
CREATE OR REPLACE TRIGGER cash_entries_append_only BEFORE UPDATE OR DELETE ON cash_entries
FOR EACH ROW EXECUTE FUNCTION reject_economy_ledger_mutation();
CREATE OR REPLACE TRIGGER point_entries_append_only BEFORE UPDATE OR DELETE ON ledgers
FOR EACH ROW EXECUTE FUNCTION reject_economy_ledger_mutation();
