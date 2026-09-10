# Job Agent — Computrabajo

Local-first job discovery and auto-application app built on top of `browser-use` 0.13.10.

## What works now

1. Run the dashboard locally on `127.0.0.1`.
2. Configure an editable candidate profile directly from the dashboard.
3. Persist roles, skills, locations, experience, salary, availability, language level and frequent answers in local SQLite.
4. Start real Browser Use searches on `co.computrabajo.com`.
5. Extract, deduplicate and score vacancies against the local profile.
6. Review each vacancy with strengths, gaps, score reasons and description.
7. Save or discard vacancies without losing that decision on later searches.
8. Submit an individual application automatically when required answers can be supported by stored data.
9. Save every answer used, submission result and confirmation evidence.
10. Run autonomous search + auto-apply batches with a score threshold, per-run quota and daily submission limit.
11. Skip vacancies already marked `applied` or `ignored`.
12. Keep batch history and application-attempt history in SQLite.
13. Keep a persistent browser profile under `data/browser-profile`.

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

## Automatic application mode

Open a vacancy with **Revisar** and click **Postular automáticamente**. Browser Use opens the vacancy with the persistent local browser profile, navigates the application flow, fills supported answers, submits the application and verifies the confirmation state.

Every encountered question and answer is stored. `submitted=true` is recorded only when Browser Use reports positive evidence that Computrabajo accepted the application. Successful submissions update the vacancy to `applied`.

The agent may use only facts supplied by the local profile, saved answers or unambiguous page context. It must not invent personal information, qualifications, employment history, legal declarations or salary facts.

## Autonomous batch mode

The **Buscar y postular en lote** panel combines discovery and application into one run. Configure:

- keyword and location;
- maximum search results (1–50);
- minimum compatibility score;
- maximum applications for that run (1–25);
- daily confirmed-submission limit (1–50).

The runner searches first, persists/scorers results, selects only vacancies from that search meeting the threshold, excludes `applied` and `ignored`, then processes the remaining jobs sequentially. Sequential execution avoids Chromium profile conflicts.

The daily limit is based on successful application attempts recorded for the local calendar day. Batch history stores found, eligible, attempted, submitted, blocked/error counts and final state.

If CAPTCHA, 2FA, bot detection or another access-control challenge blocks an application, Job Agent does not bypass it. The batch stops on a detected access-control block rather than repeatedly triggering the same challenge.

## Browser concurrency

Discovery, individual applications and batch auto-apply share the same persistent Chromium profile. The dashboard serializes these operations so only one browser workflow owns the profile at a time.

## Dashboard API

- `POST /api/search` — starts a discovery search.
- `GET /api/search/status` — returns discovery status.
- `POST /api/batch` — starts search + autonomous batch application.
- `GET /api/batch/status` — returns live batch progress.
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
- `GET /api/profile` — loads the local candidate profile.
- `POST /api/profile` — validates and saves the candidate profile.

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
