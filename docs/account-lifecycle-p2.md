# Account lifecycle P2 — behavior and release checklist

This document describes shipped account lifecycle behavior and the remaining external dependency for social login.

## Account settings

- `?view=account&section=profile`: avatar selection, crop, display name and biography.
- `?view=account&section=email`: current email status, verification, confirmed change.
- `?view=account&section=security`: password and active browser sessions.
- `?view=account&section=devices`: existing Skill and terminal grants.
- `?view=account&section=privacy`: basic JSON export and account closure.

Legacy `?view=profile&ptab=account` links redirect to the account center.

## Nickname policy

Usernames are stable identifiers. Public display names may be changed once every 30 days.
The server enforces the cooldown using `users.nickname_changed_at`, migration 088.
Existing accounts begin with zero and are eligible for their first rename; future renames
refresh the timestamp. Public authored works, topics, and community assets update their
author display-name snapshot. Keep any external cached display labels consistent.

## Account closure — not full erasure

`POST /api/account/close` requires an authenticated account, exact username confirmation,
and the current password. It closes the account, deletes browser sessions, revokes
personal API tokens, and denies issued device grants. Historical public works, comments,
community moderation records, wallet balances and legally relevant records are **not**
deleted automatically. The UI must never present this as irreversible deletion of all
user data. A separately reviewed privacy-erasure workflow is necessary for deletion
requests, historical authorship, financial records and legal retention.

`GET /api/account/export` exports basic profile information plus authored work/topic
indexes and wallet balance. It intentionally excludes passwords, hashes, API keys and
raw credentials. It is not an exhaustive personal-data portability archive.

## Auth metrics

Migration 088 adds `auth_funnel_events`. Public registration and login endpoints
record attempts and successes. Events contain no email, password, client IP or session
token. The success rows contain a user ID solely to distinguish successful accounts.
Example daily reporting:

```sql
SELECT date(created_at, 'unixepoch') AS day, event_name, count(*) AS events
FROM auth_funnel_events
WHERE created_at >= strftime('%s', 'now', '-30 days')
GROUP BY day, event_name ORDER BY day DESC, event_name;
```

These are request-level counts, not a fully deduplicated visitor conversion funnel.
Do not present attempts divided by successes as a unique-user conversion rate.
Define retention and archival rules before operating at large scale.

## Social login decision

Social login is **not activated**. There are no configured OAuth app credentials, state
and PKCE handling, verified-email account linking, provider account conflict policy,
or end-to-end callback tests in this codebase. Do not ship an inert Google/GitHub login
button or auto-link by unverified email. Before enabling a provider, implement and test:
state/CSRF protection, strict redirect allowlist, server-side token exchange, verified
email checks, explicit account-linking for existing users, callback replay prevention,
and a password-recovery alternative. Protect against provider email changes.

## Deployment verification

1. Deploy migration 088 additively. Never roll it back by deleting columns.
2. Verify avatar selection gives immediate status and shows a crop after image load.
3. Verify nickname changes once and is rejected before 30 days; legacy users can rename.
4. Verify email, password and device controls appear in their correct independent panels.
5. Verify invalid closure confirmation/password changes nothing.
6. Verify successful closure revokes browser and API token access; data export omits secrets.
7. Confirm the relevant CI jobs are green and test the flow in a real browser before production deploy.
