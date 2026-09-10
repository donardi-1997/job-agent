# Job Agent — Computrabajo

Local-first job discovery application built on top of `browser-use` 0.13.10.

## What works now

1. Run the dashboard locally on `127.0.0.1`.
2. Configure an editable candidate profile directly from the dashboard.
3. Persist roles, skills, locations, experience and scoring thresholds in local SQLite.
4. Enter a job title/keyword, location, and result limit.
5. Start a real Browser Use search on `co.computrabajo.com`.
6. Watch search state from the dashboard while the browser works in the background.
7. Extract validated job records with title, company, location, description, and canonical URL.
8. Deduplicate vacancies by canonical URL.
9. Score each vacancy against the locally saved profile.
10. Render compatibility bands and KPIs in the dashboard.
11. Keep a persistent browser profile under `data/browser-profile`.
12. Do **not** submit applications automatically.

## Local setup

Use `uv` and Python 3.12 when possible.

```powershell
uv sync
```

Create a local `.env` file with the Browser Use API key:

```env
BROWSER_USE_API_KEY=your_key_here
```

Candidate matching configuration no longer needs to live in `.env`; edit it from **Mi perfil** in the dashboard. The profile and browser state remain under the gitignored `data/` directory.

Start the application:

```powershell
uv run python run_job_agent.py
```

The dashboard opens automatically at:

```text
http://127.0.0.1:8765
```

## Local profile

`GET /api/profile` loads the current profile and `POST /api/profile` validates and persists it in SQLite. The profile controls:

- target roles;
- skills;
- years of experience;
- preferred locations;
- remote preference;
- minimum score;
- score required to prepare an application;
- excluded terms.

The profile is the source of truth for new vacancy scoring. Duplicate list values are normalized before persistence and invalid scoring ranges are rejected.

## Browser behavior

The collector uses a visible local Browser Use browser with a persistent dedicated profile in `data/browser-profile`. On an authenticated workflow you can sign in manually and retain the local session state.

The search agent is restricted to `co.computrabajo.com` and receives explicit read-only instructions. It may inspect vacancy pages, but it must never apply, submit a form, change account data, send messages, or attempt to bypass CAPTCHA, 2FA, bot detection, or access controls.

## Dashboard API

- `POST /api/search` — starts one background Computrabajo search.
- `GET /api/search/status` — returns `idle`, `running`, `completed`, or `error`.
- `GET /api/jobs` — returns locally stored vacancies.
- `GET /api/stats` — returns dashboard KPIs.
- `GET /api/profile` — loads the locally persisted candidate profile.
- `POST /api/profile` — validates and saves the candidate profile.

Only one discovery run can execute at a time, preventing accidental duplicate browser sessions.

## Safety defaults

- `auto_fill = True`
- `auto_submit = False`
- CAPTCHA or anti-bot challenges are handed back to the user.
- No attempt is made to bypass access controls or anti-abuse protections.
- Application history must be persisted before automated submissions are considered.

## Decision bands

- `< min_score`: ignore
- `min_score–74`: save
- `75–prepare_application_score-1`: recommend
- `>= prepare_application_score`: prepare application

## Next milestones

- Vacancy detail drawer with score reasons and skill gaps.
- Search history and per-run metrics.
- Ability to save/archive individual jobs from the dashboard.
- Assisted application flow with a mandatory final human review.
- Application pipeline states and response/interview analytics.

## Development branch

All current Job Agent work lives on `develop/computrabajo-agent`. Keep upstream-derived Browser Use code isolated from application-specific code where practical so future upstream updates remain manageable.
