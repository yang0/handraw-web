-- Rename existing unique indexes without changing their keys or data.
DO $$
DECLARE target record; current_name text;
BEGIN
    FOR target IN SELECT * FROM (VALUES
        ('api_tokens', ARRAY['token_hash']::text[], 'uq_api_tokens_token_hash'),
        ('curation_assignments', ARRAY['submission_id','revision','reviewer_username']::text[], 'uq_curation_assignments_submission_revision_reviewer'),
        ('curation_requests', ARRAY['owner_username','request_id']::text[], 'uq_curation_requests_owner_username_request_id'),
        ('curation_submissions', ARRAY['kind','target_id']::text[], 'uq_curation_submissions_kind_target_id'),
        ('curation_versions', ARRAY['submission_id','revision']::text[], 'uq_curation_versions_submission_revision'),
        ('curation_votes', ARRAY['assignment_id']::text[], 'uq_curation_votes_assignment_id'),
        ('device_codes', ARRAY['user_code']::text[], 'uq_device_codes_user_code'),
        ('dm_conversations', ARRAY['user_low_id','user_high_id']::text[], 'uq_dm_conversations_user_low_id_user_high_id'),
        ('dm_messages', ARRAY['sender_id','client_message_id']::text[], 'uq_dm_messages_sender_id_client_message_id'),
        ('forum_moderators', ARRAY['username','category']::text[], 'uq_forum_moderators_username_category'),
        ('generation_items', ARRAY['run_id','position']::text[], 'uq_generation_items_run_id_position'),
        ('generation_runs', ARRAY['user_id','source','external_run_id']::text[], 'uq_generation_runs_user_id_source_external_run_id'),
        ('ledgers', ARRAY['user_id','event_key']::text[], 'uq_ledgers_user_id_event_key'),
        ('media_assets', ARRAY['owner_user_id','storage_key']::text[], 'uq_media_assets_owner_user_id_storage_key'),
        ('media_public_grants', ARRAY['media_url','target_type','target_id']::text[], 'uq_media_public_grants_media_url_target_type_target_id'),
        ('oauth_identities', ARRAY['provider','user_id']::text[], 'uq_oauth_identities_provider_user_id'),
        ('studio_generation_media', ARRAY['generation_id','media_url']::text[], 'uq_studio_generation_media_generation_id_media_url'),
        ('unlocks', ARRAY['user_id','target_type','target_id']::text[], 'uq_unlocks_user_id_target_type_target_id'),
        ('users', ARRAY['username']::text[], 'uq_users_username'),
        ('users', ARRAY['email']::text[], 'uq_users_email'),
        ('users', ARRAY['invite_code']::text[], 'uq_users_invite_code'),
        ('users', ARRAY['api_key']::text[], 'uq_users_api_key'),
        ('work_media', ARRAY['work_id','position']::text[], 'uq_work_media_work_id_position')
    ) AS keys(table_name, column_names, desired_name)
    LOOP
        IF to_regclass('public.' || target.desired_name) IS NOT NULL THEN CONTINUE; END IF;
        SELECT idx.relname INTO current_name
        FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class tbl ON tbl.oid=i.indrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid=tbl.relnamespace
        JOIN pg_catalog.pg_class idx ON idx.oid=i.indexrelid
        WHERE ns.nspname='public' AND tbl.relname=target.table_name
          AND i.indisunique AND NOT i.indisprimary AND i.indexprs IS NULL AND i.indpred IS NULL
          AND (SELECT array_agg(a.attname::text ORDER BY k.pos)
               FROM unnest(i.indkey) WITH ORDINALITY k(attnum,pos)
               JOIN pg_catalog.pg_attribute a ON a.attrelid=tbl.oid AND a.attnum=k.attnum
              ) = target.column_names
        ORDER BY idx.relname LIMIT 1;
        IF current_name IS NOT NULL THEN
            EXECUTE format('ALTER INDEX public.%I RENAME TO %I', current_name, target.desired_name);
        END IF;
    END LOOP;
END $$;

INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES (117, '117_unique_index_names', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (version) DO NOTHING;
