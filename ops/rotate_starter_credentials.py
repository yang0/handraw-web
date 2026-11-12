"""Rotate starter account credentials.

The first version of ``seed_starter_library.py`` shipped a shared constant
password, so every starter account was publicly signable-in and each had an
Api-Key minted for it.  This rotates both: the password becomes random and the
Api-Key is reissued, invalidating anything that leaked.

Usage:
    python -X utf8 ops/rotate_starter_credentials.py
    python -X utf8 ops/rotate_starter_credentials.py --apply
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops.label_starter_accounts import STARTER_USERNAMES
from ops.postgres_maintenance import backup_before_change, configure_transaction, maintenance_database, maintenance_parser
from ops.starter_credentials import write_credentials


def plan(db) -> list[dict]:
    conn = db.get_conn()
    placeholders = ", ".join("?" for _ in STARTER_USERNAMES)
    found = {
        row["username"] for row in conn.execute(
            f"SELECT username FROM users WHERE username IN ({placeholders})",
            STARTER_USERNAMES,
        )
    }
    return [{"username": name} for name in STARTER_USERNAMES if name in found]


def apply(db, todo: list[dict]) -> list[dict]:
    from backend.security import generate_api_key, hash_password

    rotated: list[dict] = []
    with db.transaction() as tx:
        for item in todo:
            password = "hws-rot-" + secrets.token_urlsafe(18)
            new_key = generate_api_key()
            new_hash = hash_password(password)
            tx.execute(
                "UPDATE users SET password_hash = ?, password_algo = 'pbkdf2_sha256', api_key = ? WHERE username = ?",
                (new_hash, new_key, item["username"]),
            )
            # Rotating the password is pointless if the old session cookie keeps
            # working; drop every live session for the account.
            tx.execute(
                "DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = ?)",
                (item["username"],),
            )
            rotated.append({"username": item["username"], "password": password, "apiKey": new_key})
    return rotated


def main(argv: list[str] | None = None) -> int:
    parser = maintenance_parser("Rotate starter account passwords and API keys.")
    args = parser.parse_args(argv)
    with maintenance_database(parser) as (db, dsn), db.transaction() as conn:
        configure_transaction(conn, write=args.apply)
        todo = plan(db)
        print(f"待轮换账号：{len(todo)} 个（{', '.join(i['username'] for i in todo)}）")
        if not args.apply or not todo:
            return 0
        backup = backup_before_change(conn, dsn, args.backup_dir, "starter-rotation-before")
        print(f"已验证备份：{backup}")
        rotated = apply(db, todo)
        out = write_credentials(rotated)
    print(f"已轮换 {len(rotated)} 个账号的密码与 Api-Key，凭据写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
