# #132 · Phase19: idempotent text setter and contiguous three-move trace

Baseline: Phase18 studio2@751449db5e560a565d54df5ac063e688ddd5728b. The earlier A-B-A-B-A benchmark verified that the two project-save buttons are the text-writing sources. On 1× CPU, A had 3/3 large layout events (max=9185) and B had 0/2; on emulated 4×, neither A nor B captured a large event in the individual short windows. Suppressing all setters changed visual behavior. No production optimization was authorized.

## Test-only experiment

The new browser-only hook intercepts the native Node.textContent setter only for the two pre-existing project-save buttons and **only when the desired text already equals the current text**. Actual changed labels always call the original native setter; test instrumentation is restored after every round. No production JS/CSS is patched.

Both 1× and emulated 4× CPU modes execute A=observe, B=skip-identical, A, B, A. Each round uses one real pointerdown and exactly three explicitly untrusted synthetic pointermove events in a single continuous Chrome Trace (instead of separate brief move windows). The existing 300 true nodes / 150 SVG connections / 120 independently decoded WebPs, node coordinates, Graph, Undo and media invariants are mandatory. Only the redacted artifacts/studio-111-phase19/summary.json is uploaded; no raw Chrome Trace, user text, selectors, IDs, media, or paid provider data leave the browser.

## Decision contract

For each CPU, measure whether both buttons actually received writes, how many were identical, how many were skipped, HTML childList counts and >=8000 UpdateLayoutTree events. A synthetic controlled signal is valid only if **all 3 control rounds** reproduce a large event, **both experimental rounds** show none, and all text-skipping operations are proven identical. This is stronger than Phase18's complete suppress mode, but is still not a production-grade speedup.

The tool outputs decision=NO-GO, productionChangeAuthorized=false, rootCauseUniquelyProven=false, productionVisualEquivalenceIndependentlyProven=false, physicalLowEndDeviceTested=false. A separate real low-end physical-device test, normal UI visual and accessibility regression, independent production-code review, and all 17 real-world D-level evidence gates are still prerequisites.

FF-018 / FF-019 / FG-025 website human approval, real official DB export and Web/Skill strict parity, real provider billing, physical PG17 restore, R2/S3/CDN, multi-instance Redis, device performance, and independent dual signoff are not substituted by this C-level experiment. Issue #132 stays Open; PR #131 Draft; main unchanged; production NO-GO.
