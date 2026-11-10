"""#132 Phase21 real-infra probe contracts: no CI network or production credentials."""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.studio_phase21_infra_probe_132 import (
    preflight,probe_s3,probe_redis,main,
)

BUCKET="handraw-phase21-qa-test-resource"
PREFIX="phase21-qa:isolated123"
ENV="preprod-phase21-infra"


class AccessDenied(Exception):
    def __init__(self):
        self.response={"Error":{"Code":"AccessDenied"},
                       "ResponseMetadata":{"HTTPStatusCode":403}}


class NoPermissionError(Exception):
    pass


class FakeS3:
    def __init__(self,state,tenant,*,ignore_acl=False,allow_list=False,
                 allow_cross_delete=False,mutate_then_deny=False):
        self.state=state
        self.tenant=tenant
        self.ignore_acl=ignore_acl
        self.allow_list=allow_list
        self.allow_cross_delete=allow_cross_delete
        self.mutate_then_deny=mutate_then_deny
        self.cleared=[]
    def allowed(self,key):
        return (self.ignore_acl or
                (self.tenant in ("tenant-a","tenant-b")
                 and f"/{self.tenant}/" in key))
    def put_object(self,*,Bucket,Key,Body,**kwargs):
        if self.tenant=="anonymous" or not self.allowed(Key):
            if self.mutate_then_deny and self.tenant!="anonymous":
                self.state[Key]=Body
            raise AccessDenied()
        self.state[Key]=Body
        return {}
    def get_object(self,*,Bucket,Key,**kwargs):
        if self.tenant=="anonymous" or not self.allowed(Key):
            raise AccessDenied()
        return {"Body":BytesIO(self.state[Key])}
    def delete_object(self,*,Bucket,Key):
        if not self.allowed(Key) and not self.allow_cross_delete:
            raise AccessDenied()
        self.cleared.append(Key)
        self.state.pop(Key,None)
    def list_objects_v2(self,*,Bucket,Prefix):
        if not self.allowed(Prefix) and not self.allow_list:
            raise AccessDenied()
        return {"Contents":[{"Key":k} for k in self.state if k.startswith(Prefix)]}
    def generate_presigned_url(self,*args,**kwargs):
        return "https://s3.example.test/temporarily-signed"


class FakeRedis:
    def __init__(self,state,role):
        self.state=state
        self.role=role
    def _allowed(self,key):
        if self.role.startswith("tenant-") and f":{self.role}:" not in key:
            raise NoPermissionError("ACL key scope violation")
    def ping(self):
        return True
    def set(self,key,value,*,nx=False,ex=None):
        self._allowed(key)
        if nx and key in self.state:
            return None
        self.state[key]=value
        return True
    def get(self,key):
        self._allowed(key)
        return self.state.get(key)
    def delete(self,key):
        self._allowed(key)
        self.state.pop(key,None)
    def eval(self,script,n,key,tag):
        if self.state.get(key)==tag:
            self.state.pop(key,None)


class Phase21InfraTest(unittest.TestCase):
    def test_live_requires_disposable_approved_tls_dedicated_target(self):
        with self.assertRaises(ValueError):
            preflight(environment=ENV,endpoint="https://s3.example.test",
                      bucket=BUCKET,prefix=PREFIX,run=True)
        with patch.dict(os.environ,{"HANDRAW_PHASE21_INFRA_D_PROBE":"YES"}):
            out=preflight(environment=ENV,endpoint="https://s3.example.test",
                      bucket=BUCKET,prefix=PREFIX,run=True)
        self.assertFalse(out["externalProviderActuallyContacted"])
        self.assertEqual(out["decision"],"NO-GO")
        for endpoint in ("http://s3.example.test","https://localhost:9000",
                         "https://attacker:pwd@s3.example.test"):
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):
                preflight(environment=ENV,endpoint=endpoint,bucket=BUCKET)
        for bucket in ("production-media","handraw-phase21-qa-",""):
            with self.subTest(bucket=bucket),self.assertRaises(ValueError):
                preflight(environment=ENV,endpoint="https://s3.example.test",bucket=bucket)
        with self.assertRaises(ValueError):
            preflight(environment="production",prefix=PREFIX)
        with self.assertRaises(ValueError):
            preflight(environment=ENV,prefix="handraw:production")

    def test_scoped_s3_a_b_and_anonymous_denials_are_observed_without_claiming_d(self):
        state={}
        a=FakeS3(state,"tenant-a")
        b=FakeS3(state,"tenant-b")
        anon=FakeS3(state,"anonymous")
        statuses=iter((200,403))
        def checker(url,*,expected_hostname):
            self.assertEqual(expected_hostname,"s3.example.test")
            self.assertNotIn("Secret",url)
            return next(statuses)
        out=probe_s3(a,b,anon,bucket=BUCKET,prefix=PREFIX,
            endpoint_host="s3.example.test",signed_url_checker=checker,
            sleep=lambda _:None)
        self.assertTrue(out["observed"]["ownBytesMatched"])
        self.assertTrue(out["observed"]["crossTenantReadDeniedBothDirections"])
        self.assertTrue(out["observed"]["crossTenantWriteDeniedBothDirections"])
        self.assertTrue(out["observed"]["crossTenantDeleteDeniedBothDirections"])
        self.assertTrue(out["observed"]["crossTenantListDeniedBothDirections"])
        self.assertTrue(out["observed"]["postDeniedProbeOwnBytesMatched"])
        self.assertTrue(out["observed"]["anonymousDenied"])
        self.assertTrue(out["observed"]["expiredSignedUrlDenied"])
        self.assertFalse(out["cdnOldUrlInvalidated"])
        self.assertFalse(out["realProviderSourceIndependentlyAudited"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertEqual(state,{})
        self.assertNotIn(PREFIX,json.dumps(out))

    def test_s3_cross_tenant_allowed_fails_and_still_cleans_own_test_objects(self):
        state={}
        a=FakeS3(state,"tenant-a",ignore_acl=True)
        b=FakeS3(state,"tenant-b",ignore_acl=True)
        anon=FakeS3(state,"anonymous")
        with self.assertRaisesRegex(ValueError,"policy allowed access"):
            probe_s3(a,b,anon,bucket=BUCKET,prefix=PREFIX,
                     endpoint_host="s3.example.test")
        self.assertEqual(state,{})

    def test_s3_unscoped_delete_or_listing_is_a_strict_failure(self):
        for violation,flags in (
            ("delete",{"allow_cross_delete":True}),
            ("list",{"allow_list":True}),
            ("mutated_403",{"mutate_then_deny":True}),
        ):
            with self.subTest(violation=violation):
                state={}
                a=FakeS3(state,"tenant-a",**flags)
                b=FakeS3(state,"tenant-b",**flags)
                anon=FakeS3(state,"anonymous")
                with self.assertRaisesRegex(ValueError,"policy allowed access"):
                    probe_s3(a,b,anon,bucket=BUCKET,prefix=PREFIX,
                             endpoint_host="s3.example.test")
                # Only disposable canary objects ever existed, and owner
                # cleanup must remove them even after a policy violation.
                self.assertEqual(state,{})

    def test_s3_404_or_timeout_does_not_pass_cross_tenant_list_authz(self):
        class NoSuchKey(Exception):
            def __init__(self):
                self.response={"Error":{"Code":"NoSuchKey"},
                               "ResponseMetadata":{"HTTPStatusCode":404}}
        for error in (NoSuchKey,TimeoutError):
            class BogusList(FakeS3):
                def list_objects_v2(self,*,Bucket,Prefix):
                    raise error()
            with self.subTest(error=error.__name__):
                state={}
                a=BogusList(state,"tenant-a")
                b=FakeS3(state,"tenant-b")
                anon=FakeS3(state,"anonymous")
                with self.assertRaisesRegex(ValueError,"policy allowed access"):
                    probe_s3(a,b,anon,bucket=BUCKET,prefix=PREFIX,
                             endpoint_host="s3.example.test")
                self.assertEqual(state,{})

    def test_s3_expired_url_network_outage_does_not_prove_expiry(self):
        state={}
        a=FakeS3(state,"tenant-a")
        b=FakeS3(state,"tenant-b")
        anon=FakeS3(state,"anonymous")
        out=probe_s3(a,b,anon,bucket=BUCKET,prefix=PREFIX,
                     endpoint_host="s3.example.test",
                     signed_url_checker=lambda url,**k:200,
                     sleep=lambda _:None)
        self.assertFalse(out["observed"]["expiredSignedUrlDenied"])

    def test_two_redis_app_clients_shared_lock_but_tenant_ACL_isolated(self):
        data={}
        a=FakeRedis(data,"coordinator-a")
        b=FakeRedis(data,"coordinator-b")
        t1=FakeRedis(data,"tenant-a")
        t2=FakeRedis(data,"tenant-b")
        out=probe_redis(a,b,t1,t2,prefix=PREFIX)
        self.assertTrue(out["crossClientAtomicNxObserved"])
        self.assertTrue(out["redisTenantAclDeniedBothDirections"])
        self.assertFalse(out["automaticFailoverVerified"])
        self.assertFalse(out["twoPhysicalWebInstancesIndependentlyProven"])
        self.assertEqual(data,{})
        self.assertNotIn(PREFIX,json.dumps(out))

    def test_redis_broken_tenant_acl_or_split_brain_never_passes(self):
        shared={}
        a=FakeRedis(shared,"coordinator-a")
        b=FakeRedis(shared,"coordinator-b")
        t1=FakeRedis(shared,"coordinator-a")  # accidental unscoped writer
        t2=FakeRedis(shared,"tenant-b")
        with self.assertRaisesRegex(ValueError,"ACL isolation"):
            probe_redis(a,b,t1,t2,prefix=PREFIX)
        a=FakeRedis({},"coordinator-a")
        b=FakeRedis({},"coordinator-b")
        t1=FakeRedis({},"tenant-a")
        t2=FakeRedis({},"tenant-b")
        with self.assertRaises(ValueError):
            probe_redis(a,b,t1,t2,prefix=PREFIX)

    def test_cli_plan_only_never_opens_network(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"infra.json"
            with patch.dict(os.environ,{"HANDRAW_PHASE21_INFRA_D_PROBE":""}):
                self.assertEqual(main(["--mode","plan","--environment",ENV,
                                       "--report",str(path)]),0)
                self.assertEqual(json.loads(path.read_text())["decision"],"NO-GO")
                self.assertEqual(main(["--mode","plan","--environment",ENV,
                                       "--report",str(path)]),2)
                self.assertEqual(main(["--mode","redis","--environment",ENV,
                                       "--prefix",PREFIX,
                                       "--report",str(Path(temp)/"no.json")]),2)


if __name__=="__main__":
    unittest.main()
