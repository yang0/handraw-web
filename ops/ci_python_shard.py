#!/usr/bin/env python3
"""Run the entire unittest discovery set in balanced, deterministic CI shards.

Tests are grouped by Python module, so test classes and their usual ordering
stay together. Every shard independently discovers the full manifest; LPT
bin-packing uses observed module durations rather than fragile hash buckets.

This intentionally uses only the Python standard library. No tests are
excluded, silently skipped, renamed, or made optional.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TIMINGS = Path(__file__).with_name("ci_python_weights.json")


def each_case(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from each_case(item)
        else:
            yield item


def discover() -> dict[str, list[unittest.TestCase]]:
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(ROOT / "tests"),
        pattern="test_*.py",
        top_level_dir=str(ROOT / "tests"),
    )
    if loader.errors:
        raise RuntimeError("unittest discovery failed:\n" + "\n".join(loader.errors))
    grouped: dict[str, list[unittest.TestCase]] = defaultdict(list)
    ids: list[str] = []
    for test in each_case(suite):
        name = test.__class__.__module__.split(".")[-1]
        grouped[name].append(test)
        ids.append(test.id())
    duplicate_ids = [name for name, count in Counter(ids).items() if count != 1]
    if duplicate_ids:
        raise RuntimeError(f"Duplicate unittest identities: {duplicate_ids[:10]}")
    if not ids:
        raise RuntimeError("No unittest tests discovered")
    return dict(grouped)


def assign(
    groups: dict[str, list[unittest.TestCase]], shard_count: int
) -> tuple[list[list[str]], list[float]]:
    if shard_count < 1 or shard_count > len(groups):
        raise ValueError(f"Invalid shard count {shard_count}: {len(groups)} modules")
    doc = json.loads(TIMINGS.read_text(encoding="utf-8"))
    weights = doc["modules"]
    # New test modules are included automatically, with a modest estimate.
    def predicted(module: str) -> float:
        return max(0.2, float(weights.get(module, 0.4 + 0.15 * len(groups[module]))))

    # Longest processing time first: stable sorting and stable tie breaking.
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    loads = [0.0] * shard_count
    for module in sorted(groups, key=lambda m: (-predicted(m), m)):
        dest = min(
            range(shard_count),
            key=lambda n: (loads[n], sum(len(groups[m]) for m in shards[n]), n),
        )
        shards[dest].append(module)
        loads[dest] += predicted(module)

    assigned = [m for shard in shards for m in shard]
    if len(assigned) != len(groups) or set(assigned) != set(groups):
        raise RuntimeError("CI partition dropped or duplicated test modules")
    return shards, loads


class TimingResult(unittest.TextTestResult):
    """Expose module-level timings in Actions logs to rebalance future runs."""

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self._began: dict[str, float] = {}
        self.module_seconds: dict[str, float] = defaultdict(float)

    def startTest(self, test):
        self._began[test.id()] = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        began = self._began.pop(test.id(), None)
        if began is not None:
            self.module_seconds[test.__class__.__module__.split(".")[-1]] += (
                time.monotonic() - began
            )
        super().stopTest(test)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=int, default=6)
    parser.add_argument("--shard", type=int, default=None, help="Zero-based shard index")
    parser.add_argument("--plan", action="store_true", help="Verify and print all shards")
    args = parser.parse_args()
    if not args.plan and args.shard is None:
        parser.error("--shard is required unless --plan is used")

    groups = discover()
    shards, loads = assign(groups, args.shards)
    total = sum(map(len, groups.values()))
    print(f"Full unittest coverage: {total} test cases in {len(groups)} modules", flush=True)
    for i, modules in enumerate(shards):
        count = sum(len(groups[name]) for name in modules)
        print(
            f"  shard {i}/{args.shards}: {count} tests, {len(modules)} modules, "
            f"estimated {loads[i]:.1f}s",
            flush=True,
        )
    if args.plan:
        return 0
    if not 0 <= args.shard < args.shards:
        parser.error(f"Expected --shard in [0,{args.shards - 1}]")

    selected = shards[args.shard]
    tests = unittest.TestSuite(
        case for module in sorted(selected) for case in groups[module]
    )
    print(
        f"Running shard {args.shard}: {tests.countTestCases()} tests from "
        + ", ".join(sorted(selected)),
        flush=True,
    )
    result = unittest.TextTestRunner(
        verbosity=2, resultclass=TimingResult,
    ).run(tests)
    for name, seconds in sorted(
        result.module_seconds.items(), key=lambda x: (-x[1], x[0])
    ):
        print(f"CI_MODULE_SECONDS {name} {seconds:.3f}", flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"CI shard setup failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
