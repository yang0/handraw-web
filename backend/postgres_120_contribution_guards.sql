-- Preserve contribution identity and pause automated rewards under points risk lock.
SET LOCAL lock_timeout='5s';
SELECT pg_advisory_xact_lock(186,120);
CREATE TABLE IF NOT EXISTS contribution_reward_content (
 kind text NOT NULL, fingerprint text NOT NULL,
 reward_id bigint NOT NULL REFERENCES contribution_rewards(id),
 PRIMARY KEY(kind,fingerprint), UNIQUE(reward_id)
);
CREATE OR REPLACE FUNCTION public.v3_safe_jsonb_array(raw text) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE val jsonb;
BEGIN
 IF raw IS NULL OR btrim(raw) = '' THEN RETURN '[]'::jsonb; END IF;
 val := raw::jsonb;
 IF jsonb_typeof(val) = 'array' THEN RETURN val; END IF;
 RETURN '[]'::jsonb;
EXCEPTION WHEN OTHERS THEN
 RETURN '[]'::jsonb;
END $$;
CREATE OR REPLACE FUNCTION contribution_fingerprint(reward_kind text,target text) RETURNS text LANGUAGE SQL STABLE AS $$
 SELECT encode(sha256(convert_to(payload,'UTF8')),'hex') FROM (
  SELECT COALESCE((
    SELECT string_agg(DISTINCT identity_key,chr(31) ORDER BY identity_key) FROM (
      SELECT COALESCE(NULLIF((SELECT m.sha256 FROM media_assets m WHERE m.storage_key=images.image_url AND m.sha256<>'' LIMIT 1),''),
                      NULLIF((SELECT u.sha256 FROM user_uploads u WHERE u.image_url=images.image_url AND u.sha256<>'' LIMIT 1),''),image_url) identity_key
      FROM (SELECT CASE WHEN jsonb_typeof(value)='string' THEN value#>>'{}'
                    ELSE COALESCE(value->>'url',value->>'imageUrl','') END image_url
            FROM jsonb_array_elements(public.v3_safe_jsonb_array(w.images_json))) images
      WHERE image_url<>''
    ) identities
  ),regexp_replace(w.prompt,'\s+','','g')) payload
  FROM works w WHERE reward_kind='quality_work' AND w.id=target
  UNION ALL
  SELECT regexp_replace(summary,'\s+','','g')||chr(31)||regexp_replace(locked_body,'\s+','','g')
  FROM forum_topics WHERE reward_kind='quality_topic' AND id=target
  UNION ALL
  SELECT regexp_replace(definition,'\s+','','g')
  FROM catalog_assets WHERE reward_kind='asset' AND upper(code)=upper(target)
 ) content LIMIT 1
$$;
INSERT INTO contribution_reward_content(kind,fingerprint,reward_id)
SELECT kind,contribution_fingerprint(kind,target_id),id FROM contribution_rewards
WHERE kind IN ('quality_work','quality_topic','asset') AND contribution_fingerprint(kind,target_id) IS NOT NULL
ORDER BY id ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION award_verified_account_points() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ledger_id bigint; old_balance bigint; new_balance bigint; inserted_id bigint; risk_locked bigint;
BEGIN
 SELECT balance,locked INTO old_balance,risk_locked FROM wallets WHERE user_id=NEW.user_id FOR UPDATE;
 IF NOT FOUND OR risk_locked<>0 THEN RETURN NEW; END IF;
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
INSERT INTO schema_migrations(version,name,applied_at) VALUES(120,'120_contribution_identity_and_risk_pause',CURRENT_TIMESTAMP::text) ON CONFLICT DO NOTHING;
