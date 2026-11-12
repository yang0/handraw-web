"""Run maintenance logic inside backend test fixtures without a CLI backup."""

from ops import converge_asset_comments, converge_work_comments, ensure_resource_topics


def migrate_asset_comments(db):
    with db.transaction() as conn:
        pending, unmapped, work_comments, _ = converge_asset_comments.plan(conn)
        _, failures = converge_asset_comments.apply(conn, pending, unmapped, work_comments)
    return int(bool(failures))


def migrate_work_comments(db):
    with db.transaction() as conn:
        _, failures = converge_work_comments.apply(conn, converge_work_comments.plan(conn))
    return int(bool(failures))


def fill_resource_topics(db, manifest=None):
    with db.transaction() as conn:
        _, ids = ensure_resource_topics.apply(conn, *ensure_resource_topics.plan(conn))
    if manifest is not None:
        ensure_resource_topics.write_manifest(manifest, ids)
    return 0
