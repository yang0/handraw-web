"""Private-media retention for normalized authoring and execution references."""


def studio_media_referenced(conn, url):
    return bool(
        conn.execute(
            """SELECT 1 WHERE
          EXISTS(SELECT 1 FROM article_illustrations i JOIN studio_articles a ON a.id=i.article_id
                 LEFT JOIN media_assets m ON m.id=i.selected_media_id
                 WHERE i.deleted_at IS NULL AND a.deleted_at='' AND
                   (m.storage_key=? OR i.spec_json @> jsonb_build_object('refImages',jsonb_build_array(CAST(? AS text)))))
          OR EXISTS(SELECT 1 FROM generation_attempt_media am JOIN media_assets m ON m.id=am.media_id
                    WHERE m.storage_key=?)
          OR EXISTS(SELECT 1 FROM generation_items i WHERE i.spec_json @>
                    jsonb_build_object('refImages',jsonb_build_array(CAST(? AS text))))
          OR EXISTS(SELECT 1 FROM studio_canvases c WHERE c.deleted_at IS NULL AND
                    jsonb_path_exists(c.graph_json,'$.nodes[*] ? (@.parameter == "refImages").values[*][*] ? (@ == $url)',
                                      jsonb_build_object('url',CAST(? AS text))))""",
            (url, url, url, url, url),
        ).fetchone()
    )
