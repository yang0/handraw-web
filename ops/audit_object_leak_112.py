#!/usr/bin/env python3
"""Issue #112: read-only, explicit-host live media access boundary probe.

No discovery, mutation, upload, asset content download, automatic redirects, or
production GO decision. Operator supplies URLs and test credentials privately.
This is a security observation, NOT proof that the manifest's resource ownership
claims are genuine. Never commit the manifest or request credentials.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

CASE_EXPECTATIONS = {
    "public_work": "allow",
    "private_owner": "allow",
    "private_anonymous": "deny",
    "private_cross_user": "deny",
    "hidden_work": "deny",
    "private_bucket_object": "deny",
    "expired_signed_url": "deny",
    "bucket_listing": "deny",
}
AUTHORIZED_CASES = {"private_owner", "private_cross_user"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_url(raw: object, allowed_hosts: set[str], allow_http_test: bool) -> str:
    if not isinstance(raw, str) or len(raw) > 8192:
        raise ValueError("invalid case URL")
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise ValueError("invalid case URL") from None
    if (not host or parts.username is not None or parts.password is not None or
            parts.fragment or parts.scheme not in ("https", "http")):
        raise ValueError("unsafe case URL")
    origin = host + ((":" + str(port)) if port else "")
    if origin not in allowed_hosts:
        raise ValueError("case origin is not on explicit allowlist")
    if parts.scheme == "http":
        if not allow_http_test or host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("HTTP is restricted to explicit loopback testing")
    elif host in ("localhost", "127.0.0.1", "::1") and not allow_http_test:
        raise ValueError("loopback URLs require explicit testing flag")
    return raw


def validate_manifest(manifest: object, *, allowed_hosts: set[str],
                      allow_http_test: bool = False, now: dt.datetime | None = None) -> list[dict]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("unsupported manifest schema")
    if manifest.get("environment") not in ("staging", "preproduction", "production"):
        raise ValueError("explicit environment required")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", str(manifest.get("release_sha", ""))):
        raise ValueError("40-character release SHA required")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != len(CASE_EXPECTATIONS):
        raise ValueError("all eight required cases must be provided exactly once")
    seen: set[str] = set()
    verified = []
    now = now or dt.datetime.now(dt.timezone.utc)
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("invalid case record")
        case_id = case.get("id")
        if case_id not in CASE_EXPECTATIONS or case_id in seen:
            raise ValueError("unknown or duplicated required case")
        seen.add(case_id)
        if case.get("expect") != CASE_EXPECTATIONS[case_id]:
            raise ValueError("case expectation cannot be weakened")
        url = _safe_url(case.get("url"), allowed_hosts, allow_http_test)
        auth_env = case.get("auth_env")
        if case_id in AUTHORIZED_CASES:
            if not isinstance(auth_env, str) or not re.fullmatch(r"HANDRAW_AUDIT_[A-Z0-9_]+", auth_env):
                raise ValueError("authenticated test needs an audit-specific env variable")
            if case.get("auth_kind") not in ("bearer", "cookie"):
                raise ValueError("authenticated test needs bearer/cookie mode")
        elif auth_env is not None or case.get("auth_kind") is not None:
            raise ValueError("anonymous denial case may not include credentials")
        if case_id == "expired_signed_url":
            try:
                expiration = dt.datetime.fromisoformat(case["expired_at_utc"].replace("Z", "+00:00"))
                if expiration.tzinfo is None or expiration >= now:
                    raise ValueError()
            except (KeyError, AttributeError, TypeError, ValueError):
                raise ValueError("signed URL must have an already-past UTC expiry") from None
        verified.append({"id": case_id, "url": url, "expect": case["expect"],
                         "auth_env": auth_env, "auth_kind": case.get("auth_kind")})
    return verified


def probe(case: dict, *, timeout: float = 8.0) -> dict:
    headers = {"Range": "bytes=0-0", "Cache-Control": "no-cache", "Accept": "image/*,*/*;q=0.1"}
    env_name = case["auth_env"]
    if env_name:
        credential = os.environ.get(env_name, "")
        if not credential or any(c in credential for c in "\r\n"):
            return {"id": case["id"], "expect": case["expect"], "status": None,
                    "passed": False, "error": "missing_or_invalid_audit_credential"}
        if case["auth_kind"] == "bearer":
            headers["Authorization"] = "Bearer " + credential
        else:
            headers["Cookie"] = credential
    request = urllib.request.Request(case["url"], headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    status = None
    content_type = ""
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "").lower()
            # Deliberately do NOT read or save any private/public media bytes.
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {"id": case["id"], "expect": case["expect"], "status": None,
                "passed": False, "error": "network_or_tls_failure"}
    if case["expect"] == "allow":
        passed = status in (200, 206) and content_type.startswith("image/")
    else:
        # 302/500/429 and login pages are NOT proof that media access was denied.
        passed = status in (401, 403, 404)
    return {"id": case["id"], "expect": case["expect"],
            "status": status, "passed": bool(passed)}


def audit(manifest: dict, *, allowed_hosts: set[str], allow_http_test: bool = False,
          timeout: float = 8.0) -> dict:
    cases = validate_manifest(manifest, allowed_hosts=allowed_hosts, allow_http_test=allow_http_test)
    results = [probe(case, timeout=timeout) for case in cases]
    return {"issue": 112, "environment": manifest["environment"],
            "releaseSha": manifest["release_sha"], "checks": results,
            "allProbesPassed": all(item["passed"] for item in results),
            "decision": "NO-GO", "productionVerified": False,
            "requiresHumanOwnershipAndGatewayReview": True,
            "note": "Read-only observations only; cannot grant release approval"}


def _write_new_report(path: Path, result: dict) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allowed-host", action="append", required=True)
    parser.add_argument("--allow-http-test", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args(argv)
    if not 0.5 <= args.timeout <= 30:
        parser.error("timeout must be between 0.5 and 30 seconds")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = audit(manifest, allowed_hosts=set(args.allowed_host),
                       allow_http_test=args.allow_http_test, timeout=args.timeout)
        _write_new_report(args.report, result)
        print(json.dumps({"allProbesPassed": result["allProbesPassed"],
                          "checks": len(result["checks"]), "decision": result["decision"]}))
        return 0 if result["allProbesPassed"] else 1
    except (ValueError, OSError, json.JSONDecodeError):
        print("audit refused: invalid manifest, target or report location", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
