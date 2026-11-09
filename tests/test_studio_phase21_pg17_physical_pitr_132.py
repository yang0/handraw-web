"""Phase21 guarded physical PG17 PITR: fake runner only, zero real connections."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime,timezone,timedelta
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ops.studio_phase21_pg17_physical_pitr_132 import (
    preflight,run_backup,prepare_pitr,verify_restored,main,
)

ENV="preprod-phase21-pg17"
TARGET="recovery-phase21"
SOURCE="staging-db.internal"
LEAF="pitr-phase21-check"
UTC=(datetime.now(timezone.utc)+timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Exit:
    returncode=0


class FakeRunner:
    def __init__(self):
        self.commands=[]
    def __call__(self,argv,**kwargs):
        self.commands.append((argv,kwargs))
        if argv[0]=="pg_basebackup":
            path=Path(argv[argv.index("--pgdata")+1])
            path.mkdir(mode=0o700)
            (path/"backup_manifest").write_bytes(b"PG17 physical backup manifest")
            (path/"PG_VERSION").write_text("17\n")
            (path/"postgresql.auto.conf").write_text("")
        return Exit()


class DbRows:
    def __init__(self,value):
        self.value=value
    def fetchone(self):
        return self.value


class FakePg:
    def __init__(self,paused="paused",version=170002):
        self.paused=paused
        self.version=version
    def __enter__(self): return self
    def __exit__(self,*a): return None
    def execute(self,sql):
        if "SHOW server_version_num" in sql:
            return DbRows((str(self.version),))
        if "pg_is_in_recovery()" in sql:
            return DbRows((True,self.paused,"0/2000010"))
        return DbRows(None)


class Phase21PhysicalPg17Tests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root=Path(self.dir.name)
        self.base=root/"backup-root"
        self.wal=root/"wal-archive"
        self.base.mkdir()
        self.wal.mkdir()
        self.source=SOURCE
        self.host=TARGET
        self.patcher=patch("ops.studio_phase21_pg17_physical_pitr_132.socket.gethostname",
                           return_value=TARGET)
        self.patcher2=patch("ops.studio_phase21_pg17_physical_pitr_132.socket.getfqdn",
                            return_value=TARGET)
        self.patcher.start()
        self.patcher2.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.patcher2.stop)

    def plan(self,run=False):
        return preflight(environment=ENV,source_host=self.source,
               target_host=self.host,root=self.base,leaf=LEAF,
               archive_dir=self.wal,target_utc=UTC,run=run)

    def test_preflight_dry_plan_is_isolated_and_never_go(self):
        out=self.plan()
        self.assertEqual(out["decision"],"NO-GO")
        self.assertFalse(out["destructiveSourceOperationsAllowed"])
        self.assertFalse(out["automaticDatabaseStartupAllowed"])
        self.assertFalse(Path(out["backupDir"]).exists())
        with self.assertRaises(ValueError):
            self.plan(run=True)

    def test_host_identity_source_collision_and_target_overwrite_blocked(self):
        for field,value in (("source_host",TARGET),("source_host","localhost"),
                            ("target_host","unrelated-host"),
                            ("environment","production"),
                            ("target_utc","2020-03-01"),
                            ("leaf","../main")):
            args=dict(environment=ENV,source_host=SOURCE,target_host=TARGET,
                      root=self.base,leaf=LEAF,archive_dir=self.wal,target_utc=UTC)
            args[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                preflight(**args)
        (self.base/LEAF).mkdir()
        with self.assertRaisesRegex(ValueError,"overwrite"):
            self.plan()

    def test_guarded_physical_basebackup_and_wal_recovery_configuration(self):
        fake=FakeRunner()
        with patch.dict(os.environ,{"HANDRAW_PHASE21_PG_ISOLATED_DRILL":"YES",
                                    "HANDRAW_PHASE21_PG_REPLICATION_PASSWORD":"test-never-log"}):
            plan=self.plan(run=True)
            report=run_backup(plan,user="limited_replication",port=5432,runner=fake)
            self.assertTrue(report["backupVerifiedByPgVerifybackup"])
            self.assertFalse(report["pitrReplayAlreadyVerified"])
            self.assertEqual([x[0][0] for x in fake.commands],
                             ["pg_basebackup","pg_verifybackup"])
            self.assertNotIn("test-never-log",repr([x[0] for x in fake.commands]))
            self.assertIn("PGPASSWORD",fake.commands[0][1]["env"])
            (self.wal/"000000010000000000000001").write_bytes(b"mock-archive-WAL")
            prepared=prepare_pitr(backup_dir=plan["backupDir"],
                archive_dir=self.wal,target_utc=UTC)
            self.assertFalse(prepared["replayVerified"])
            config=(Path(plan["backupDir"])/"postgresql.auto.conf").read_text()
            self.assertIn("recovery_target_action = 'pause'",config)
            self.assertIn("recovery_target_time = '"+UTC.replace("Z","+00")+"'",config)
            self.assertTrue((Path(plan["backupDir"])/"recovery.signal").exists())
            with self.assertRaises(ValueError):
                prepare_pitr(backup_dir=plan["backupDir"],
                             archive_dir=self.wal,target_utc=UTC)

    def test_missing_wal_or_tampered_manifest_blocks_pitr(self):
        with patch.dict(os.environ,{"HANDRAW_PHASE21_PG_ISOLATED_DRILL":"YES",
                                    "HANDRAW_PHASE21_PG_REPLICATION_PASSWORD":"fake"}):
            out=self.plan(run=True)
            run_backup(out,user="limited_replication",port=5432,runner=FakeRunner())
            with self.assertRaises(ValueError):
                prepare_pitr(backup_dir=out["backupDir"],
                             archive_dir=self.wal,target_utc=UTC)
            Path(out["backupDir"],"backup_manifest").write_text("TAMPERED")
            (self.wal/"000000010000000000000001").write_bytes(b"fake")
            with self.assertRaisesRegex(ValueError,"manifest changed"):
                prepare_pitr(backup_dir=out["backupDir"],
                             archive_dir=self.wal,target_utc=UTC)

    def test_readonly_pg17_target_fingerprint_and_paused_replay(self):
        import psycopg
        expected={"schemaVersion":1,"targetUtc":UTC,
                  "backupManifestSha256":"a"*64,
                  "expected":{"rowCounts":{"wallets":2},
                              "rowSha256":{"wallets":"b"*64}}}
        with patch.dict(os.environ,{"HANDRAW_PHASE21_PG_ISOLATED_DRILL":"YES"}), \
             patch("ops.studio_phase21_pg17_physical_pitr_132.settings",
                    return_value={"host":"127.0.0.1","dbname":"handraw_restore_drill_test"}), \
             patch("ops.studio_phase21_pg17_physical_pitr_132.fingerprint",
                    return_value=expected["expected"]), \
             patch.object(psycopg,"connect",return_value=FakePg()):
            out=verify_restored(target_dsn="host=127.0.0.1 dbname=handraw_restore_drill_test",
                                expected=expected,declared_host=TARGET)
            self.assertEqual(out["decision"],"NO-GO")
            self.assertTrue(out["pg17ReplayPausedAndRowsMatched"])
            self.assertFalse(out["physicalClusterAndWALProvenByThisReport"])
            expected["expected"]["rowCounts"]["wallets"]=3
            with patch("ops.studio_phase21_pg17_physical_pitr_132.fingerprint",
                       return_value={"rowCounts":{"wallets":2},
                                     "rowSha256":{"wallets":"b"*64}}):
                with self.assertRaises(ValueError):
                    verify_restored(target_dsn="host=127.0.0.1 dbname=test",
                                    expected=expected,declared_host=TARGET)
        with patch.dict(os.environ,{"HANDRAW_PHASE21_PG_ISOLATED_DRILL":"YES"}), \
             patch("ops.studio_phase21_pg17_physical_pitr_132.settings",
                   return_value={"host":"remote.example","dbname":"test"}):
            with self.assertRaises(ValueError):
                verify_restored(target_dsn="host=remote.example dbname=test",
                                expected=expected,declared_host=TARGET)

    def test_cli_plan_writes_private_report_and_cannot_overwrite(self):
        report=Path(self.dir.name)/"report.json"
        args=["--mode","plan","--environment",ENV,
              "--source-host",SOURCE,"--target-host",TARGET,
              "--root",str(self.base),"--leaf",LEAF,
              "--archive-dir",str(self.wal),"--target-utc",UTC,
              "--report",str(report)]
        self.assertEqual(main(args),0)
        self.assertEqual(json.loads(report.read_text())["decision"],"NO-GO")
        self.assertEqual(main(args),2)
        self.assertFalse((self.base/LEAF).exists())


if __name__=="__main__":
    unittest.main()
