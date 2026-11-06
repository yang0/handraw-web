# Account identity, avatar and recovery — current product policy

## Shipped account settings

- `?view=account&section=profile`: immutable creator nickname, editable biography and avatar.
- `?view=account&section=email`: current email status, verification and verified email change.
- `?view=account&section=security`: password change and browser sessions.
- `?view=account&section=devices`: authorized Skill and terminal clients.

Legacy links to `?view=profile&ptab=account` redirect to the account center.

## Creator nickname is immutable

The creator nickname is selected at registration. If omitted, the username is used as
the nickname. **After registration the nickname cannot be edited**, including for
legacy accounts with an earlier `nickname_locked=0` flag. Server-side profile
changes reject a different displayName with `nickname_locked`. The user may still
edit their biography. Columns `nickname_changed_at` and related migration 088
remain in the additive schema for compatibility; they do not authorize renaming.

## Avatar crop

User may upload PNG, JPEG or WebP source files up to 12 MB. Source decoding uses
`createImageBitmap` when available and FileReader/Image as a fallback. The photo
is previewed on a 320px canvas, with drag-to-pan, touch dragging, keyboard arrow
movement, zoom slider and reset-to-center. The crop is clamped to source boundaries.
The current 320px square crop is encoded as PNG and uploaded with explicit user
confirmation; the server validates and transcodes it to WebP. The server's 3 MB
limit applies to the generated crop, **not** the 12 MB source file.
Verify with real large transparent PNGs, portrait photos and square JPEG/WebP images.

## Account closure and deletion

**Account closure, self-service deletion and reactivation are disabled.** The client
must not display them; the backend does not expose `/api/account/close`,
`/api/auth/request-reactivation` or `/api/auth/confirm-reactivation`. No existing
user data is automatically erased. Additive migrations 088 and 089 may retain unused
compatibility schema; that is not permission to operate closure flows.
`GET /api/account/export` remains available to authenticated users at the API
level as a limited, credential-free basic data export. A complete export and
deletion policy require separate legal and product review.

## Registration metrics

Migration 088 adds `auth_funnel_events`, which records login and registration
attempts and successes. No password, IP address or email is stored in these events.
This is **not** a complete activation/retention funnel.

## Social login

Social login remains disabled. A provider requires OAuth configuration, PKCE/state,
strict redirect controls, verified identity, explicit linking, conflicts handling,
callback replay protection, recovery policy and end-to-end tests. Do not ship a
placeholder social login button.

## Release verification

1. Complete additive DB migrations without destructive rollback.
2. Test avatar source PNG/JPEG/WebP preview, drag movement, zoom and confirmed upload.
3. Confirm every registered nickname, including legacy unlocked rows, is immutable.
4. Confirm email verification, recovery, password change and sessions still work.
5. Confirm closure/reactivation routes are unavailable and have no UI entry points.
6. Verify account identity tests and regression guards are green, then test manually
   in production-equivalent browsers before deployment.
