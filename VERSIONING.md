# Versioning Guide

This file is the project reference for release versioning, deployment versioning, and future version rules.

## Current Baseline

- `v2.0.0`
  Status: deployed
  Environment: `Pre-prod`
  Meaning: current Docker app running on the server before the recent emergency-genset follow-up changes.

- `v2.1.0`
  Status: unreleased
  Environment: local repository / next deployment target
  Meaning: current codebase after the emergency-genset inventory, fallback, booking UI, and billing UI follow-up work.

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
  Example: `3.0.0`

## Source Of Truth

For every release, keep these in sync:

- [config.py](/home/aatish/app/genset/config.py) -> `APP_VERSION`
- [pyproject.toml](/home/aatish/app/genset/pyproject.toml) -> `[project].version`
- [VERSIONING.md](/home/aatish/app/genset/VERSIONING.md) -> release log below
- [CHANGELOG.md](/home/aatish/app/genset/CHANGELOG.md) -> user-facing change summary

## Release Log

| Version | Status | Environment | Notes |
| --- | --- | --- | --- |
| `2.0.0` | Deployed | Pre-prod | Baseline Docker deployment on server |
| `2.1.0` | Unreleased | Repo HEAD | Emergency genset inventory split, retailer out-of-stock fallback flow, emergency red styling, billing emergency highlighting |

## Release Rules

1. Never reuse a version number for a different build or image.
2. Pre-prod and Prod may share the same version only if they use the exact same artifact/image.
3. Every deployment should record:
   - version
   - git commit SHA
   - deployment date
   - environment
4. Unreleased work should stay on the next intended version until it is tagged and deployed.
5. Hotfixes from a deployed release should increment `PATCH`.
   Example: `2.0.0` -> `2.0.1`
6. New feature work should increment `MINOR` unless it introduces breaking change.
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
- Treat the current repository state as `v2.1.0`.
- The next Pre-prod deployment of this repo should therefore be released as `v2.1.0`.

## Future Improvement

A later cleanup can reduce duplication by deriving the runtime app version from package metadata so the version only needs to be maintained in one place.
