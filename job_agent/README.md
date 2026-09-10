# Job Agent — Computrabajo

Local-first job discovery application built on top of `browser-use` 0.13.10.

## What works now

1. Run the dashboard locally on `127.0.0.1`.
2. Enter a job title/keyword, location, and result limit.
3. Start a real Browser Use search on `co.computrabajo.com`.
4. Watch search state from the dashboard while the browser works in the background.
5. Extract validated job records with title, company, location, description, and canonical URL.
6. Deduplicate vacancies by canonical URL.
7. Score each vacancy with the deterministic matcher.
8. Persist results in local SQLite and render them in the dashboard.
9. Keep a persistent local browser profile under `data/browser-profile`.
10. Do **not** submit applications automatically.

## Local setup

Use `uv` and Python 3.12 when possible.

```powershell
uv sync
```

Create a local `.env` file and add a Browser Use API key:

```env
BROWSER_USE_API_KEY=your_key_here
```

Optional matching configuration can stay private in the same `.env` file:

```env
JOB_AGENT_TARGET_ROLES=Python Developer,Backend Developer,AWS Developer
JOB_AGENT_SKILLS=Python,FastAPI,AWS,SQL,Docker
JOB_AGENT_LOCATIONS=Colombia,Bogotá
```

These values are never required to be committed. `.env` and the complete `data/` directory are gitignored.

Start the application:

```powershell
uv run python run_job_agent.py
```

The dashboard opens automatically at:

```text
http://127.0.0.1:8765
```

## Browser behavior

The collector uses a visible local Browser Use browser with a persistent dedicated profile in `data/browser-profile`. On the first authenticated workflow you can sign in manually; subsequent runs can reuse the local session state.

The search agent is restricted to `co.computrabajo.com` and receives explicit read-only instructions. It may inspect vacancy pages, but it must never apply, submit a form, change account data, send messages, or attempt to bypass CAPTCHA, 2FA, bot detection, or access controls.

## Search API used by the dashboard

- `POST /api/search` — starts one background Computrabajo search.
- `GET /api/search/status` — returns `idle`, `running`, `completed`, or `error`.
- `GET /api/jobs` — returns locally stored vacancies.
- `GET /api/stats` — returns dashboard KPIs.

Only one discovery run can execute at a time, preventing accidental duplicate browser sessions.

## Safety defaults

- `auto_fill = True`
- `auto_submit = False`
- CAPTCHA or anti-bot challenges are handed back to the user.
- No attempt is made to bypass access controls or anti-abuse protections.
- Application history must be persisted before automated submissions are considered.

## Decision bands

- `< 60`: ignore
- `60-74`: save
- `75-84`: recommend
- `>= 85`: prepare application

These values remain configurable in `job_agent.config.SearchPreferences`.

## Next milestones

- Editable candidate profile from the dashboard instead of `.env`.
- Vacancy detail drawer with match reasons and skill gaps.
- Search history and per-run metrics.
- Assisted application flow with a mandatory final human review.
- Application pipeline states and response/interview analytics.

## Development branch

All current Job Agent work lives on `develop/computrabajo-agent`. Keep upstream-derived Browser Use code isolated from application-specific code where practical so future upstream updates remain manageable.
