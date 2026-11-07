# Handraw Web

Private application extensions for the existing Handraw Discourse installation.

- Never commit credentials, `/web`, uploads, database dumps, private resource bundles, or user libraries.
- Keep the public Skill, static distribution, and Discourse core repositories separate.
- Back up existing server changes before deployment. Never force-reset a dirty checkout.
- Server pulls must be fast-forward-only; production deploys use an exact commit.
- Database changes are additive. A code rollback must never roll back database migrations.
- Run plugin integration tests in an isolated PostgreSQL database, never the production database.
- Implementation delegation, when explicitly authorized, uses `luna_worker`; `explorer` is read-only.

## Design

Visual thesis: warm paper, ink typography, vermilion actions, and generous image-led editorial layouts.
Content plan: discover community work, browse reusable resources, share, and manage personal collections.
Interaction thesis: a short entrance reveal, restrained image hover, and immediate explicit saved/unlocked feedback; honor reduced motion.

## Ownership

`plugin/` contains the Discourse extension; `ops/` handles backup and deployment;
`skill-addon/` contains the portable personal-library integration; `tests/` contains local checks.

## Product review workflow

The primary reviewer owns product decisions, priorities, and acceptance. For the
configured DeepSeek source-review and proposed-patch workflow, read
`docs/deepseek-workflow.md` and use `ops/deepseek_task.py`. The reviewer inspects
and applies accepted patches; this API helper does not execute shell commands or
edit product files. Keep its credentials and task outputs under ignored `.local/`.
Built-in implementation worker delegation still uses `luna_worker`.

## Issue-first development protocol

Before changing product code, tests, configuration, or docs for a development task:
1. Create or identify a GitHub Issue describing the bug/request, intended behavior, and acceptance criteria. If a request is new or an existing Issue is too broad, create a focused Issue and cross-link it.
2. Only after the Issue exists, implement the change (normally on `main` for this repository, unless the maintainer requests a branch).
3. Reference the Issue number in commit messages and update the Issue with commits, tests actually run, and outstanding manual/browser verification.
4. Never mark an Issue completed based only on a source-text assertion or a successful commit. Verify actual interaction/layout at representative desktop, tablet, and mobile widths where applicable; disclose any verification that could not be performed.
