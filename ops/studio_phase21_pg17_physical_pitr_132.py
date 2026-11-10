"""Phase21 #132: guarded PG17 PHYSICAL basebackup -> WAL/PITR preparation -> read-only restore audit.

Run on a dedicated PREPRODUCTION recovery host, never in Actions or on a
live PG data directory. NO drops, rm, --clean, source SQL writes, or starting
a database automatically. The target must be a NEW, isolated directory;
an operator is responsible for the actual isolated pg_ctl start and shutdown.
Proof of a real independent host/PITR still requires human D-level review.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.pg_release_restore_drill_112 import fingerprint, settings

LABEL=re.compile(r"^preprod-[a-z0-9][a-z0-9-]{3,55}$")
HOST=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,180}$")
SAFE_PATH=re.compile(r"^/[A-Za-z0-9_./-]+$")
WAL_FILE=re.compile(r"^[A-F0-9]{24}(?:\.[A-Za-z0-9]+)?$")
HASH=re.compile(r"^[a-f0-9]{64}$")
TARGET=re.compile(r"^pitr-[a-z0-9-]{8,64}$")
UTC=re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
ALLOW="HANDRAW_PHASE21_PG_ISOLATED_DRILL"
MAX_INPUT=256_000


def _dir(path,*,required=False):
    """Reject symlinked ancestors, not only the final directory.

    This runs before ever constructing restore_command or opening a backup
    output. An alias of the recovery root must not reach a non-QA tree.
    """
    p=Path(path)
    if (not p.is_absolute() or p==Path("/") or
        not SAFE_PATH.fullmatch(str(p)) or ".." in p.parts):
        raise ValueError("unsafe PITR directory")
    if any(part.is_symlink() for part in (p,*p.parents)):
        raise ValueError("PITR path or ancestor is a symbolic link")
    if p.exists() and not p.is_dir():
        raise ValueError("PITR path non-directory")
    if required and not p.is_dir():
        raise ValueError("required PITR root absent")
    return p


def _separate_directories(left,right):
    """Never permit archived WAL to alias or contain a recovery data tree."""
    if left==right or left in right.parents or right in left.parents:
        raise ValueError("WAL archive and PITR target roots must be separate")


def _host_pair(source_host,target_host):
    if any(not isinstance(v,str) or not HOST.fullmatch(v)
           for v in (source_host,target_host)):
        raise ValueError("explicit host identities required")
    forbidden={"localhost","127.0.0.1","0.0.0.0","::1"}
    if source_host.lower() in forbidden or source_host.lower()==target_host.lower():
        raise ValueError("PITR source may not be local or equal target")
    current={socket.gethostname().lower(),socket.getfqdn().lower()}
    if target_host.lower() not in current:
        raise ValueError("must execute on the declared independent recovery host")


def _time(value):
    if not isinstance(value,str) or not UTC.fullmatch(value):
        raise ValueError("PITR target must be precise UTC YYYY-MM-DDTHH:MM:SSZ")
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed>datetime.now(timezone.utc)+timedelta(minutes=5):
        raise ValueError("future PITR target")
    return value


def preflight(*,environment,source_host,target_host,root,leaf,archive_dir,
              target_utc,run=False):
    if not isinstance(environment,str) or not LABEL.fullmatch(environment):
        raise ValueError("preproduction-only environment ID required")
    _host_pair(source_host,target_host)
    base=_dir(root,required=True)
    wal=_dir(archive_dir,required=True)
    _separate_directories(base,wal)
    if not isinstance(leaf,str) or not TARGET.fullmatch(leaf):
        raise ValueError("invalid new disposable PITR directory name")
    dest=base/leaf
    if dest.exists() or dest.is_symlink():
        raise ValueError("never overwrite an existing recovery directory")
    _time(target_utc)
    if run and os.environ.get(ALLOW)!="YES":
        raise ValueError("explicit isolated PG D drill approval required")
    return {"environment":environment,"sourceHost":source_host,
            "targetHost":target_host,"backupDir":str(dest),
            "archiveDir":str(wal),"targetUtc":target_utc,
            "destructiveSourceOperationsAllowed":False,
            "automaticDatabaseStartupAllowed":False,
            "decision":"NO-GO"}


def _read_private(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>MAX_INPUT:
        raise ValueError("invalid private PITR witness")
    if os.name=="posix" and stat.S_IMODE(p.stat().st_mode)&0o077:
        raise ValueError("PITR witness must be 0600")
    return json.loads(p.read_text(encoding="utf-8"))


def _new_private(path,obj):
    p=Path(path)
    if p.is_symlink() or p.exists():
        raise ValueError("never overwrite a PITR audit record")
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        json.dump(obj,out,ensure_ascii=False,indent=2,sort_keys=True)
        out.write("\n")


def run_backup(plan,*,user,port,runner=subprocess.run):
    """Real pg_basebackup on dedicated recovery host, opt-in only.

    The source is a designated preproduction replication endpoint; credentials
    are passed only via inherited PG env, never arguments/logs.
    """
    if os.environ.get(ALLOW)!="YES":
        raise ValueError("real backup not explicitly authorized")
    if not isinstance(user,str) or not HOST.fullmatch(user):
        raise ValueError("missing limited replication username")
    if type(port) is not int or not 1<=port<=65535:
        raise ValueError("invalid PG source port")
    # Do not trust a forged plan passed by another Python caller: the CLI
    # preflight's host/path restrictions remain mandatory in run_backup.
    if (not isinstance(plan,dict)
        or not isinstance(plan.get("environment"),str)
        or not LABEL.fullmatch(plan["environment"])):
        raise ValueError("isolated preproduction backup plan required")
    root=Path(plan["backupDir"])
    if not TARGET.fullmatch(root.name):
        raise ValueError("dedicated disposable recovery leaf required")
    base=_dir(root.parent,required=True)
    wal=_dir(plan["archiveDir"],required=True)
    _host_pair(plan["sourceHost"],plan["targetHost"])
    _separate_directories(base,wal)
    _dir(root)
    if root.exists():
        raise ValueError("backup target must be absent")
    if not os.environ.get("HANDRAW_PHASE21_PG_REPLICATION_PASSWORD"):
        raise ValueError("replication credentials missing")
    env={**os.environ,"PGPASSWORD":os.environ["HANDRAW_PHASE21_PG_REPLICATION_PASSWORD"],
         "PGCONNECT_TIMEOUT":"5"}
    argv=["pg_basebackup","--host",plan["sourceHost"],"--port",str(port),
          "--username",user,"--pgdata",str(root),
          "--format=plain","--wal-method=stream","--checkpoint=fast",
          "--no-password","--progress"]
    try:
        proc=runner(argv,env=env,check=False,stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,timeout=3600)
    except (OSError,subprocess.TimeoutExpired):
        raise RuntimeError("pg_basebackup failed (details intentionally redacted)") from None
    if proc.returncode!=0:
        raise RuntimeError("pg_basebackup failed; partial target must be handled by operator")
    manifest=root/"backup_manifest"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("PG17 physical backup_manifest missing")
    tool=runner(["pg_verifybackup",str(root)],env=env,check=False,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=600)
    if tool.returncode!=0:
        raise ValueError("pg_verifybackup rejected physical basebackup")
    if not (root/"PG_VERSION").is_file() or (root/"PG_VERSION").read_text().strip()!="17":
        raise ValueError("physical basebackup is not PG17")
    evidence={"mode":"isolated-real-pg17-physical-basebackup",
              "backupManifestSha256":hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "environment":plan["environment"],
              "sourceAndRecoveryHostsDeclaredDistinct":True,
              "backupVerifiedByPgVerifybackup":True,
              "basebackupCompletedAtUtc":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "pitrReplayAlreadyVerified":False,
              "productionReleaseAuthorized":False,"decision":"NO-GO"}
    _new_private(root/"phase21-physical-backup.json",evidence)
    return evidence


def prepare_pitr(*,backup_dir,archive_dir,target_utc):
    """Create recovery.signal and append restore settings in verified cold copy.

    This intentionally does not launch PostgreSQL; pg_ctl is operator-owned.
    """
    if os.environ.get(ALLOW)!="YES":
        raise ValueError("PITR preparation requires isolated drill approval")
    b=_dir(backup_dir,required=True)
    a=_dir(archive_dir,required=True)
    _separate_directories(b,a)
    if not TARGET.fullmatch(b.name):
        raise ValueError("untrusted disposable recovery directory")
    evidence=_read_private(b/"phase21-physical-backup.json")
    if (evidence.get("mode")!="isolated-real-pg17-physical-basebackup"
        or evidence.get("backupVerifiedByPgVerifybackup") is not True
        or evidence.get("decision")!="NO-GO"):
        raise ValueError("physical backup not previously verified")
    manifest=b/"backup_manifest"
    if manifest.is_symlink() or not manifest.is_file() or hashlib.sha256(
            manifest.read_bytes()).hexdigest()!=evidence["backupManifestSha256"]:
        raise ValueError("basebackup manifest changed")
    if (not (b/"PG_VERSION").is_file() or
            (b/"PG_VERSION").read_text().strip()!="17"):
        raise ValueError("PG17 physical backup identity lost")
    files=[p for p in a.iterdir() if WAL_FILE.fullmatch(p.name) and p.is_file()
           and not p.is_symlink()]
    if not files:
        raise ValueError("no real archived WAL segments available")
    if not SAFE_PATH.fullmatch(str(a)):
        raise ValueError("unsafe WAL archive path")
    _time(target_utc)
    completed=_time(evidence.get("basebackupCompletedAtUtc"))
    if target_utc<=completed:
        raise ValueError("physical PITR target must be AFTER basebackup completion")
    signal=b/"recovery.signal"
    config=b/"postgresql.auto.conf"
    if signal.exists() or signal.is_symlink() or not config.is_file() or config.is_symlink():
        raise ValueError("recovery already configured or unsafe auto.conf")
    existing=config.read_text(encoding="utf-8")
    if any(v in existing for v in ("restore_command =","recovery_target_time =",
                                    "recovery_target_action =")):
        raise ValueError("existing recovery settings cannot be overwritten")
    # Restrict archive directory above to characters safe in PG's single-
    # quoted command; both placeholders are PostgreSQL-provided filenames.
    conf=("\n# Phase21 isolated PITR target; operator must start via local-only pg_ctl\n"
          + "restore_command = 'cp -- "+str(a)+"/%f %p'\n"
          + "recovery_target_time = '"+target_utc.replace("Z","+00")+"'\n"
          + "recovery_target_action = 'pause'\n")
    with config.open("a",encoding="utf-8") as file:
        file.write(conf)
    signal.open("x").close()
    report={"mode":"isolated-pitr-prepared-not-started",
            "backupManifestSha256":evidence["backupManifestSha256"],
            "walArchiveSegmentCount":len(files),
            "targetUtc":target_utc,"replayVerified":False,
            "productionReleaseAuthorized":False,"decision":"NO-GO"}
    _new_private(b/"phase21-pitr-prepare.json",report)
    return report


def verify_restored(*,target_dsn,expected,declared_host):
    """Read-only post-recovery PG17 and business state fingerprint check.

    Operator must first start the isolated cluster on 127.0.0.1 and pause at
    recovery_target_time; DO NOT connect this to any production endpoint.
    """
    if os.environ.get(ALLOW)!="YES":
        raise ValueError("PITR verification not authorized")
    info=settings(target_dsn)
    if (info.get("host") not in ("127.0.0.1","localhost")
        or declared_host.lower() not in {socket.getfqdn().lower(),
                                         socket.gethostname().lower()}
        or any(info.get(field) for field in ("hostaddr","service","servicefile"))
        or any(os.environ.get(field) for field in
               ("PGHOSTADDR","PGSERVICE","PGSERVICEFILE"))):
        raise ValueError("read-only restore DSN must target only the local recovery host")
    if (not isinstance(expected,dict) or set(expected)!={"schemaVersion","expected",
            "targetUtc","backupManifestSha256","sourceSystemIdentifierSha256"}
        or expected["schemaVersion"]!=1
        or not isinstance(expected["backupManifestSha256"],str)
        or not HASH.fullmatch(expected["backupManifestSha256"])
        or not isinstance(expected.get("sourceSystemIdentifierSha256"),str)
        or not HASH.fullmatch(expected["sourceSystemIdentifierSha256"])):
        raise ValueError("invalid out-of-band pre-target snapshot/PG cluster identity")
    _time(expected["targetUtc"])
    import psycopg
    # The conninfo host label alone does not pin the endpoint: libpq may
    # resolve it using hostaddr/service/PGHOSTADDR.  Force the network target
    # to numeric loopback in both this audit and the following fingerprint
    # connection, even when the caller used the name "localhost".
    from psycopg.conninfo import make_conninfo
    local_dsn=make_conninfo(target_dsn,host="127.0.0.1",hostaddr="127.0.0.1")
    with psycopg.connect(local_dsn,autocommit=False,connect_timeout=5) as pg:
        pg.execute("SET TRANSACTION READ ONLY")
        addr=pg.execute("SELECT inet_server_addr()").fetchone()
        if not addr or str(addr[0]) not in ("127.0.0.1","::1"):
            raise ValueError("connected PostgreSQL server is not on loopback")
        version=int(pg.execute("SHOW server_version_num").fetchone()[0])
        if version//10000!=17:
            raise ValueError("restore is not PostgreSQL 17")
        in_recovery,paused,lsn=pg.execute(
            "SELECT pg_is_in_recovery(), "
            "pg_get_wal_replay_pause_state(), pg_last_wal_replay_lsn()").fetchone()
        if in_recovery is not True or paused!="paused" or lsn is None:
            raise ValueError("PITR recovery is not paused at target")
        # A different local PG17 instance can satisfy version/paused checks
        # and even contain copied business rows.  Pin its physical cluster
        # identity to the source's independently collected pre-backup witness.
        # This is a read-only query on the restored local PG control file.
        system_row=pg.execute(
            "SELECT system_identifier FROM pg_control_system()").fetchone()
        system_id=system_row[0] if system_row and len(system_row)==1 else None
        if type(system_id) is not int or not (0 < system_id < 2**64):
            raise ValueError("invalid recovered PG17 cluster system identifier")
        actual_id_hash=hashlib.sha256(str(system_id).encode("ascii")).hexdigest()
        if actual_id_hash!=expected["sourceSystemIdentifierSha256"]:
            raise ValueError("recovered PG17 cluster identity does not match source witness")
    observed=fingerprint(local_dsn)
    if observed!=expected["expected"]:
        raise ValueError("business tables differ from pre-target snapshot")
    return {"mode":"isolated-postgres17-pitr-readonly-verified",
            "physicalClusterAndWALProvenByThisReport":False,
            "pg17ReplayPausedAndRowsMatched":True,
            "clusterIdentifierMatchesOutOfBandClaim":True,
            "sourceClusterIdentityIndependentlyAuthenticatedHere":False,
            "independentHumanAuditStillRequired":True,
            "fingerprintsDigestSha256":hashlib.sha256(json.dumps(
                observed,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "productionReleaseAuthorized":False,"decision":"NO-GO"}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode",choices=["plan","backup","prepare","verify"],required=True)
    ap.add_argument("--environment",required=True)
    ap.add_argument("--source-host",required=True)
    ap.add_argument("--target-host",required=True)
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--leaf",required=True)
    ap.add_argument("--archive-dir",type=Path,required=True)
    ap.add_argument("--target-utc",required=True)
    ap.add_argument("--source-user",default="")
    ap.add_argument("--source-port",type=int,default=5432)
    ap.add_argument("--expected-witness",type=Path)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        if not isinstance(args.environment,str) or not LABEL.fullmatch(args.environment):
            raise ValueError("preproduction-only environment required")
        if args.report.exists() or args.report.is_symlink():
            raise ValueError("report must be new")
        # Only plan/backup require an absent target; prepare/verify use the
        # backed up directory and re-check all other safety preconditions.
        if args.mode in ("plan","backup"):
            plan=preflight(environment=args.environment,source_host=args.source_host,
                target_host=args.target_host,root=args.root,leaf=args.leaf,
                archive_dir=args.archive_dir,target_utc=args.target_utc,
                run=args.mode=="backup")
        else:
            # Prepare and verify must retain the same isolated-host and WAL
            # root constraints as plan/backup, despite the target now existing.
            root=_dir(args.root,required=True)
            archive=_dir(args.archive_dir,required=True)
            _separate_directories(root,archive)
            _host_pair(args.source_host,args.target_host)
            if not TARGET.fullmatch(args.leaf):
                raise ValueError("invalid disposable recovery leaf")
            target=_dir(root/args.leaf,required=True)
            _separate_directories(target,archive)
            plan={"backupDir":str(target),"targetUtc":_time(args.target_utc)}
        if args.mode=="plan":
            result=plan
        elif args.mode=="backup":
            result=run_backup(plan,user=args.source_user,port=args.source_port)
        elif args.mode=="prepare":
            result=prepare_pitr(backup_dir=plan["backupDir"],
                                archive_dir=args.archive_dir,target_utc=args.target_utc)
        else:
            if not args.expected_witness:
                raise ValueError("prior business-state witness required")
            witness=_read_private(args.expected_witness)
            backup=_read_private(Path(plan["backupDir"])/"phase21-physical-backup.json")
            prepared=_read_private(Path(plan["backupDir"])/"phase21-pitr-prepare.json")
            if (witness.get("targetUtc")!=plan["targetUtc"]
                or prepared.get("targetUtc")!=plan["targetUtc"]
                or witness.get("backupManifestSha256")!=backup.get("backupManifestSha256")
                or witness.get("backupManifestSha256")!=prepared.get("backupManifestSha256")):
                raise ValueError("physical backup, PITR target and expected fingerprint witness drift")
            result=verify_restored(
                target_dsn=os.environ.get("HANDRAW_PHASE21_PG_TARGET_DSN",""),
                expected=witness,declared_host=args.target_host)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        _new_private(args.report,result)
        print("PHASE21 PG17 "+json.dumps({"mode":args.mode,
            "decision":"NO-GO","rawCredentialsOrRowsEmitted":False}))
        return 0
    except Exception:
        print("Phase21 PG17 physical rehearsal BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
