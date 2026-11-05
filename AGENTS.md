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
