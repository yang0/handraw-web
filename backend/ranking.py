"""Single source of truth for popularity ordering.

Every list in the product exposes at most three sort keys -- ``newest``,
``popular`` and ``active`` (topics only) -- and each object type has exactly one
popularity formula.  Before this module there were at least nine different
formulas scattered across the backend and the front end, so "hot" meant
something different on every page.

The weights encode intended effort: a fork is a real reuse (highest weight),
favouriting means planning to reuse, and likes/cheers are light acknowledgement.
Time decay is deliberately absent -- a period filter narrows by publication
date, which keeps results explainable and index-friendly.
"""
from __future__ import annotations

from typing import Any

# Works: likes + cheers + 2*favorites + 1*forks.
#
# Forks were weighted 3x because they represent real reuse, but the counter is
# reachable by spending free generation quota, so it is not trustworthy enough
# to dominate the ranking.  Weight 1 keeps the signal without giving a farmable
# metric three times the pull of a like.
# Kept as a SQL expression so an ORDER BY can use the expression index.
WORK_POPULAR_EXPR = "(likes + cheers + 2 * favorites + forks)"


def work_popular_sql(alias: str = "") -> str:
    """Popularity expression for ``works``, optionally qualified by a table alias."""
    if not alias:
        return WORK_POPULAR_EXPR
    prefix = f"{alias}."
    return (
        f"({prefix}likes + {prefix}cheers + 2 * {prefix}favorites + {prefix}forks)"
    )


# Topics: published replies + likes + 2*favorites.  A work's own discussion
# topic reports the work's counters instead of its own, so the two views agree.
def topic_popular_sql(alias: str = "t") -> str:
    replies = (
        f"(SELECT COUNT(*) FROM forum_replies r WHERE r.topic_id = {alias}.id AND r.status = 'published')"
    )
    return f"({replies} + {alias}.likes + 2 * {alias}.favorites)"


TOPIC_REPLY_COUNT_SQL = (
    "(SELECT COUNT(*) FROM forum_replies r WHERE r.topic_id = t.id AND r.status = 'published')"
)
TOPIC_POPULAR_SQL = f"({TOPIC_REPLY_COUNT_SQL} + t.likes + 2 * t.favorites)"

SORT_KEYS = ("newest", "popular", "active")


def work_popular_score(row: Any) -> int:
    """Popularity of a work row (sqlite3.Row or dict)."""
    return (
        int(_get(row, "likes") or 0)
        + int(_get(row, "cheers") or 0)
        + 2 * int(_get(row, "favorites") or 0)
        + int(_get(row, "forks") or 0)
    )


def topic_popular_score(topic: Any) -> int:
    """Popularity of a discussion topic.

    ``replyCount`` is supplied by the serializer.  When the topic is a work's
    primary discussion, ``likes``/``favorites`` already carry the work's values
    (see ``services`` serialization), so the same function serves both cases.
    """
    replies = _get(topic, "replyCount")
    if replies is None:
        replies = len(_get(topic, "replies") or [])
    return int(replies or 0) + int(_get(topic, "likes") or 0) + 2 * int(_get(topic, "favorites") or 0)


def asset_popular_score(row: Any) -> int:
    """Styles and layouts are ranked by how many published works reference them."""
    usage = _get(row, "usageCount")
    if usage is None:
        usage = _get(row, "usage_count")
    return int(usage or 0)


def normalize_sort(value: str | None, *, allow_active: bool = False) -> str:
    """Map a request value onto one of the supported sort keys.

    Legacy values from stored URLs (``favorites``, ``cheers``, ``hot``,
    ``recommended``) collapse onto ``popular`` instead of erroring, so old links
    keep working.
    """
    key = (value or "").strip().lower()
    if key in ("popular", "hot", "recommended", "favorites", "cheers"):
        return "popular"
    if key == "active" and allow_active:
        return "active"
    return "newest"


def sort_works(rows: list[Any], key: str) -> list[Any]:
    """Sort work rows in Python, matching the SQL ordering exactly."""
    if key == "popular":
        return sorted(
            rows,
            key=lambda r: (-work_popular_score(r), -int(_get(r, "published_at_ms") or 0), str(_get(r, "id") or "")),
        )
    return sorted(
        rows,
        key=lambda r: (-int(_get(r, "published_at_ms") or 0), str(_get(r, "id") or "")),
    )


def _get(row: Any, name: str) -> Any:
    try:
        return row[name]
    except (IndexError, KeyError, TypeError):
        return None
