"""Studio2 ResourceRef server authorization for private project drafts (#105).

Browser Picker and AI suggestions never grant resource/media access. Reuse the
existing resource_registry; do not expose hidden prompts or definitions.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from .config import CONTENT_DIR

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,99}$")
_KINDS = {"style": "style", "secondaryStyle": "style", "layout": "layout",
          "colors": "color", "tones": "tone"}
_LEGACY = {"style": "style1", "secondaryStyle": "style2", "layout": "layout",
           "colors": "colors", "tones": "tones"}
_SOURCES = {"official", "community", "override", "private", "pending", "exclusive"}


def _bad(message: str, code: str, status: int = 400) -> None:
    from .services import ServiceError
    raise ServiceError(message, code=code, status=status)


@lru_cache(maxsize=1)
def _catalog() -> tuple[int, dict[str, str]]:
    # Public resource identities only; never return secret recipe content.
    with (CONTENT_DIR / "catalog.json").open(encoding="utf-8") as f:
        catalog = json.load(f)
    with (CONTENT_DIR / "studio-options.json").open(encoding="utf-8") as f:
        opts = json.load(f)
    ids = {str(v["id"]).upper(): "color" for v in catalog.get("resources", [])
           if v.get("kind") == "color"}
    ids.update({str(v["id"]).upper(): "tone" for v in opts.get("tones", [])})
    return int(catalog.get("version", 1)), ids


def check_resource_ref(ref: Any, kind: str, tx: Any, viewer: dict[str, Any]) -> None:
    if not isinstance(ref, dict) or not {"id", "type"} <= set(ref) or \
            set(ref) - {"id", "type", "source", "version"}:
        _bad("资源引用必须使用 id/type/source/version", "invalid_resource_ref")
    ident = ref.get("id")
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        _bad("资源编号无效", "invalid_resource_ref")
    if ref.get("type") != kind:
        _bad("资源类别错误", "resource_type_mismatch")
    source, version = ref.get("source"), ref.get("version")
    if source is not None and (not isinstance(source, str) or source not in _SOURCES):
        _bad("资源来源无效", "invalid_resource_source")
    if version is not None and (type(version) not in (int, str)
            or (type(version) is int and version < 1)
            or (type(version) is str and (not version or len(version) > 64))):
        _bad("资源版本无效", "invalid_resource_version")

    if kind in ("color", "tone"):
        catalog_version, ids = _catalog()
        if ids.get(ident.upper()) != kind:
            _bad("资源编号不存在", "resource_not_found")
        canonical_source, current_version = "official", catalog_version
    else:
        from . import resource_registry
        item = resource_registry.resolve(tx, ident, viewer=viewer, purpose="generate")
        if not item or item.get("kind") != kind:
            _bad("画风或图型不存在或已失效", "resource_not_found")
        if not item.get("canUse") or not item.get("access", {}).get("canUse"):
            _bad("画风或图型尚未获得使用授权", "resource_forbidden", 403)
        canonical_source = item.get("source")
        row = item.get("_raw_row") or {}
        current_version = row.get("revision") or row.get("version")
        if current_version is None:
            current_version = _catalog()[0] if canonical_source == "official" and not row else "current"
    if source is not None and source != canonical_source:
        _bad("资源来源已更新，请重新选择", "resource_source_mismatch")
    if version is not None and str(version) not in ("current", str(current_version)):
        _bad("资源定义版本已更新，请重新选择", "resource_version_conflict", 409)


def check_media_owner(media_id: Any, tx: Any, user_id: int) -> None:
    if not isinstance(media_id, str) or not 1 <= len(media_id) <= 128:
        _bad("媒体编号无效", "invalid_project_media")
    if tx.execute("SELECT 1 FROM media_assets WHERE id=? AND owner_user_id=?",
                  (media_id, user_id)).fetchone():
        return
    if tx.execute("""SELECT 1 FROM user_uploads WHERE asset_uid=? AND user_id=?
                     AND deleted_at IS NULL""", (media_id, user_id)).fetchone():
        return
    _bad("图片已删除、不存在或无权访问", "project_media_forbidden", 403)


def _check_spec(spec: Any, tx: Any, viewer: dict[str, Any]) -> None:
    if not isinstance(spec, dict):
        _bad("CreationSpec 必须为对象", "invalid_creation_spec")
    for field, kind in _KINDS.items():
        ref = spec.get(field)
        if ref is None:
            continue
        if field in ("colors", "tones"):
            if not isinstance(ref, list) or len(ref) > 20:
                _bad("多选资源列表无效", "invalid_creation_spec")
            for x in ref:
                check_resource_ref(x, kind, tx, viewer)
        else:
            check_resource_ref(ref, kind, tx, viewer)
    if "fusionEnabled" in spec and not isinstance(spec["fusionEnabled"], bool):
        _bad("融合开关必须为布尔值", "invalid_creation_spec")
    if "referenceMedia" in spec:
        _check_media_list(spec["referenceMedia"], tx, viewer)


def _check_media_list(media: Any, tx: Any, viewer: dict[str, Any]) -> None:
    if not isinstance(media, list):
        _bad("参考媒体必须为数组", "invalid_project_media")
    for x in media:
        if not isinstance(x, dict) or x.get("role", "other") not in (
            "character", "scene", "object", "composition", "result", "other"):
            _bad("参考媒体用途无效", "invalid_project_media")
        check_media_owner(x.get("mediaId"), tx, int(viewer["id"]))


def _check_graph(graph: Any, tx: Any, viewer: dict[str, Any]) -> None:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes", []), list):
        _bad("Graph 格式无效", "invalid_project_graph")
    for node in graph.get("nodes", []):
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            continue
        data = node["data"]
        if node.get("type") == "skill_params" and "resourceRefs" in data:
            refs = data["resourceRefs"]
            if not isinstance(refs, dict) or set(refs) - set(_LEGACY):
                _bad("Graph 资源元数据无效", "invalid_resource_ref")
            for field, legacy in _LEGACY.items():
                if field not in refs:
                    continue
                selected = refs[field]
                live = data.get(legacy)
                if field in ("colors", "tones"):
                    if not isinstance(selected, list) or [x.get("id") if isinstance(x, dict) else None
                            for x in selected] != (live if isinstance(live, list) else []):
                        _bad("Graph 资源引用与所选编号不一致", "resource_ref_mismatch")
                    for ref in selected:
                        check_resource_ref(ref, _KINDS[field], tx, viewer)
                elif selected is None:
                    if live:
                        _bad("Graph 资源引用与所选编号不一致", "resource_ref_mismatch")
                else:
                    if not isinstance(selected, dict) or selected.get("id") != live:
                        _bad("Graph 资源引用与所选编号不一致", "resource_ref_mismatch")
                    check_resource_ref(selected, _KINDS[field], tx, viewer)
        if node.get("type") == "loop" and isinstance(data.get("batchRows"), list):
            for row in data["batchRows"]:
                if not isinstance(row, dict) or "layoutRef" not in row:
                    continue
                ref = row["layoutRef"]
                if ref is None and not row.get("layout"):
                    continue
                if not isinstance(ref, dict) or ref.get("id") != row.get("layout"):
                    _bad("分镜图型标记与选择不一致", "resource_ref_mismatch")
                check_resource_ref(ref, "layout", tx, viewer)


def validate_draft_refs(draft: dict[str, Any], tx: Any, viewer: dict[str, Any]) -> None:
    if "creationSpec" in draft:
        _check_spec(draft["creationSpec"], tx, viewer)
    if "graph" in draft:
        _check_graph(draft["graph"], tx, viewer)
    plan = draft.get("plan")
    if isinstance(plan, dict):
        for slot in plan.get("slots", []):
            if isinstance(slot, dict):
                if isinstance(slot.get("overrides"), dict):
                    _check_spec(slot["overrides"], tx, viewer)
                if "referenceMedia" in slot:
                    _check_media_list(slot["referenceMedia"], tx, viewer)
