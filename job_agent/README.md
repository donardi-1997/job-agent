# Job Agent — Computrabajo

Personal, local-first job discovery and auto-application app built on top of `browser-use` 0.13.10.

This project is intentionally optimized for one user and one local browser profile. It is not designed as a multi-user SaaS: **Mi perfil** is the source of truth for search, scoring and application answers.

## What works now

1. Run the dashboard locally on `127.0.0.1`.
2. Configure one editable personal candidate profile directly from the dashboard.
3. Persist roles, skills, locations, experience, salary, availability, language level and frequent answers in local SQLite.
4. Start real Browser Use searches on `co.computrabajo.com`.
5. Extract, deduplicate and score vacancies against the local profile.
6. Review each vacancy with strengths, gaps, score reasons and description.
7. Save or discard vacancies without losing that decision on later searches.
8. Submit an individual application automatically when required answers can be supported by stored data.
9. Save every answer used, submission result and confirmation evidence.
10. Run a personalized multi-query autopilot across all target roles from **Mi perfil**.
11. Deduplicate vacancies across different role searches before selecting applications.
12. Apply to the highest-scoring new vacancies first, subject to per-run and daily limits.
13. Skip vacancies already marked `applied` or `ignored`.
14. Keep batch history and application-attempt history in SQLite.
15. Keep one persistent browser profile under `data/browser-profile`.

## Local setup

Use `uv` and Python 3.12 when possible.

```powershell
uv sync
```

Create a local `.env` file with the Browser Use API key:

```env
BROWSER_USE_API_KEY=your_key_here
```

Candidate and application data is configured from **Mi perfil**. The profile, answers, SQLite database and browser state remain under the gitignored `data/` directory.

Start the application:

```powershell
uv run python run_job_agent.py
```

The dashboard opens automatically at:

```text
http://127.0.0.1:8765
```

## Personal profile as source of truth

`target_roles` controls automatic discovery. If the profile contains, for example:

```text
Python Developer
Backend Developer
AWS Developer
AI Engineer
```

one batch can search all of them automatically. A batch request may also include one optional extra keyword for experimentation without modifying the saved profile.

The app deliberately does not create users, organizations, teams or shared profiles. The local SQLite profile and the persistent local Chromium session belong to the single owner of the app.

## Automatic application mode

Open a vacancy with **Revisar** and click **Postular automáticamente**. Browser Use opens the vacancy with the persistent local browser profile, navigates the application flow, fills supported answers, submits the application and verifies the confirmation state.

Every encountered question and answer is stored. `submitted=true` is recorded only when Browser Use reports positive evidence that Computrabajo accepted the application. Successful submissions update the vacancy to `applied`.

The agent may use only facts supplied by the local profile, saved answers or unambiguous page context. It must not invent personal information, qualifications, employment history, legal declarations or salary facts.

## Personalized multi-query autopilot

The **Buscar en todos mis cargos y postular** panel combines discovery and application into one run.

The runner:

1. Loads `target_roles` from **Mi perfil**.
2. Adds the optional one-off search term, if supplied.
3. Deduplicates equivalent search terms case-insensitively.
4. Caps the number of role searches to avoid accidental runaway execution.
5. Treats `max_results` as one global discovery budget, not a multiplier per role.
6. Distributes that budget across the configured role searches.
7. Reuses unused budget when an earlier search returns fewer vacancies than requested.
8. Deduplicates discovered vacancies by canonical URL across every search term.
9. Scores the combined unique set against the personal profile.
10. Excludes jobs already marked `applied` or `ignored`.
11. Sorts eligible jobs by score and recency.
12. Applies sequentially to the best jobs until the run quota or daily limit is reached.

Example: with 5 target roles and `max_results=30`, Job Agent reviews up to roughly 30 unique vacancies in total, not 150. This keeps Browser Use usage and application volume predictable.

The batch panel configures:

- optional extra keyword;
- location;
- total discovery budget (1–50);
- minimum compatibility score;
- maximum applications for that run (1–25);
- daily confirmed-submission limit (1–50).

The daily limit is based on successful application attempts recorded for the local calendar day. Batch history stores the combined searched roles plus found, eligible, attempted, submitted, blocked/error counts and final state.

If CAPTCHA, 2FA, bot detection or another access-control challenge blocks an application, Job Agent does not bypass it. The batch stops on a detected access-control block rather than repeatedly triggering the same challenge.

## Browser concurrency

Discovery, individual applications and batch auto-apply share the same persistent Chromium profile. The dashboard serializes these operations so only one browser workflow owns the profile at a time.

## Dashboard API

- `POST /api/search` — starts a one-off discovery search.
- `GET /api/search/status` — returns discovery status.
- `POST /api/batch` — starts personal multi-query discovery + autonomous applications.
- `GET /api/batch/status` — returns live batch progress, including current role search.
- `GET /api/batch/history` — returns persisted batch history.
- `GET /api/jobs` — returns locally stored vacancies.
- `GET /api/jobs/{id}` — returns full vacancy detail.
- `POST /api/jobs/{id}/status` — changes a review state.
- `POST /api/jobs/{id}/prepare` — starts an individual automatic application.
- `GET /api/jobs/{id}/draft` — loads the latest stored answers/result.
- `POST /api/jobs/{id}/draft` — edits locally stored answers.
- `GET /api/jobs/{id}/attempts` — returns application-attempt history.
- `GET /api/prepare/status` — returns individual-application status.
- `GET /api/stats` — returns dashboard KPIs.
- `GET /api/profile` — loads the personal candidate profile.
- `POST /api/profile` — validates and saves the personal candidate profile.

## Safety constraints

- no invented personal facts;
- no CAPTCHA, 2FA, anti-bot or access-control bypass;
- no unrelated profile/account modification;
- duplicate applications are skipped when local state already says `applied`;
- success is recorded only when there is positive submission evidence.

## Decision bands

- `< min_score`: ignore
- `min_score–74`: save
- `75–prepare_application_score-1`: recommend
- `>= prepare_application_score`: auto-apply candidate

## Development branch

All current Job Agent work lives on `develop/computrabajo-agent`. Upstream-derived Browser Use code remains isolated from application-specific code where practical so future upstream updates remain manageable.
