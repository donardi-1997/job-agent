# Job Agent — Computrabajo

Local-first job discovery and assisted-application app built on top of `browser-use` 0.13.10.

## What works now

1. Run the dashboard locally on `127.0.0.1`.
2. Configure an editable candidate profile directly from the dashboard.
3. Persist roles, skills, locations, experience and scoring thresholds in local SQLite.
4. Start a real Browser Use search on `co.computrabajo.com`.
5. Extract, deduplicate and score vacancies against the locally saved profile.
6. Review each vacancy in a detail drawer with strengths, gaps, score reasons and description.
7. Save or discard individual vacancies without losing the decision on future searches.
8. Prepare an assisted application draft for a vacancy.
9. Inspect visible application questions/fields when this can be done without submitting or creating the application.
10. Store suggested answers, options, confidence and `requires_user_input` flags in SQLite.
11. Reopen an existing draft without running Browser Use again.
12. Keep a persistent browser profile under `data/browser-profile`.
13. Never submit an application automatically.

## Local setup

Use `uv` and Python 3.12 when possible.

```powershell
uv sync
```

Create a local `.env` file with the Browser Use API key:

```env
BROWSER_USE_API_KEY=your_key_here
```

Candidate matching configuration no longer needs to live in `.env`; edit it from **Mi perfil** in the dashboard. The profile, application drafts, SQLite database and browser state remain under the gitignored `data/` directory.

Start the application:

```powershell
uv run python run_job_agent.py
```

The dashboard opens automatically at:

```text
http://127.0.0.1:8765
```

## Assisted application mode

Open a vacancy with **Revisar** and click **Preparar postulación**. Browser Use opens the vacancy in the same persistent local browser profile and attempts to inspect the application flow.

The preparer may open an application form only when doing so is clearly non-submitting. It must stop if opening or advancing the flow could create/finalize an application, or if CAPTCHA, 2FA, bot detection or another access control blocks the flow.

For every visible field/question, the stored draft can contain:

- exact label/question;
- field type;
- selectable options;
- suggested answer;
- confidence from 0 to 100;
- whether user input is required;
- a note explaining uncertainty.

The agent must not invent missing personal facts. Unknown answers remain marked for manual review. The dashboard does not expose any final submit action.

## Browser concurrency

Discovery searches and application preparation share the same persistent Chromium profile. The dashboard therefore serializes them: a search cannot start while a preparation is running, and a preparation cannot start while a search is running.

## Dashboard API

- `POST /api/search` — starts a background Computrabajo search.
- `GET /api/search/status` — returns discovery status.
- `GET /api/jobs` — returns locally stored vacancies.
- `GET /api/jobs/{id}` — returns full vacancy detail.
- `POST /api/jobs/{id}/status` — saves a manual review status.
- `POST /api/jobs/{id}/prepare` — starts assisted application preparation.
- `GET /api/jobs/{id}/draft` — loads the saved application draft.
- `GET /api/prepare/status` — returns preparation status.
- `GET /api/stats` — returns dashboard KPIs.
- `GET /api/profile` — loads the locally persisted candidate profile.
- `POST /api/profile` — validates and saves the candidate profile.

## Safety defaults

- `auto_submit = False`
- no final application submission;
- no profile/account modification;
- no CV replacement/upload during preparation;
- no message sending;
- no CAPTCHA/2FA/anti-bot bypass;
- no invented personal facts;
- mandatory human review of suggested answers.

## Decision bands

- `< min_score`: ignore
- `min_score–74`: save
- `75–prepare_application_score-1`: recommend
- `>= prepare_application_score`: prepare application

## Next milestones

- Add richer application-profile fields such as salary expectation, availability and language level so more answers can be suggested safely.
- Let the user edit draft answers locally before opening Computrabajo.
- Search history and per-run metrics.
- Application pipeline states and response/interview analytics.
- A later controlled fill mode, still requiring explicit final human submission.

## Development branch

All current Job Agent work lives on `develop/computrabajo-agent`. Keep upstream-derived Browser Use code isolated from application-specific code where practical so future upstream updates remain manageable.
