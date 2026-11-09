"""Phase21 #132: read-only, Website-authoritative official catalog snapshot.

Unlike generic Skill export, this does NOT treat existing Skill IDs as a
website-approval conflict. All proposed official rows must first have been
published by the website editor. It NEVER inserts/reviews/publishes rows and
NEVER writes to Skill. Live PG is opt-in and must be preproduction read-only.
No approval or GO is implied by a completed export or its SHA claims.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.studio_official_approval_132 import sha,CODES

CODE=re.compile(r"^[A-Z]{2}-[0-9]{3}$")
ENV=re.compile(r"^HANDRAW_PHASE21_[A-Z0-9_]{3,64}$")
IDENT=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
ALLOW="HANDRAW_PHASE21_ALLOW_WEBSITE_READONLY_EXPORT"
QUERY=(
    "SELECT code,kind,name,group_name,description,definition,"
    "unlock_cost,source_type,status FROM catalog_assets "
    "WHERE source_type = 'official' AND status = 'published' "
    "ORDER BY code ASC"
)


def transform(rows):
    """Deterministic published DB -> Web-approved Skill-facing read-only export."""
    if not isinstance(rows,list) or len(rows)>3000:
        raise ValueError("unexpected official export size")
    styles=[]
    layouts=[]
    seen=set()
    raw=[]
    for row in rows:
        required={"code","kind","name","group_name","description","definition",
                  "unlock_cost","source_type","status"}
        if not isinstance(row,dict) or set(row)!=required:
            raise ValueError("unreviewed DB snapshot shape")
        code,kind,name=row["code"],row["kind"],row["name"]
        if (not isinstance(code,str) or not CODE.fullmatch(code) or code in seen
                or kind not in ("style","layout")
                or not isinstance(name,str) or not name.strip()
                or len(name)>200 or row["source_type"]!="official"
                or row["status"]!="published"):
            raise ValueError("invalid/duplicate/unpublished official DB record")
        seen.add(code)
        if any(value is not None and not isinstance(value,str)
               for value in (row["group_name"],row["description"],row["definition"])):
            raise ValueError("invalid published official metadata")
        cost=row["unlock_cost"]
        if type(cost) is not int or not 0<=cost<=10**8:
            raise ValueError("invalid official unlock cost")
        desc=str(row["description"] or "").strip()
        definition=str(row["definition"] or "").strip()
        group=str(row["group_name"] or "").strip()
        if kind=="style":
            item={"number":code,"group":group,"reference":"",
                  "generation_name":name,"traits":""}
            if cost==0:
                item["traits"]=desc or definition
                item["definition"]=definition
            styles.append(item)
        else:
            cat=group or "infographic"
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}",cat):
                raise ValueError("unsafe official layout group")
            keywords=[p.strip() for p in desc.split("、") if p.strip()] or [name]
            item={"id":code,"category":cat,"name":name,
                  "image":f"../../../images/layouts/{cat}/{code}.webp",
                  "keywords":keywords}
            if cost==0:
                item["prompt_file"]=f"layouts/{code}.md"
                item["definition"]=definition
            layouts.append(item)
        raw.append(row)
    return styles,layouts,sha(raw)


def build_receipt(*,styles,layouts,raw_digest,deployed_sha,
                  operator,reviewer,session):
    if (not isinstance(deployed_sha,str) or not re.fullmatch(r"[a-f0-9]{40}",deployed_sha)
        or not isinstance(raw_digest,str) or not re.fullmatch(r"[a-f0-9]{64}",raw_digest)):
        raise ValueError("deployed SHA/raw snapshot digest required")
    for v in (operator,reviewer,session):
        if not isinstance(v,str) or not IDENT.fullmatch(v):
            raise ValueError("invalid read-only DB export witness")
    if operator==reviewer:
        raise ValueError("DB export source must have independent reviewer")
    return {"schemaVersion":1,"sourceSystem":"website-postgresql-read-only",
        "sourceRole":"readonly-export","webDeployedSha":deployed_sha,
        "publishedStylesSha256":sha(styles),
        "publishedLayoutsSha256":sha(layouts),
        "sourceRowsSha256":raw_digest,"operatorId":operator,
        "independentReviewerId":reviewer,"exportSessionId":session}


def _new_private(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        json.dump(data,out,ensure_ascii=False,sort_keys=True,indent=2)
        out.write("\n")


def write_fresh(out_dir,styles,layouts,receipt):
    root=Path(out_dir)
    if root.is_symlink() or root.exists() or not root.parent.is_dir():
        raise ValueError("only a NEW private export directory is allowed")
    root.mkdir(mode=0o700)
    _new_private(root/"styles.json",styles)
    _new_private(root/"layouts.json",layouts)
    _new_private(root/"readonly-export-receipt.json",receipt)
    return {"dbStylesExported":len(styles),"dbLayoutsExported":len(layouts),
            "candidateCodesInReadOnlyExport":sorted(
                set(CODES)&{x["number"] for x in styles}),
            "rawRowsOrPersonalDetailsEmitted":False,
            "trueDbOriginIndependentlyAttested":False,
            "automaticWebsiteApprovalGranted":False,
            "decision":"NO-GO"}


def load_readonly_pg(*,dsn_env):
    if not isinstance(dsn_env,str) or not ENV.fullmatch(dsn_env):
        raise ValueError("read-only DSN env name required")
    if os.environ.get(ALLOW)!="YES":
        raise ValueError("website PG read-only snapshot not authorized")
    dsn=os.environ.get(dsn_env,"")
    if not dsn:
        raise ValueError("read-only website DSN not available")
    import psycopg
    from psycopg.rows import dict_row
    # Source credentials never printed or passed on CLI. A read-only account
    # with server-enforced SELECT-only privileges is an operator prerequisite.
    with psycopg.connect(dsn,row_factory=dict_row,
                         autocommit=False,connect_timeout=5) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        ro=db.execute("SHOW transaction_read_only").fetchone()
        version=db.execute("SHOW server_version_num").fetchone()
        read_only=ro.get("transaction_read_only") if isinstance(ro,dict) else ro[0]
        version_number=version.get("server_version_num") if isinstance(version,dict) else version[0]
        if read_only!="on" or int(version_number)//10000!=17:
            raise ValueError("requires read-only PostgreSQL 17 official DB session")
        rows=db.execute(QUERY).fetchall()
    return [dict(row) for row in rows]


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsn-env",required=True)
    p.add_argument("--environment",required=True)
    p.add_argument("--deployed-sha",required=True)
    p.add_argument("--operator-id",required=True)
    p.add_argument("--independent-reviewer-id",required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if not re.fullmatch(r"preprod-[a-z0-9][a-z0-9-]{3,55}",args.environment):
            raise ValueError("preproduction-only Web DB export allowed")
        rows=load_readonly_pg(dsn_env=args.dsn_env)
        styles,layouts,original_hash=transform(rows)
        receipt=build_receipt(styles=styles,layouts=layouts,
            raw_digest=original_hash,deployed_sha=args.deployed_sha,
            operator=args.operator_id,reviewer=args.independent_reviewer_id,
            session="web-export-"+secrets.token_hex(12))
        output=write_fresh(args.out,styles,layouts,receipt)
        print("PHASE21 WEB READONLY EXPORT "+json.dumps(output,sort_keys=True))
        return 0
    except Exception:
        print("Phase21 website published DB export BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
