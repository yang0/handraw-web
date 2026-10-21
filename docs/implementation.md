# Implementation contract

The approved scope is a private Web repository, safe commit-based deployment, a Discourse-mounted portal, independent credit ledger and protected downloads, and an opt-in portable personal-library client.

Rollout uses staff-only write access until the owner enrolls the 10–20 pilot creators. No invitations are sent automatically. Public discovery remains available. Runtime records and resource bundles are excluded from Git.

## Fixed defaults

- Feed: 50% quality, 30% exploration, 20% editorial, with type diversity and author caps.
- Exploration: 30 unique qualified impressions, extended to 100 after 2 detail visitors or 1 collection.
- Credits: welcome 10; validated contribution 3 (max 3/day); editorial 20; verified free reusable definition 30 (editorial/reuse award takes the larger total).
- Unlock: author 80%, platform retirement 20%; proceeds held 7 days; permanent entitlement including updates.
- Price: explicit opt-in, starts at 10, range 5–30, step 5, weekly decisions using the preceding 7 days.
- No recharge, withdrawal, or arbitrary credit transfers.
- Favorites are free bookmarks. Entitlements are separate. Only explicitly requested sync downloads full resources.

## Existing deployment

Discourse at `/home/yang0/projectHome/discourse`, supervised web on port 3000 and Sidekiq. Static resources at `/home/yang0/projectHome/handraw-static`; existing public symlinks are preserved. The portal mounts at `/studio` to avoid collision with existing `/handraw` static resources.
