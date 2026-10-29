"""Rotate starter account credentials.

The first version of ``seed_starter_library.py`` shipped a shared constant
password, so every starter account was publicly signable-in and each had an
Api-Key minted for it.  This rotates both: the password becomes random and the
Api-Key is reissued, invalidating anything that leaked.

Usage:
    python -X utf8 ops/rotate_starter_credentials.py --db .local/handraw_v2.db
    python -X utf8 ops/rotate_starter_credentials.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STARTER_USERNAMES = ("linnan", "chenmo", "yuzi_art", "helan", "tangyuan")


def plan(db) -> list[dict]:
    conn = db.get_conn()
    out = []
    for username in STARTER_USERNAMES:
        row = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            out.append({"username": username})
    return out


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
    parser = argparse.ArgumentParser(description="Rotate starter account passwords and API keys.")
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    from backend.db import Database

    db = Database(Path(args.db).resolve())
    db.migrate()
    try:
        todo = plan(db)
        print(f"待轮换账号：{len(todo)} 个（{', '.join(i['username'] for i in todo)}）")
        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0
        rotated = apply(db, todo)
        out = Path(args.db).resolve().parent / f"starter_credentials.{Path(args.db).stem}.json"
        out.write_text(json.dumps(rotated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已轮换 {len(rotated)} 个账号的密码与 Api-Key，凭据写入 {out}")
        print("请确认该文件位于 .gitignore 覆盖范围内，并在首次登录后再次修改密码。")
        return 0
    finally:
        db.close_thread_conn()
        db.get_conn().close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
