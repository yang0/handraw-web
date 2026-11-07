"""Native PostgreSQL constraints for the fresh Handraw V3 business schema.

The full site has many auxiliary tables (accounts, forum, styling, billing).
Those are bootstrapped from the current, freshly generated schema; these
PostgreSQL-native definitions enforce V3's crucial transactional invariants.
All statements are intended for a brand-new empty database.
"""

NATIVE_V3_SQL = r"""
-- Native FKs absent from SQLite's ALTER TABLE ADD COLUMN syntax.
ALTER TABLE works ADD CONSTRAINT fk_works_run_v3
    FOREIGN KEY (run_id) REFERENCES generation_runs(id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE works ADD CONSTRAINT fk_works_cover_v3
    FOREIGN KEY (cover_media_id) REFERENCES media_assets(id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE works ADD CONSTRAINT chk_work_cover_author_choice_v3
    CHECK (cover_selected_by_author IN (0,1));

ALTER TABLE generation_runs ADD CONSTRAINT chk_run_source_v3
    CHECK (source IN ('web','skill','api'));
ALTER TABLE generation_runs ADD CONSTRAINT chk_run_count_v3
    CHECK (expected_count >= 1);
ALTER TABLE generation_runs ADD CONSTRAINT chk_run_status_v3
    CHECK (status IN ('pending','uploading','running','partial','success','failed','cancelled'));
ALTER TABLE generation_items ADD CONSTRAINT chk_item_position_v3
    CHECK (position >= 0);
ALTER TABLE generation_items ADD CONSTRAINT chk_item_status_v3
    CHECK (status IN ('pending','generating','success','failed','cancelled'));
ALTER TABLE generation_items ADD CONSTRAINT chk_item_success_media_v3
    CHECK (status <> 'success' OR media_id IS NOT NULL);
ALTER TABLE work_media ADD CONSTRAINT chk_work_media_position_v3
    CHECK (position >= 0);
ALTER TABLE media_assets ADD CONSTRAINT chk_media_dimension_v3
    CHECK ((width IS NULL OR width > 0)
       AND (height IS NULL OR height > 0)
       AND (size_bytes IS NULL OR size_bytes >= 0));

-- A run and media object have an immutable owner and identity.
CREATE OR REPLACE FUNCTION v3_immutable_generation_run() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.user_id IS DISTINCT FROM OLD.user_id OR
       NEW.source IS DISTINCT FROM OLD.source OR
       NEW.external_run_id IS DISTINCT FROM OLD.external_run_id THEN
       RAISE EXCEPTION 'run_identity_is_immutable';
    END IF;
    RETURN NEW;
END $fn$;
CREATE TRIGGER v3_run_immutable BEFORE UPDATE OF user_id,source,external_run_id
    ON generation_runs FOR EACH ROW EXECUTE FUNCTION v3_immutable_generation_run();

CREATE OR REPLACE FUNCTION v3_immutable_media_identity() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id OR
       NEW.storage_key IS DISTINCT FROM OLD.storage_key THEN
       RAISE EXCEPTION 'media_identity_is_immutable';
    END IF;
    RETURN NEW;
END $fn$;
CREATE TRIGGER v3_media_immutable BEFORE UPDATE OF owner_user_id,storage_key
    ON media_assets FOR EACH ROW EXECUTE FUNCTION v3_immutable_media_identity();

-- The work author's user account and the run owner must be the same.
CREATE OR REPLACE FUNCTION v3_guard_work_run() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM generation_runs r
        JOIN users u ON u.id=r.user_id
        WHERE r.id=NEW.run_id AND u.username=NEW.author_username
    ) THEN
        RAISE EXCEPTION 'work_run_owner_mismatch';
    END IF;
    RETURN NEW;
END $fn$;
CREATE TRIGGER v3_work_run_owner BEFORE INSERT OR UPDATE OF run_id,author_username
    ON works FOR EACH ROW EXECUTE FUNCTION v3_guard_work_run();

-- Each output item and each published work image belong to the same user.
CREATE OR REPLACE FUNCTION v3_guard_generation_item_media() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.media_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM generation_runs r
        JOIN media_assets m ON m.id=NEW.media_id
        WHERE r.id=NEW.run_id AND r.user_id=m.owner_user_id
    ) THEN
        RAISE EXCEPTION 'generation_item_owner_mismatch';
    END IF;
    RETURN NEW;
END $fn$;
CREATE TRIGGER v3_gen_item_owner BEFORE INSERT OR UPDATE OF media_id,run_id
    ON generation_items FOR EACH ROW EXECUTE FUNCTION v3_guard_generation_item_media();

CREATE OR REPLACE FUNCTION v3_guard_work_media_owner() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM works w JOIN users u ON u.username=w.author_username
        JOIN media_assets m ON m.id=NEW.media_id
        WHERE w.id=NEW.work_id AND m.owner_user_id=u.id
    ) THEN
        RAISE EXCEPTION 'work_media_owner_mismatch';
    END IF;
    RETURN NEW;
END $fn$;
CREATE TRIGGER v3_work_media_owner BEFORE INSERT OR UPDATE OF media_id,work_id
    ON work_media FOR EACH ROW EXECUTE FUNCTION v3_guard_work_media_owner();

-- Cover selection never changes output order; it points to existing media.
CREATE OR REPLACE FUNCTION v3_guard_work_cover() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.cover_media_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM work_media
        WHERE work_id=NEW.id AND media_id=NEW.cover_media_id
    ) THEN
        RAISE EXCEPTION 'cover_must_be_linked_media';
    END IF;
    RETURN NEW;
END $fn$;
CREATE TRIGGER v3_work_cover BEFORE INSERT OR UPDATE OF cover_media_id
    ON works FOR EACH ROW EXECUTE FUNCTION v3_guard_work_cover();

CREATE OR REPLACE FUNCTION v3_guard_cover_media_delete() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF EXISTS (
        SELECT 1 FROM works
        WHERE id=OLD.work_id AND cover_media_id=OLD.media_id
    ) THEN
        RAISE EXCEPTION 'cannot_remove_cover_media';
    END IF;
    RETURN OLD;
END $fn$;
CREATE TRIGGER v3_cover_media_delete BEFORE DELETE ON work_media
    FOR EACH ROW EXECUTE FUNCTION v3_guard_cover_media_delete();

-- The list JSON is ONLY a derived feed cache; prevent stale/mismatched media.
CREATE OR REPLACE FUNCTION v3_guard_work_images_cache() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE canonical jsonb;
BEGIN
    IF NEW.run_id IS NULL THEN RETURN NEW; END IF;
    SELECT COALESCE(jsonb_agg(m.storage_key ORDER BY wm.position), '[]'::jsonb)
    INTO canonical
    FROM work_media wm JOIN media_assets m ON m.id=wm.media_id
    WHERE wm.work_id=NEW.id;
    IF COALESCE(NEW.images_json,'[]')::jsonb IS DISTINCT FROM canonical THEN
        RAISE EXCEPTION 'generated_work_media_cache_mismatch';
    END IF;
    RETURN NEW;
END $fn$;
CREATE TRIGGER v3_work_images_cache BEFORE UPDATE OF images_json
    ON works FOR EACH ROW EXECUTE FUNCTION v3_guard_work_images_cache();
"""
