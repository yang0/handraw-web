"""Unified resource resolution layer for Handraw (Phase 3b-13a).

Resolves resources across catalog_assets, static catalog.json, curation_submissions,
and (future) user_resources with consistent ownership, visibility, and generation access rules.
"""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from typing import Any

from .config import CONTENT_DIR
from .runtime_policy import sanitize_media_url
from . import services as S


@lru_cache(maxsize=1)
def static_catalog() -> dict[str, dict[str, Any]]:
    path = CONTENT_DIR / "catalog.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(r["id"]).upper(): r
        for r in data.get("resources", [])
        if r.get("kind") in ("style", "layout")
    }


def resolve(
    conn: sqlite3.Connection,
    code: str,
    *,
    viewer: dict[str, Any] | None = None,
    purpose: str = "view",
) -> dict[str, Any] | None:
    """Resolve a style or layout resource by code across all storage layers.

    Order of lookup:
      1. catalog_assets (published, withdrawn, hidden, paused, etc.)
      2. catalog.json (official static definitions)
      3. curation_submissions (latest revision of pending/changes_requested/withdrawn)
      4. user_resources (private authored read model; Skill CAS is authoritative)

    Returns a dict with resource metadata, viewer access rules, and action permissions.
    """
    clean_code = str(code or "").strip().upper().lstrip("#")
    if not clean_code:
        return None

    if not S.is_demo_mode() and clean_code in S.seed_ids("assets"):
        return None

    viewer_id = viewer.get("id") if isinstance(viewer, dict) else None
    viewer_uname = str(viewer.get("username") or "") if isinstance(viewer, dict) else ""
    viewer_role = str(viewer.get("role") or "") if isinstance(viewer, dict) else ""
    is_logged_in = bool(viewer_id or viewer_uname)
    is_staff = viewer_role in ("admin", "reviewer", "operator")

    item_kind = ""
    source_type = ""
    status = ""
    name = clean_code
    desc = ""
    definition = ""
    secret_blackbox_prompt = ""
    image = ""
    unlock_cost = 0
    author_username = ""
    author_name = ""
    owner_user_id: int | None = None
    examples: list[str] = []
    raw_db_row: dict[str, Any] | None = None

    # 1. catalog_assets
    ca_row = conn.execute(
        "SELECT * FROM catalog_assets WHERE code = ? OR UPPER(code) = ?",
        (clean_code, clean_code),
    ).fetchone()

    if ca_row:
        raw_db_row = dict(ca_row)
        item_kind = ca_row["kind"]
        source_type = ca_row["source_type"]
        status = ca_row["status"]
        name = ca_row["name"]
        desc = ca_row["description"] or ""
        definition = ca_row["definition"] or ""
        secret_blackbox_prompt = ca_row["secret_blackbox_prompt"] or ""
        image = sanitize_media_url(ca_row["image_url"] or "")
        unlock_cost = int(ca_row["unlock_cost"] or 0)
        if source_type == "official":
            author_username = ""
            author_name = "Handraw 官方"
            owner_user_id = None
        else:
            author_username = str(ca_row["author_username"] or "")
            author_name = str(ca_row["author_name"] or author_username or "")
            if author_username:
                u_row = conn.execute(
                    "SELECT id, display_name FROM users WHERE username = ?",
                    (author_username,),
                ).fetchone()
                if u_row:
                    owner_user_id = int(u_row["id"])
                    if not author_name and u_row["display_name"]:
                        author_name = str(u_row["display_name"])
    else:
        # 2. static catalog.json
        cat_item = static_catalog().get(clean_code)
        if cat_item and cat_item.get("kind") in ("style", "layout"):
            item_kind = cat_item.get("kind")
            source_type = "official"
            status = "published"
            name = cat_item.get("name") or clean_code
            desc = cat_item.get("description") or ""
            definition = cat_item.get("definition") or ""
            secret_blackbox_prompt = ""
            image = sanitize_media_url(cat_item.get("image") or cat_item.get("cover") or "")
            unlock_cost = 0
            author_username = ""
            author_name = "官方团队"
            owner_user_id = None
        else:
            # 3. curation_submissions (latest revision)
            sub_row = conn.execute(
                """
                SELECT s.id AS submission_id, s.target_id, s.kind, s.owner_username, s.owner_user_id,
                       s.status, s.current_revision, v.payload_json
                FROM curation_submissions s
                JOIN curation_versions v ON v.submission_id = s.id AND v.revision = s.current_revision
                WHERE (UPPER(s.target_id) = ? OR s.target_id = ?) AND s.kind IN ('style', 'layout')
                ORDER BY s.updated_at DESC LIMIT 1
                """,
                (clean_code, clean_code),
            ).fetchone()

            if sub_row:
                item_kind = sub_row["kind"]
                source_type = "pending"
                status = sub_row["status"]
                author_username = str(sub_row["owner_username"] or "")
                owner_user_id = int(sub_row["owner_user_id"])
                author_name = author_username
                u_row = conn.execute(
                    "SELECT display_name FROM users WHERE id = ?",
                    (owner_user_id,),
                ).fetchone()
                if u_row and u_row["display_name"]:
                    author_name = str(u_row["display_name"])

                try:
                    payload = json.loads(sub_row["payload_json"] or "{}")
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}

                name = payload.get("name") or clean_code
                desc = payload.get("description") or ""
                definition = payload.get("definition") or ""
                secret_blackbox_prompt = ""
                cover = payload.get("cover") or payload.get("image") or ""
                raw_imgs = payload.get("images") or []
                if not cover and raw_imgs:
                    first = raw_imgs[0]
                    cover = first.get("url", "") if isinstance(first, dict) else str(first or "")
                image = sanitize_media_url(cover)
                unlock_cost = int(payload.get("unlock_cost") or payload.get("unlockCost") or 0)
                for img in raw_imgs:
                    u = img.get("url", "") if isinstance(img, dict) else str(img or "")
                    if u:
                        examples.append(sanitize_media_url(u))
            else:
                # 4. user_resources (if table exists)
                table_query = (
                    "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='user_resources'"
                    if getattr(conn, "dialect", "") == "postgresql"
                    else "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_resources'"
                )
                has_ur = conn.execute(table_query).fetchone()
                if has_ur:
                    ur_row = conn.execute(
                        "SELECT * FROM user_resources WHERE (code = ? OR UPPER(code) = ?) AND deleted_at IS NULL",
                        (clean_code, clean_code),
                    ).fetchone()
                    if ur_row:
                        raw_db_row = dict(ur_row)
                        item_kind = ur_row["kind"]
                        source_type = "private"
                        status = "private"
                        owner_user_id = int(ur_row["owner_user_id"])
                        u_row = conn.execute(
                            "SELECT username, display_name FROM users WHERE id = ?",
                            (owner_user_id,),
                        ).fetchone()
                        author_username = str(u_row["username"] if u_row else "")
                        author_name = str((u_row["display_name"] if u_row else "") or author_username)
                        name = ur_row["name"]
                        desc = ur_row["description"] or ""
                        definition = ur_row["definition"] or ""
                        image = sanitize_media_url(ur_row["cover_url"] or "")
                        unlock_cost = 0
                    else:
                        return None
                else:
                    return None

    # Check author identity: compare account ID or login username (not display name)
    is_author = False
    if is_logged_in:
        if owner_user_id is not None and viewer_id is not None and int(viewer_id) == int(owner_user_id):
            is_author = True
        elif author_username and viewer_uname and author_username.lower() == viewer_uname.lower():
            is_author = True

    # 1a-1 Access matrix
    access = {
        "canRead": False,
        "canUse": False,
        "hiddenBy": None,
        "inject": None,
    }

    if status in ("withdrawn", "hidden"):
        if is_author:
            access["canRead"] = True
            access["canUse"] = True
            access["hiddenBy"] = None
            access["inject"] = None
        else:
            access["canRead"] = is_staff
            access["canUse"] = False
            access["hiddenBy"] = "withdrawn"
            access["inject"] = None
    elif source_type == "pending" or status in ("pending", "changes_requested"):
        if unlock_cost <= 0:
            # 免费，未收录（pending / changes_requested）：任何人（包括未登录）可见定义；登录用户可用，未登录不可用
            access["canRead"] = True
            access["canUse"] = bool(is_logged_in)
            access["hiddenBy"] = None
            access["inject"] = None
        else:
            # 付费，未收录：作者与员工可见可用；其他登录用户可用但不可见（服务端注入）；未登录不可见不可用
            if is_author or is_staff:
                access["canRead"] = True
                access["canUse"] = True
                access["hiddenBy"] = None
                access["inject"] = None
            elif is_logged_in:
                access["canRead"] = False
                access["canUse"] = True
                access["hiddenBy"] = "pending"
                access["inject"] = "definition"
            else:
                access["canRead"] = False
                access["canUse"] = False
                access["hiddenBy"] = "pending"
                access["inject"] = None
    elif source_type == "exclusive":
        is_unlocked = False
        if unlock_cost <= 0 or is_author or is_staff:
            is_unlocked = True
        elif is_logged_in and viewer_id is not None:
            ul = conn.execute(
                "SELECT 1 FROM unlocks WHERE user_id = ? AND target_type = 'asset' AND target_id = ? AND status = 'settled'",
                (viewer_id, clean_code),
            ).fetchone()
            is_unlocked = bool(ul)

        if is_unlocked:
            access["canRead"] = False
            access["canUse"] = True
            access["hiddenBy"] = "blackbox"
            access["inject"] = "blackbox"
        else:
            access["canRead"] = False
            access["canUse"] = False
            access["hiddenBy"] = "locked"
            access["inject"] = None
    elif unlock_cost > 0:
        is_unlocked = False
        if is_author or is_staff:
            is_unlocked = True
        elif is_logged_in and viewer_id is not None:
            ul = conn.execute(
                "SELECT 1 FROM unlocks WHERE user_id = ? AND target_type = 'asset' AND target_id = ? AND status = 'settled'",
                (viewer_id, clean_code),
            ).fetchone()
            is_unlocked = bool(ul)

        if is_author or is_staff:
            access["canRead"] = True
            access["canUse"] = True
            access["hiddenBy"] = None
            access["inject"] = None
        elif is_unlocked:
            # 付费，已收录，已解锁买家：不显示定义（hiddenBy="paid"），可在线使用，服务端注入定义
            access["canRead"] = False
            access["canUse"] = True
            access["hiddenBy"] = "paid"
            access["inject"] = "definition"
        else:
            access["canRead"] = False
            access["canUse"] = False
            access["hiddenBy"] = "locked"
            access["inject"] = None
    elif source_type == "private":
        if is_author:
            access["canRead"] = True
            access["canUse"] = True
            access["hiddenBy"] = None
            access["inject"] = None
        else:
            return None
    else:
        # Official or Community free
        access["canRead"] = True
        access["canUse"] = True
        access["hiddenBy"] = None
        access["inject"] = None

    # Determine canCollect, canTip, canStamp
    if status in ("withdrawn", "hidden"):
        can_collect = False
        can_tip = False
        can_stamp = False
    elif source_type == "private":
        can_collect = is_author
        can_tip = False
        can_stamp = False
    elif source_type == "pending" or status in ("pending", "changes_requested"):
        can_collect = is_logged_in
        can_tip = False
        can_stamp = is_logged_in
    else:
        # Published official or community
        can_collect = is_logged_in
        can_stamp = is_logged_in
        if source_type == "community":
            can_tip = is_logged_in and not is_author
        else:
            settings = S.get_site_settings(conn)
            payee = S.get_official_tip_payee(settings)
            if payee and is_logged_in:
                can_tip = str(payee).lower() != viewer_uname.lower() and str(payee) != str(viewer_id)
            else:
                can_tip = False

    # Normalized source value
    if source_type == "exclusive":
        norm_source = "exclusive"
    elif source_type == "official_override":
        norm_source = "override"
    elif source_type == "official":
        norm_source = "official"
    elif source_type == "community":
        norm_source = "community"
    elif source_type == "pending":
        norm_source = "pending"
    elif source_type == "private":
        norm_source = "private"
    else:
        norm_source = source_type

    visible_definition = definition if access["canRead"] else None

    return {
        "code": clean_code,
        "id": clean_code,
        "kind": item_kind,
        "source": norm_source,
        "sourceType": norm_source,
        "source_type": source_type,
        "status": status,
        "owner": {
            "userId": owner_user_id,
            "username": author_username,
            "name": author_name,
        },
        "name": name,
        "description": desc,
        "image": image,
        "image_url": image,
        "cover": image,
        "examples": examples,
        "definition": visible_definition,
        "_raw_definition": definition,
        "secret_blackbox_prompt": secret_blackbox_prompt,
        "unlockCost": unlock_cost,
        "unlock_cost": unlock_cost,
        "author": author_username,
        "author_username": author_username,
        "authorName": author_name,
        "author_name": author_name,
        "canUse": access["canUse"],
        "canCollect": can_collect,
        "canTip": can_tip,
        "canStamp": can_stamp,
        "access": access,
        "_raw_row": raw_db_row,
    }


def to_client_dict(res: dict[str, Any]) -> dict[str, Any]:
    """Convert resolved resource dictionary to public API response format.

    Guarantees no internal fields (such as 'inject', '_raw_definition',
    'secret_blackbox_prompt') are exposed to clients.
    """
    return {
        "code": res["code"],
        "id": res["code"],
        "kind": res["kind"],
        "source": res["source"],
        "sourceType": res["sourceType"],
        "status": res["status"],
        "name": res["name"],
        "description": res.get("description", ""),
        "image": res.get("image", ""),
        "cover": res.get("cover", ""),
        "examples": res.get("examples", []),
        "definition": res["definition"],  # None or str
        "unlockCost": res.get("unlockCost", 0),
        "owner": res.get("owner", {}),
        "author": res.get("author", ""),
        "authorName": res.get("authorName", ""),
        "canUse": res["canUse"],
        "canCollect": res.get("canCollect", False),
        "canTip": res.get("canTip", False),
        "canStamp": res.get("canStamp", False),
        "access": {
            "canRead": res["access"]["canRead"],
            "canUse": res["access"]["canUse"],
            "hiddenBy": res["access"]["hiddenBy"],
        },
    }
