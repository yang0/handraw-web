# Studio 2.0 · Runtime authority & recovery (#119)

Status: implementation in `studio2-issue119-ci`, anchored at `4fecf6af3dc6`. Parent #104, contracts #102, media/work invariant #84, CI #112. This is an **execution reliability slice**, not the DAG dispatcher (#120).

## Identity / write authority

| Domain | Durable identity | Owner | Invariant |
| --- | --- | --- | --- |
| Logical run | `generation_runs.id` from authenticated `ensure_run(user_id,source,external_run_id)` | V3 DB | One run / at most one public work, fixed `expected_count` |
| Output slot | `(generation_items.run_id,position)` where Web position=`slotIndex*1000+imageIndex` | V3 DB | Confirmed success has owner-matched `mediaId` and cannot be overwritten by another attempt |
| Attempt | `studio_generations.id`, user-scoped `request_id` | Existing gateway/credits ledger | Replay the same request ID reuses original charge; an explicitly requested failed-slot retry uses **new** ID/ledger entry |
| Work/media | `works.run_id`, `work_media`, `media_assets` | V3 DB | At most one Work per Run; re-projection uses all canonical successful RunItems in slot order |
| Frozen input | `studio_generations.system_append_json.runtimeSnapshot` & `generation_runs.original_request` | Gateway ledger / Run | Capture `batchId`, `slotId`, `slotIndex`, `position`, `expectedCount`, `idempotencyKey`, optionally `planRevision`; no protected prompt exposed via Run GET |

The frontend compiles/freeze the current Graph/Plan before submission. Each attempt sends `requestId == clientRequestId == idempotencyKey` and safe slot identifiers. The server rejects conflicting aliases, different `slotId` on a retry, new attempts while another is queued/running/unknown, and new attempts for already-successful slots **inside the same transaction as wallet reservation**. A user-requested retry of a failed/cancelled slot must explicitly set `retryFailed`/`retryCancelled`; it is **new billing**, not automatic replay. Previously refunded attempts and failures remain available for audit.

## State mapping: persisted / client intent / view

| Layer | Valid states | Source / meaning |
| --- | --- | --- |
| **Persisted Run** | `pending`, `uploading`, `running`, `partial`, `success`, `failed`, `cancelled` | V3 CHECK; derived from output slots in `refresh_run_status` |
| **Persisted Item** | `pending`, `generating`, `success`, `failed`, `cancelled` | V3 CHECK; success implies actual `media_id` |
| **Gateway ledger** | `queued`, `running`, `success`, `refunded`, `failed`, `cancelled` (plus legacy errors) | Existing attempt and reservation facts |
| **Client transient intent** | `submitting`, `cancel_requested`, `checking_remote`, `connection_lost` | Memory/UI only; no V3 database mutation |
| **View** | `pending`, `running`, `success`, `failed`, `partial`, `cancelled`, `unknown`, `cancel_requested` | Authenticated read model; does **not** expand persisted CHECK enums |

For each slot, precedence is (1) V3 confirmed success and authorized media; (2) the last accepted gateway attempt while pending/running (very old attempts become **view-only unknown**); (3) persisted Item failure/cancel; (4) pending/unsubmitted. Stale missing gateway state **never** counts as completed. A recovered Run may have persisted status `running` while its projection reports three successes, two failures, one unknown. `unknown` does not imply a refund, failure, or cancelled upstream task.

Client projects the owner-scoped `GET /api/studio/runs/{id}` response, which now extends the existing `run` and `items` with `slots[]`, `attempts[]`, `projection`, and `billing` (non-authoritative monetary summary; ledger governs). Existing consumers of `run/items` remain valid.

## Duplicate, out-of-order and cancelled callbacks

- `record_public_work` uses a conditional `generation_items` upsert, refusing to replace `status='success'` and rebuilding `work_media` from **all currently confirmed** RunItems. A partial/old callback cannot erase a completed sibling slot. PostgreSQL serializes writes via row lock on the immutable logical run. A deleted-work tombstone is still enforced.
- `generation_works` picks the **earliest** confirmed success per slot from gateway attempts, not whichever callback arrives last. Work identity and public order remain stable across replay.
- `cancel-pending` only marks positions with no gateway ledger attempt. A submitted or unconfirmed upstream task remains eligible for a later success or reconciliation. An in-browser AbortController **only** stops local waiting and future unsubmitted requests; upstream cancellation/refund cannot be promised.
- No new gateway webhook endpoint or ambiguous simulated refund policy was introduced. Existing `/api/studio/tasks?id={taskId}` performs authenticated gateway check and completes/refunds through existing transactional services.

## Refresh / server restart / network recovery

- The browser keeps the original `runId` and original request/slot keys, while the server persists the Run and gateway attempts. No refresh creates a new charge.
- `GET /api/studio/runs/{runId}` can repopulate real status from durable Run/Item plus owned attempts after a browser or service restart. `studio-core` / quick / series / Canvas share the same **server** ordered slot projection.
- Canvas taskbar's **重新检查远端 / 解除本地忙状态** clears detached local busy flags and retrieves the Run, then polls the already-owned provider taskId for any unresolved attempts (never calls `POST /api/studio/generate`). Offline/online invalidates stale read caches; the projection stays uncertain during network loss without faking completion.

## Billing, limits, and verification

Replaying the same user-scoped request key returns its existing reservation (idempotent, no second wallet charge). Deliberately retrying a failed slot creates a new gateway request/ledger fact, potentially incurring credits. A gateway reject may refund through existing service policy, but a timeout, local cancel, or unknown remote state **does not** guarantee credits back.

Local/CI safety verification does not call a paid provider: Python unit and owner HTTP tests exercise authoritative Run+Item, cancellation, restart and simulated fail/retry; Node tests verify view state and UI intent boundaries; Playwright real Chromium checks offline/reconnect/reload and the recheck GET flow without paid POST. End-to-end reconciliation against a real external provider (including its cancellation and billing behavior) remains a **separate live gateway acceptance requirement** and is not claimed tested by these fixtures.
