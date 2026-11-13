"""Read-only economy preflight by default; additive migration with an explicit ACK."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path


def upgrade(dsn, *, apply=False):
    import psycopg

    if not dsn:
        raise RuntimeError("Set HANDRAW_ECONOMY_UPGRADE_URL explicitly")
    if apply and os.environ.get("HANDRAW_ALLOW_ECONOMY_UPGRADE") != "YES":
        raise RuntimeError("Set HANDRAW_ALLOW_ECONOMY_UPGRADE=YES to apply")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='60s'")
        real_orders = conn.execute(
            "SELECT count(*) FROM payment_orders WHERE test_mode=0 AND status NOT IN ('failed','expired','cancelled')"
        ).fetchone()[0]
        installed = bool(
            conn.execute("SELECT 1 FROM schema_migrations WHERE version=119").fetchone()
        )
        guards_installed = bool(
            conn.execute("SELECT 1 FROM schema_migrations WHERE version=120").fetchone()
        )
        users, points = conn.execute(
            "SELECT count(*),COALESCE(sum(balance),0) FROM wallets"
        ).fetchone()
        report = {
            "ok": not real_orders or installed,
            "applied": False,
            "installed": installed,
            "contributionGuardsInstalled": guards_installed,
            "requiredVersion": 120,
            "realPaymentOrders": real_orders,
            "pointWallets": users,
            "retainedPoints": points,
            "cashConversion": False,
        }
        if real_orders and not installed:
            raise RuntimeError(
                "Real payment history exists; reconcile purchases before cutover"
            )
        if apply:
            for filename in (
                "postgres_119_economy.sql",
                "postgres_120_contribution_guards.sql",
            ):
                conn.execute(
                    (
                        Path(__file__).resolve().parents[1] / "backend" / filename
                    ).read_text(encoding="utf-8")
                )
            report["applied"] = True
            report["installed"] = True
            report["contributionGuardsInstalled"] = True
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = upgrade(
            os.environ.get("HANDRAW_ECONOMY_UPGRADE_URL", ""), apply=args.apply
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
