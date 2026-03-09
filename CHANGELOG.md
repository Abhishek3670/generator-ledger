# Changelog

All notable changes to this project should be recorded in this file.

This changelog starts from the point where versioning was formalized. Older history before `v2.0.0` is not reconstructed in detail here.

The format is intentionally simple and release-focused.

## [Unreleased]

### Added

- Emergency genset inventory support as a separate operational stock group.
- Emergency genset table on the generators page after the retailer genset table.
- Retailer out-of-stock fallback flow for create-booking with emergency suggestions.
- Emergency inventory metadata in booking and billing responses.
- Versioning policy in [VERSIONING.md](/home/aatish/app/genset/VERSIONING.md).

### Changed

- Renamed the original generators table/section to `Retailer Genset`.
- Added responsive vertical scroll behavior to the generator inventory tables.
- Emergency-booked gensets now render in danger-red text across booking and billing views.
- Billing page now highlights emergency gensets in red.

### Fixed

- New generator creation validation now imports and recognizes maintenance status correctly.

## [2.0.0]

### Notes

- Baseline `Pre-prod` Docker deployment currently running on the server.
- This is the deployment state before the emergency-genset follow-up work contained in the current repository.

## Rules For Future Updates

When a release is prepared:

1. Update the `Unreleased` section during development.
2. At release time, rename `Unreleased` content into a new version section.
3. Add the release date if you want stricter release tracking.
4. Keep the version number aligned with [VERSIONING.md](/home/aatish/app/genset/VERSIONING.md), [config.py](/home/aatish/app/genset/config.py), and [pyproject.toml](/home/aatish/app/genset/pyproject.toml).
