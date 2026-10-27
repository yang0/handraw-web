"""Password hashing (PBKDF2-SHA256 + Discourse migration compatibility) and session helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from http.cookies import SimpleCookie


PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt_hex = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_hex.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_hex}${dk.hex()}"


def verify_password(password: str, stored_hash: str, password_algo: str = "pbkdf2_sha256", discourse_salt: str = "") -> bool:
    if not stored_hash or not password:
        return False

    # Native Handraw Web 2.0 format: pbkdf2_sha256$iterations$salt$hex
    if stored_hash.startswith("pbkdf2_sha256$"):
        parts = stored_hash.split("$")
        if len(parts) != 4:
            return False
        try:
            iterations = int(parts[1])
            salt_str = parts[2]
            expected_hex = parts[3]
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_str.encode("utf-8"), iterations)
            return hmac.compare_digest(dk.hex(), expected_hex)
        except Exception:
            return False

    # Imported Discourse PBKDF2-SHA256 format (64000 iterations, 32-byte key hex, separate salt)
    if password_algo == "discourse_pbkdf2" and discourse_salt:
        for iters in (64000, 600000):
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), discourse_salt.encode("utf-8"), iters, dklen=32)
            if hmac.compare_digest(dk.hex(), stored_hash.strip().lower()):
                return True
        return False

    return False


def generate_session_token() -> str:
    return "hws_" + secrets.token_urlsafe(32)


def generate_api_key() -> str:
    return "hwk_" + secrets.token_urlsafe(28)


def parse_cookie_header(cookie_header: str | None) -> dict[str, str]:
    if not cookie_header:
        return {}
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        result: dict[str, str] = {}
        for part in cookie_header.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                result[k.strip()] = v.strip()
        return result
    return {k: morsel.value for k, morsel in jar.items()}


def build_session_cookie(name: str, value: str, host: str, max_age: int, secure: bool = False) -> str:
    parts = [f"{name}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
    clean_host = (host or "").split(":")[0].strip().lower()
    if clean_host == "handraw-style.com" or clean_host.endswith(".handraw-style.com"):
        parts.append("Domain=.handraw-style.com")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
