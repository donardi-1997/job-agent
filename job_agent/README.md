# Job Agent — Computrabajo

This directory contains the first application-specific layer built on top of `browser-use` 0.13.10.

## Current scope

The first milestone is intentionally read-only/dry-run:

1. Open Computrabajo.
2. Search jobs using configured keywords and locations.
3. Extract normalized job records.
4. Deduplicate jobs.
5. Score each job against the candidate profile.
6. Save/recommend/prepare matching jobs.
7. Do **not** submit an application automatically.

## Safety defaults

- `auto_fill = True`
- `auto_submit = False`
- CAPTCHA or anti-bot challenges must be handed back to the user.
- No attempt should be made to bypass access controls or anti-abuse protections.
- Application history should be persisted before enabling automated submissions to avoid duplicate applications.

## Decision bands

- `< 60`: ignore
- `60-74`: save
- `75-84`: recommend
- `>= 85`: prepare application

These values are configurable in `job_agent.config.SearchPreferences`.

## Planned modules

- `computrabajo/browser.py`: Browser Use session and authenticated navigation.
- `computrabajo/search.py`: search result discovery and pagination.
- `computrabajo/extract.py`: normalized vacancy extraction.
- `storage.py`: SQLite application/search history and deduplication.
- `application.py`: form preparation and guarded submission flow.
- `cli.py`: local commands for dry-run, review, and later controlled apply mode.

## Development branch

All Job Agent work starts on `develop/computrabajo-agent`. Keep upstream-derived Browser Use code isolated from application-specific code where practical so future upstream updates remain manageable.
