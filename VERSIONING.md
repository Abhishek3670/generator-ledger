# Versioning Guide

This file defines how version numbers should be managed for this project and records the inferred release timeline reconstructed from git history.

## Historical Note

Formal versioning was added after the project was already under active development.

Because the repository has no historical git tags, versions before formal version tracking are inferred from commit clusters and milestone-sized change groups.
These inferred versions are suitable for documentation and future reference, but they are not exact proof of historical Docker image tags or server deployments.

## Current Version Position

- `v2.0.0`
  Status: inferred deployed baseline
  Environment: `Pre-prod`
  Meaning: the Docker app currently running on the server before the emergency-genset follow-up work.

- `v2.2.0`
  Status: latest tagged local release
  Environment: local git tag / most recent release baseline
  Meaning: emergency genset inventory flow plus CLI capacity add flow and exported data tracking cleanup.

- `v3.0.0`
  Status: documented local release baseline / previous deployment target
  Environment: local repository history / previous `Pre-prod` target
  Meaning: release-oriented Docker Compose cutovers now require an explicit image tag and use versioned deployment examples.

- `v3.1.0`
  Status: documented local release baseline / previous deployment target
  Environment: local repository history / previous `Pre-prod` target
  Meaning: Permanent Genset inventory, rental-vendor assignment on generators, update flow for existing gensets, and booking exclusion for permanently parked stock.

- `v3.1.1`
  Status: documented local release baseline / previous deployment target
  Environment: local repository / previous deployment target
  Meaning: runtime file logging now writes to a dedicated `logs/` folder instead of the repository root.

- `v4.0.0`
  Status: current repository version / next deployment target
  Environment: local repository / next deployment target
  Meaning: PostgreSQL-only runtime, Alembic schema management, and SQLite-to-PostgreSQL cutover tooling.

## Inferred Release Timeline

| Version | Status | Approx. Commit Range | Environment | Notes |
| --- | --- | --- | --- | --- |
| `1.0.0` | Inferred historical milestone | `adf0168` -> `233a4ac` | Historical | Initial booking ledger foundation, dashboard redesign, booking calendar, history log, generator management |
| `1.1.0` | Inferred historical milestone | `ec8ab72` -> `c36064a` | Historical | Hybrid auth, vendor booking table on create-booking, admin settings, grouped booking detail improvements |
| `1.2.0` | Inferred historical milestone | `bd8d4ba` -> `58e918b` | Historical | Advanced booking filters, billing preview, print layout improvements, vendor paid adjustments |
| `1.3.0` | Inferred historical milestone | `51455a5` -> `fdc30fb` | Historical | Monitor tab, history redesign, vendor actions, permission matrix, billing permission tightening |
| `2.0.0` | Inferred deployed baseline | `744ad2e` -> `ab14db4` | `Pre-prod` | Repository refactor, security hardening, env support, permissions expansion, session Docker/LAN handling, rental vendors |
| `2.1.0` | Inferred local milestone | `7823c8f` -> `6f9bfe9` | Local repository history | Emergency genset inventory and fallback flow, emergency billing styling, versioning and changelog docs |
| `2.2.0` | Tagged local release | `18076c9` -> `de113ca` | Local repo / previous `Pre-prod` target | CLI generator-capacity add option, exported data untracked from git, and release-note updates |
| `3.0.0` | Documented local release baseline | `7c91444` release commit | Local repo / previous `Pre-prod` target | Explicit `APP_IMAGE_TAG` requirement in Compose plus versioned Docker release examples |
| `3.1.0` | Documented local release baseline | `b3a24eb` release commit | Local repo / previous `Pre-prod` target | Permanent Genset inventory, rental-vendor assignment on generators, generator update flow, and booking exclusion for permanently parked stock |
| `3.1.1` | Documented local release baseline | Post-`98a413c` working tree | Local repo / previous `Pre-prod` target | Runtime file logging now writes to a dedicated `logs/` folder instead of the repository root |
| `4.0.0` | Current repo version | PostgreSQL cutover working tree | Local repo / next `Pre-prod` release | PostgreSQL-only runtime, Alembic schema management, split DB env config, and SQLite-to-PostgreSQL migration tooling |

## Note On `2.0.1`

No explicit `2.0.1` milestone is recorded in the inferred timeline.

Reason:

- There is no clear tag or deployment marker proving a separate patch-only release boundary after the inferred `2.0.0` baseline.
- The next clearly identifiable milestone in git is feature-sized and fits better as `2.1.0`.

If future deployment records show there really was a separate `2.0.1` image or server rollout, this file and [CHANGELOG.md](/home/aatish/app/genset/CHANGELOG.md) should be updated to reflect that evidence.

## Versioning Scheme

Use Semantic Versioning: `MAJOR.MINOR.PATCH`

- `PATCH`
  Use for bug fixes, styling fixes, validation fixes, and small safe behavior corrections.
  Example: `2.1.1`

- `MINOR`
  Use for backward-compatible features, new screens, new API fields, new operational flows, and schema additions that do not break existing use.
  Example: `2.2.0`

- `MAJOR`
  Use for breaking API behavior, incompatible schema changes, deployment/process changes, or workflow changes that require coordinated rollout.
  Example: `4.0.0`

## Source Of Truth

For every release, keep these in sync:

- [config.py](/home/aatish/app/genset/config.py) -> `APP_VERSION`
- [pyproject.toml](/home/aatish/app/genset/pyproject.toml) -> `[project].version`
- [VERSIONING.md](/home/aatish/app/genset/VERSIONING.md) -> version rules and release timeline
- [CHANGELOG.md](/home/aatish/app/genset/CHANGELOG.md) -> user-facing change summary

## Release Rules

1. Never reuse a version number for a different build or image.
2. `Pre-prod` and `Prod` may share the same version only if they use the exact same artifact or image.
3. Every deployment should record:
   - version
   - git commit SHA
   - deployment date
   - environment
4. Unreleased work should stay on the next intended version until it is tagged and deployed.
5. Hotfixes from a deployed release should increment `PATCH`.
   Example: `2.0.0` -> `2.0.1`
6. New feature work should increment `MINOR` unless it introduces a breaking change.
7. Breaking rollout should increment `MAJOR`.

## Release Checklist

Before a release:

1. Decide the next version.
2. Update [config.py](/home/aatish/app/genset/config.py).
3. Update [pyproject.toml](/home/aatish/app/genset/pyproject.toml).
4. Add or update the entry in [VERSIONING.md](/home/aatish/app/genset/VERSIONING.md).
5. Add or update the matching section in [CHANGELOG.md](/home/aatish/app/genset/CHANGELOG.md).
6. Commit the version change.
7. Create a git tag:
   - `git tag vX.Y.Z`
8. Build the Docker image with the same version tag.
9. Deploy to `Pre-prod`.
10. After verification, promote the same version to `Prod` if no new code is added.

## Practical Rule For This Project

Starting point from now on:

- Treat the currently running server Docker app as `v2.0.0`.
- Treat the most recent tagged local release as `v2.2.0`.
- Treat the current repository state as `v4.0.0`.
- Keep future release notes in [CHANGELOG.md](/home/aatish/app/genset/CHANGELOG.md).
- Only add a retrospective version entry when you have either:
  - a clear commit milestone, or
  - deployment evidence from Docker/image/server records.

## Future Improvement

A later cleanup can reduce duplication by deriving the runtime app version from package metadata so the version only needs to be maintained in one place.
