"""#111 Stage 11 full real-Chromium entrypoint.

Reuse Stage 10's isolated HTTP project, 120 unique WebPs and existing
faithful node/edge/Undo assertions. This hook is confined to the QA process;
the production application has no monkeypatch or benchmark imports.
"""
from __future__ import annotations
import json
from pathlib import Path

import benchmark_studio_tree_style_111 as stage10
from ops.canvas_style_causality_browser_111 import ablation, trace_window

ROOT = Path(__file__).resolve().parent.parent


def main():
    original = stage10.trace_tree_affected
    original_cases = stage10.CASES
    applied = False

    def inspect(page, cdp, mode):
        nonlocal applied
        if mode == "baseline" and not applied:
            applied = True
            # Stage 10's CSS A/B trials used to create the real selection
            # toolbar as a side-effect. After deduplicating those trials,
            # explicitly establish selection with ONE genuine mouse drag and
            # its Undo; camera focus alone only pans, never selects a node.
            warmup = stage10.profile_drag(page, cdp, cpu_factor=1)
            assert warmup["graphUndoAndMediaStable"]
            assert page.locator("[data-float-topbar]").count() == 1, (
                "real native selection toolbar did not mount after warmup")
            same_window = trace_window(page, cdp)
            floating_overlay_window = trace_window(
                page, cdp, "floating-layer-style-contain")
            trials = [
                ablation(page, cdp, "selected-hover-guard",
                         stage10.profile_drag, stage10.metrics_for),
                ablation(page, cdp, "node-hover-rules-off",
                         stage10.profile_drag, stage10.metrics_for),
                ablation(page, cdp, "floating-toolbar-contain",
                         stage10.profile_drag, stage10.metrics_for),
                ablation(page, cdp, "floating-layer-style-contain",
                         stage10.profile_drag, stage10.metrics_for),
            ]
            assert len(trials) == 4, trials
            result = {
                "issue": 111, "phase": 11,
                "sameWindow": same_window,
                "floatingOverlayContainWindow": floating_overlay_window,
                "realMouseSelectionWarmup": True,
                "stage10PairedAblationsAreRunSeparatelyInCI": True,
                "ablationOrder": "A-B-A-B-A at normal and CDP 4x",
                "candidates": trials,
                "canPromoteWithoutFurtherReview": False,
                "productionCssOrJsChanged": False,
                "paidGatewayCalls": 0,
                "traceNodeIdResolvedToDOM": False,
                "traceRawDataSaved": False,
                "physicalLowEndDevice": False,
                "productionReleaseApproval": False,
            }
            folder = ROOT / "artifacts/studio-111-causality"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "summary.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            evidence=same_window["sameWindowChrome"]
            print("CANVAS #111 STAGE11 " + json.dumps({
                "traceAvailable": evidence.get("available"),
                "invalidationEvents": evidence.get("invalidationEvents"),
                "reasonCategories": evidence.get("reasonCategories"),
                "largeLayoutUpdates": evidence.get(
                    "updateLayoutTree", {}).get("largeEventsGE8000"),
                "maxLayoutElements": evidence.get(
                    "updateLayoutTree", {}).get("maxElementCount"),
                "overlayTraceLargeLayoutEvents": floating_overlay_window[
                    "sameWindowChrome"].get("updateLayoutTree", {}).get(
                        "largeEventsGE8000"),
                "overlayTraceMaxElements": floating_overlay_window[
                    "sameWindowChrome"].get("updateLayoutTree", {}).get(
                        "maxElementCount"),
                "mutations": evidence.get(
                    "actualDomMutations", {}).get("byTargetRole"),
                "nearLargeUpdates": evidence.get("joinNearLargeUpdateByReason"),
                "candidates": [
                    {"name": r["case"], "valid": r["valid"],
                     "furtherReview": r["productionCandidate"],
                     "gate": r.get("gate")} for r in trials
                ],
                "paid": 0,
            }, ensure_ascii=False), flush=True)
        return original(page, cdp, mode)

    # The Stage 10 A-B-A-B-A already runs as its own mandatory CI step.
    # Reuse its real HTTP fixture, decoded WebPs and DOM/Undo assertions, but
    # DO NOT rerun all four Stage 10 CSS experiments inside Stage 11.
    # Keep this override process-local and restore both symbols on exit.
    stage10.CASES = ()
    stage10.trace_tree_affected = inspect
    try:
        stage10.main()
    finally:
        stage10.trace_tree_affected = original
        stage10.CASES = original_cases
    assert applied, "stage11 attribution hook was never invoked"


if __name__ == "__main__":
    main()
