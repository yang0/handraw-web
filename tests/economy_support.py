"""Explicit, isolated billing setup for tests whose subject is another subsystem.

These adapters request real quotes and retain production authorization/settlement.
Tests of billing itself import backend services directly and specify their own state.
"""

from copy import deepcopy


def configure(db):
    from backend.config import resolve_gateway_model

    if not getattr(db, "_test_economy_ready", False):
        db.get_conn().execute(
            "UPDATE generation_specs SET verified=true,price_cents=20,model=? WHERE id='standard-1k'",
            (resolve_gateway_model(),),
        )
        db._test_economy_ready = True


def quoted_body(db, user, body):
    from backend.economy import create_quote
    from backend.studio_execution import apply_source_input

    configure(db)
    result = deepcopy(body)
    if (
        not user
        or result.get("canvasId")
        or result.get("quoteId")
        or result.get("confirmCost") is False
    ):
        return result
    resolved = deepcopy(result)
    apply_source_input(db, user, resolved)
    if resolved.get("recipeId"):
        row = (
            db.get_conn()
            .execute(
                "SELECT ratio FROM studio_recipes WHERE id=? AND user_id=?",
                (resolved["recipeId"], user["id"]),
            )
            .fetchone()
        )
        if row:
            resolved["ratio"] = row["ratio"] or "3:4"
    quote = create_quote(db, user, [resolved])
    result.update(quoteId=quote["quoteId"], quoteIndex=0)
    return result


def prepare_cloud_generation(db, user, body, **kwargs):
    from backend.services import prepare_cloud_generation as actual

    return actual(db, user, quoted_body(db, user, body), **kwargs)


def preview_canvas(db, user, cid, **kwargs):
    from backend.studio_canvases import preview_canvas as actual

    configure(db)
    return actual(db, user, cid, **kwargs)


def submit_canvas(db, user, cid, body):
    from backend.studio_canvases import submit_canvas as actual
    from backend.economy import create_quote

    configure(db)
    previous = (
        db.get_conn()
        .execute(
            "SELECT 1 FROM generation_runs WHERE user_id=? AND external_run_id=?",
            (user["id"], body.get("requestId")),
        )
        .fetchone()
    )
    if previous or body.get("quoteId"):
        return actual(db, user, cid, body)
    preview = preview_canvas(db, user, cid)
    selected = body.get("ordinals", range(preview["count"]))
    if not isinstance(selected, (list, range)) or any(
        type(x) is not int or x < 0 or x >= preview["count"] for x in selected
    ):
        return actual(db, user, cid, body)
    quote = create_quote(
        db,
        user,
        [item["spec"] for item in preview["items"] if item["ordinal"] in selected],
    )
    return actual(
        db,
        user,
        cid,
        {**body, "quoteId": quote["quoteId"], "maxAmountCents": quote["totalCents"]},
    )


def http_body(db, headers, body):
    from backend.services import authenticate_request
    from backend.services import ServiceError

    try:
        return quoted_body(db, authenticate_request(db, headers), body)
    except ServiceError:
        # Authorization and malformed-source tests must reach the real HTTP
        # boundary and preserve its status instead of failing in the harness.
        return body
