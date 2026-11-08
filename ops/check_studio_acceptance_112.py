#!/usr/bin/env python3
"""#112 admission evidence *contract* check; does not execute a real image gateway.

The existing Checks jobs run the actual tests. This checker ensures that the
M0-M3 evidence matrix stays mapped to executable checked-in suites and to the
CI job that executes them. It cannot confer production Go approval.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/studio-2.0/acceptance-matrix-112.json"
WORKFLOW = ROOT / ".github/workflows/checks.yml"
REQUIRED_STAGES = {"M0", "M1", "M2", "M3"}
REQUIRED_JOBS = {
    "interaction-journey-regression", "python-full", "python-full-suite",
    "portable-client", "feed-ui-regression", "progressive-thumb-regression",
    "account-identity-regression", "v3-core-regression",
    "production-storage-integration",
}


def validate() -> dict:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    yaml_text = WORKFLOW.read_text(encoding="utf-8")
    assert matrix["issue"] == 112 and matrix["schema_version"] == 1
    assert set(matrix["stages"]) == REQUIRED_STAGES
    jobs = set(re.findall(r"^  ([a-z][a-z0-9-]+):\\s*$", yaml_text, re.M))
    assert REQUIRED_JOBS <= jobs, f"Missing CI jobs: {REQUIRED_JOBS - jobs}"
    assert "shard: [0, 1, 2, 3, 4, 5]" in yaml_text
    assert "ops/ci_python_shard.py --shards 6 --shard" in yaml_text
    assert "if: always()" in yaml_text and 'needs: [python-full]' in yaml_text

    ids = set()
    per_stage = {stage: [] for stage in matrix["stages"]}
    wired = []
    pending_live = []
    for case in matrix["cases"]:
        cid, stage = case["id"], case["stage"]
        assert stage in REQUIRED_STAGES and cid.startswith(stage + "-"), cid
        assert cid not in ids, f"Duplicate case id: {cid}"
        ids.add(cid)
        tests = case["tests"]
        assert len(tests) >= 2, f"{cid} needs independent evidence"
        assert case["ci_scope"] == "deterministic-mock-local-browser-or-contract"
        assert case.get("live_evidence_required"), cid
        live_status = case["live_gate"]
        assert live_status in {"PENDING", "EVIDENCED"}, (cid, live_status)
        if live_status == "EVIDENCED":
            assert str(case.get("live_evidence_url", "")).startswith("https://"), (
                cid, "live evidence cannot be claimed without a URL"
            )
        else:
            pending_live.append(cid)
        for path in tests:
            assert path.startswith("tests/") and ".." not in Path(path).parts, (cid, path)
            full_path = ROOT / path
            assert full_path.is_file(), (cid, f"missing {path}")
            if path.endswith(".cjs"):
                assert "node " + path in yaml_text, (cid, f"not CI-wired: {path}")
            elif path.startswith("tests/smoke_") or path.startswith("tests/benchmark_"):
                assert "python " + path in yaml_text, (cid, f"not CI-wired: {path}")
            else:
                assert path.endswith(".py"), (cid, path)
                assert (
                    Path(path).name in yaml_text
                    or "ops/ci_python_shard.py --shards 6 --shard" in yaml_text
                ), (cid, f"not CI-wired: {path}")
            wired.append(path)
        per_stage[stage].append(cid)

    assert all(len(v) >= 3 for v in per_stage.values()), per_stage
    assert any(
        "smoke_studio_make_image_browser_128.py" in c["tests"]
        for c in matrix["cases"] if c["stage"] == "M1"
    )
    assert any(
        "smoke_studio_series_browser_108.py" in c["tests"]
        for c in matrix["cases"] if c["stage"] == "M2"
    )
    assert any(
        "smoke_studio_article_browser_109.py" in c["tests"]
        for c in matrix["cases"] if c["stage"] == "M3"
    )
    assert any(
        "benchmark_studio_canvas.py" in c["tests"]
        for c in matrix["cases"] if c["stage"] == "M3"
    )
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=4
        ).strip()
    except (OSError, subprocess.SubprocessError):
        sha = "unknown"

    return {
        "schema_version": 1,
        "issue": 112,
        "commit": sha,
        "matrix_contract": "PASS",
        "assertion_boundary": (
            "Checks CI wiring and source availability only. Test execution "
            "results come from the matching GitHub Actions run."
        ),
        "unique_declared_test_files": len(set(wired)),
        "cases_by_stage": per_stage,
        "production_admission": "NO-GO" if pending_live else "REQUIRES_SEPARATE_RELEASE_REVIEW",
        "live_gate_pending": pending_live,
        "ci_jobs_expected": 14,
        "paid_gateway_called_by_checker": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        f"STUDIO #112 MATRIX CONTRACT PASS: "
        f"{sum(map(len, result['cases_by_stage'].values()))} cases, "
        f"{result['unique_declared_test_files']} mapped test files; "
        f"production {result['production_admission']}"
    )


if __name__ == "__main__":
    main()
