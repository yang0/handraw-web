"""Phase21 #132: opt-in real disposable R2/S3 and Redis tenant/lock probes.

Default: NO NETWORK. Live probes require preproduction-only credentials and
HANDRAW_PHASE21_INFRA_D_PROBE=YES, run against explicitly dedicated resources.
Use fresh random keys, never production customer objects or Redis keys.
No real evidence is self-attesting: output decision always NO-GO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError

ENV_ALLOW="HANDRAW_PHASE21_INFRA_D_PROBE"
LABEL=re.compile(r"^preprod-[a-z0-9][a-z0-9-]{3,55}$")
BUCKET=re.compile(r"^handraw-phase21-qa-[a-z0-9-]{5,55}$")
PREFIX=re.compile(r"^phase21-qa:[a-z0-9-]{8,80}$")


def preflight(*,environment,endpoint=None,bucket=None,prefix=None,run=False):
    if not isinstance(environment,str) or not LABEL.fullmatch(environment):
        raise ValueError("preproduction-only environment identity required")
    if run and os.environ.get(ENV_ALLOW)!="YES":
        raise ValueError("explicit phase21 live infra approval required")
    if endpoint is not None:
        u=urlsplit(endpoint)
        if (u.scheme!="https" or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path not in ("","/")
                or u.hostname.lower() in ("localhost","127.0.0.1","0.0.0.0")
                or not BUCKET.fullmatch(bucket or "")):
            raise ValueError("real TLS S3 endpoint and disposable QA bucket required")
    if prefix is not None and not PREFIX.fullmatch(prefix):
        raise ValueError("dedicated randomized Redis namespace required")
    return {"environment":environment,"networkRequested":bool(run),
            "dedicatedBucketOrNamespaceRequired":True,
            "externalProviderActuallyContacted":False,"decision":"NO-GO"}


def _refusal(exc):
    """Do not accept 5xx/timeouts as authorization denies."""
    code=str(getattr(exc,"response",{}).get("Error",{}).get("Code",""))
    status=getattr(exc,"response",{}).get("ResponseMetadata",{}).get("HTTPStatusCode")
    return code in ("AccessDenied","403","Forbidden") or status==403


def _deny(call):
    try:
        response=call()
        body=response.get("Body") if isinstance(response,dict) else None
        if body:
            body.close()
        return False
    except Exception as exc:
        return _refusal(exc)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def _http_response_code(url,*,expected_hostname):
    parts=urlsplit(url)
    if parts.scheme!="https" or parts.hostname!=expected_hostname:
        raise ValueError("signed URL points outside allowed TLS endpoint")
    opener=build_opener(_NoRedirect)
    try:
        with opener.open(Request(url,method="GET"),timeout=8) as response:
            response.read(64)
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except (URLError,TimeoutError):
        raise ValueError("network failure is not proof of expired URL") from None


def probe_s3(client_a,client_b,anonymous_client,*,bucket,prefix,
             endpoint_host,signed_url_checker=None,sleep=time.sleep):
    """Actual scoped S3 protocol requests; no customer data and no ACL creation."""
    if not BUCKET.fullmatch(bucket) or not PREFIX.fullmatch(prefix):
        raise ValueError("S3 QA storage scope missing")
    mark=secrets.token_hex(12)
    key_a=f"{prefix}/tenant-a/{mark}"
    key_b=f"{prefix}/tenant-b/{mark}"
    content_a=secrets.token_bytes(64)
    content_b=secrets.token_bytes(64)
    started_a=started_b=False
    results={}
    try:
        client_a.put_object(Bucket=bucket,Key=key_a,Body=content_a,
                            CacheControl="private, no-store")
        started_a=True
        client_b.put_object(Bucket=bucket,Key=key_b,Body=content_b,
                            CacheControl="private, no-store")
        started_b=True
        for client,key,value in ((client_a,key_a,content_a),(client_b,key_b,content_b)):
            o=client.get_object(Bucket=bucket,Key=key)
            got=o["Body"].read(65)
            o["Body"].close()
            if got!=value:
                raise ValueError("authorized S3 read does not match temporary bytes")
        results["ownBytesMatched"]=True
        results["crossTenantReadDeniedBothDirections"]=(
            _deny(lambda:client_a.get_object(Bucket=bucket,Key=key_b))
            and _deny(lambda:client_b.get_object(Bucket=bucket,Key=key_a)))
        results["crossTenantWriteDeniedBothDirections"]=(
            _deny(lambda:client_a.put_object(Bucket=bucket,Key=key_b,
                                              Body=b"unauthorized"))
            and _deny(lambda:client_b.put_object(Bucket=bucket,Key=key_a,
                                              Body=b"unauthorized")))
        results["anonymousDenied"]=(
            _deny(lambda:anonymous_client.get_object(Bucket=bucket,Key=key_a))
            and _deny(lambda:anonymous_client.get_object(Bucket=bucket,Key=key_b)))
        results["expiredSignedUrlDenied"]=False
        if signed_url_checker is not None:
            # A 1-second URL must first work, then be explicitly rejected
            # after expiry. No redirects and no full token in error/report.
            url=client_a.generate_presigned_url("get_object",
                Params={"Bucket":bucket,"Key":key_a},ExpiresIn=1)
            status=signed_url_checker(url,expected_hostname=endpoint_host)
            if status!=200:
                raise ValueError("presigned own object inaccessible before expiry")
            sleep(3)
            expired=signed_url_checker(url,expected_hostname=endpoint_host)
            results["expiredSignedUrlDenied"]=expired in (401,403)
        # CDN tombstone and restored-media hashes require a *separate*
        # authorized HTTP app/media test. Do NOT pretend S3 proves either.
        if not all((results["crossTenantReadDeniedBothDirections"],
                    results["crossTenantWriteDeniedBothDirections"],
                    results["anonymousDenied"])):
            raise ValueError("real cross-tenant bucket policy allowed access")
        return {"phase":21,"scope":"r2-s3-real-disposable",
                "observed":results,
                "cdnOldUrlInvalidated":False,"revokedSignedUrlDenied":False,
                "restoredMediaBytesMatched":False,
                "realProviderSourceIndependentlyAudited":False,
                "productionAuthorized":False,"decision":"NO-GO"}
    finally:
        # Only remove our randomly generated two own-prefix objects. A
        # cross-tenant write success is a FAIL, not an excuse to remove it
        # with unrelated credentials. The owner may safely clean its key.
        if started_a:
            try: client_a.delete_object(Bucket=bucket,Key=key_a)
            except Exception: pass
        if started_b:
            try: client_b.delete_object(Bucket=bucket,Key=key_b)
            except Exception: pass


def _acl_denied(call):
    try:
        call()
        return False
    except Exception as exc:
        # Redis uses NoPermissionError when ACL denies a command/key. Unknown
        # errors and transport outages must NEVER be reported as isolation.
        return type(exc).__name__=="NoPermissionError"


def probe_redis(coord_a,coord_b,tenant_a,tenant_b,*,prefix):
    if not PREFIX.fullmatch(prefix):
        raise ValueError("dedicated Redis namespace required")
    token=secrets.token_hex(12)
    lock=f"{prefix}:locks:{token}"
    key_a=f"{prefix}:tenant-a:{token}"
    key_b=f"{prefix}:tenant-b:{token}"
    tag=secrets.token_bytes(20)
    acquired=False
    own_a=own_b=False
    try:
        for client in (coord_a,coord_b,tenant_a,tenant_b):
            if client.ping() is not True:
                raise ValueError("Redis endpoint not reachable")
        if coord_a.set(lock,tag,nx=True,ex=60) is not True:
            raise ValueError("Redis lock unexpectedly held")
        acquired=True
        shared=(coord_b.get(lock)==tag and not coord_b.set(lock,b"conflict",nx=True,ex=60))
        tenant_a.set(key_a,b"a",ex=60)
        own_a=True
        tenant_b.set(key_b,b"b",ex=60)
        own_b=True
        isolated=(_acl_denied(lambda:tenant_a.get(key_b))
                  and _acl_denied(lambda:tenant_b.get(key_a))
                  and _acl_denied(lambda:tenant_a.set(key_b,b"x",ex=60))
                  and _acl_denied(lambda:tenant_b.set(key_a,b"x",ex=60)))
        own=(tenant_a.get(key_a)==b"a" and tenant_b.get(key_b)==b"b")
        if not (shared and isolated and own):
            raise ValueError("Redis cross-instance atomic lock or tenant ACL isolation failed")
        return {"phase":21,"scope":"redis-real-disposable",
                "crossClientAtomicNxObserved":True,
                "redisTenantAclDeniedBothDirections":True,
                "twoPhysicalWebInstancesIndependentlyProven":False,
                "automaticFailoverVerified":False,
                "billingOrOwnerSecretsEmitted":False,
                "productionAuthorized":False,"decision":"NO-GO"}
    finally:
        # Compare-and-delete using Lua to avoid deleting a lock subsequently
        # acquired by another worker after our own TTL expires.
        if acquired:
            try: coord_a.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then "
                "return redis.call('DEL',KEYS[1]) else return 0 end",
                1,lock,tag)
            except Exception: pass
        if own_a:
            try: tenant_a.delete(key_a)
            except Exception: pass
        if own_b:
            try: tenant_b.delete(key_b)
            except Exception: pass


def _private_report(path,report):
    p=Path(path)
    if p.is_symlink() or p.exists():
        raise ValueError("cannot overwrite signed D report")
    p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as file:
        json.dump(report,file,ensure_ascii=False,indent=2,sort_keys=True)
        file.write("\n")


def _s3_from_env(endpoint,region):
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    def make(label):
        kid=os.environ.get(f"HANDRAW_PHASE21_S3_{label}_KEY_ID","")
        secret=os.environ.get(f"HANDRAW_PHASE21_S3_{label}_SECRET","")
        if not kid or not secret:
            raise ValueError("separate scoped tenant S3 credentials required")
        return boto3.client("s3",aws_access_key_id=kid,
                aws_secret_access_key=secret,endpoint_url=endpoint,
                region_name=region,
                config=Config(signature_version="s3v4",
                    connect_timeout=5,read_timeout=8,
                    retries={"max_attempts":1}))
    return (make("A"),make("B"),boto3.client(
        "s3",endpoint_url=endpoint,region_name=region,
        aws_access_key_id="",aws_secret_access_key="",
        config=Config(signature_version=UNSIGNED,
            connect_timeout=5,read_timeout=8,
            retries={"max_attempts":1})))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode",choices=["plan","s3","redis"],required=True)
    ap.add_argument("--environment",required=True)
    ap.add_argument("--endpoint",default=None)
    ap.add_argument("--bucket",default=None)
    ap.add_argument("--region",default="auto")
    ap.add_argument("--prefix",default=None)
    ap.add_argument("--test-presigned-expiry",action="store_true")
    ap.add_argument("--report",required=True)
    args=ap.parse_args(argv)
    try:
        if args.mode=="s3":
            plan=preflight(environment=args.environment,endpoint=args.endpoint,
                 bucket=args.bucket,prefix=args.prefix,run=True)
            a,b,anon=_s3_from_env(args.endpoint,args.region)
            result=probe_s3(a,b,anon,bucket=args.bucket,prefix=args.prefix,
                endpoint_host=urlsplit(args.endpoint).hostname,
                signed_url_checker=_http_response_code if args.test_presigned_expiry else None)
        elif args.mode=="redis":
            plan=preflight(environment=args.environment,prefix=args.prefix,run=True)
            import redis
            names=["COORD_A","COORD_B","TENANT_A","TENANT_B"]
            env=[os.environ.get("HANDRAW_PHASE21_REDIS_"+name+"_URL","")
                 for name in names]
            if not all(env) or len(set(env))!=4:
                raise ValueError("four independent Redis client credentials required")
            clients=[redis.Redis.from_url(s,decode_responses=False,
                      socket_timeout=5,socket_connect_timeout=5) for s in env]
            result=probe_redis(*clients,prefix=args.prefix)
        else:
            result=preflight(environment=args.environment,endpoint=args.endpoint,
                 bucket=args.bucket,prefix=args.prefix,run=False)
        _private_report(args.report,result)
        print("PHASE21 INFRA "+json.dumps({"mode":args.mode,
            "decision":"NO-GO","secretsOrObjectKeysEmitted":False}))
        return 0
    except Exception:
        print("Phase21 private infrastructure probe BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
