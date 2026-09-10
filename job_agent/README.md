# Job Agent — Computrabajo

Personal, local-first job discovery and auto-application app built on top of `browser-use` 0.13.10.

This project is intentionally optimized for one user and one local browser profile. It is not a multi-user SaaS: **Mi perfil** is the source of truth for search, scoring and application answers.

## Zero Cost is the default

Normal Job Agent execution is designed to incur **US$0 in paid AI/API, Browser Use Cloud, proxy and cloud-browser charges**.

```powershell
uv run python run_job_agent.py
```

That command enables the process-wide `JOB_AGENT_ZERO_COST=1` policy before the rest of Job Agent is imported. The policy:

- uses the local Chrome/Chromium session and CDP for Computrabajo navigation;
- keeps SQLite, scoring, deduplication, answer memory and application history local;
- forces search AI fallback off;
- forces question LLM fallback off;
- forces full application AI fallback off;
- shadows `BROWSER_USE_API_KEY` inside the process;
- blocks `MeteredChatBrowserUse.ainvoke()` **before any provider request is sent** if zero-cost mode is active.

This means a stale API key in `.env`, an accidentally enabled fallback flag, or an unexpected path through the metered Browser Use client cannot silently generate paid AI usage in normal mode.

The application still uses the local PC, electricity and the user's existing internet connection, so “zero cost” here specifically means **zero incremental third-party/API usage charges**.

Paid AI is available only as an explicit opt-in diagnostic/fallback mode:

```powershell
uv run python run_job_agent.py --allow-paid-ai
```

Do not use that flag when the requirement is strict US$0 API spend.

## What works now

1. Run the dashboard locally on `127.0.0.1`.
2. Configure one editable personal candidate profile directly from the dashboard.
3. Persist roles, skills, locations, experience, salary, availability, language level and frequent answers in local SQLite.
4. Discover Computrabajo vacancies through the local browser/CDP path.
5. Extract, deduplicate and score vacancies against the local profile.
6. Review each vacancy with strengths, gaps, score reasons and description.
7. Save or discard vacancies without losing that decision on later searches.
8. Attempt individual applications deterministically when required answers are supported by stored data.
9. Save every answer used, submission result and confirmation evidence.
10. Run a personalized multi-query autopilot across all target roles from **Mi perfil**.
11. Deduplicate vacancies across different role searches before selecting applications.
12. Apply to the highest-scoring new vacancies first, subject to per-run and daily limits.
13. Skip vacancies already marked `applied` or `ignored`.
14. Keep batch history and application-attempt history in SQLite.
15. Keep one persistent browser profile under `data/browser-profile`.
16. Learn high-confidence answers from confirmed applications and explicit manual corrections.
17. Keep historical AI metering for runs where paid mode was explicitly enabled.
18. Refuse CAPTCHA/2FA/access-control bypasses.

## Local setup

Use `uv` and Python 3.12 when possible.

```powershell
uv sync
```

Copy `.env.example` to `.env` if local overrides are needed. **No Browser Use API key is required for zero-cost mode.** The recommended zero-cost settings are:

```env
JOB_AGENT_ZERO_COST=1
JOB_AGENT_SEARCH_AI_FALLBACK=0
JOB_AGENT_QUESTION_LLM=0
JOB_AGENT_APPLICATION_AI_FALLBACK=0
BROWSER_USE_API_KEY=
```

Candidate and application data is configured from **Mi perfil**. The profile, learned answers, historical usage telemetry, SQLite database and browser state remain under the gitignored `data/` directory.

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

The app deliberately does not create users, organizations, teams or shared profiles. The local SQLite profile and persistent local Chromium session belong to the single owner of the app.

## Deterministic answer memory

Application answers are resolved from local data before any fallback is considered. In zero-cost mode, no paid fallback is available. Deterministic sources include:

1. explicit profile facts such as city, English level, salary expectation and availability;
2. manually configured frequent answers;
3. answers learned from previously confirmed applications;
4. answers explicitly corrected and saved by the user;
5. deterministic form/field rules for known Computrabajo patterns.

Questions are normalized locally and equivalent saved questions can be matched without a model deciding what the answer should be. Learned answers are stored in SQLite.

Automatic learning is conservative: an answer from an application is learned only after a confirmed submission, when an answer was actually supplied, did not require user input and met the confidence requirement. Explicit manual corrections are treated as user-provided facts.

The application must never invent personal information, qualifications, employment history, legal declarations, salary facts or work authorization.

## Deterministic browser flow

The zero-cost path uses the real local browser rather than simple HTTP scraping because Computrabajo is JavaScript-driven and can present verification/access-control pages.

The deterministic collectors/application runner operate through the persistent Chrome/Chromium profile and CDP. They inspect known page/form semantics, click and fill supported controls, reuse local answers and verify positive submission evidence.

If the site changes its DOM or presents a form the deterministic runner cannot safely understand, zero-cost mode records the incomplete/blocked result instead of secretly paying for an LLM call. We extend the deterministic adapter for those cases as they appear.

If CAPTCHA, 2FA, bot detection or another access-control challenge is encountered, Job Agent does not bypass it.

## AI usage and cost metering

AI metering is retained for historical data and for the explicit `--allow-paid-ai` mode. `MeteredChatBrowserUse` records Browser Use token metadata when a paid invocation is intentionally permitted.

In normal zero-cost mode, the same class contains a hard preflight guard. It raises before contacting the provider, so its expected new paid-call count is **0**.

The dashboard can still show previous AI usage. Historical spend does not mean the current zero-cost process is generating new spend.

## Automatic application mode

Open a vacancy with **Revisar** and click **Postular automáticamente**. The deterministic application runner opens the vacancy with the persistent local browser profile, navigates supported application controls, fills answers backed by local data, submits where safe, and verifies the confirmation state.

Every encountered question and answer is stored. `submitted=true` is recorded only when there is positive evidence that Computrabajo accepted the application. Successful submissions update the vacancy to `applied`.

If required information is unknown, the app does not invent it. That application is recorded for later improvement while the broader batch can continue when appropriate.

## Personalized multi-query autopilot

The **Buscar en todos mis cargos y postular** panel combines discovery and application into one run.

The runner:

1. loads `target_roles` from **Mi perfil**;
2. adds the optional one-off search term, if supplied;
3. deduplicates equivalent search terms case-insensitively;
4. caps the number of role searches;
5. treats `max_results` as one global discovery budget, not a multiplier per role;
6. distributes that budget across role searches;
7. reuses unused discovery budget;
8. deduplicates vacancies by canonical URL;
9. scores the combined unique set against the personal profile;
10. excludes jobs already marked `applied` or `ignored`;
11. sorts eligible jobs by score and recency;
12. applies sequentially to the best jobs until the run quota or daily limit is reached.

The daily limit is based on successful application attempts recorded for the local calendar day. Batch history stores searched roles plus found, eligible, attempted, submitted, blocked/error counts and final state.

## Browser concurrency

Discovery, individual applications and batch auto-apply share the same persistent Chromium profile. The dashboard serializes browser workflows so only one workflow owns that profile at a time.

## Dashboard API

- `POST /api/search` — starts a one-off discovery search.
- `GET /api/search/status` — returns discovery status.
- `POST /api/batch` — starts personal multi-query discovery + autonomous applications.
- `GET /api/batch/status` — returns live batch progress.
- `GET /api/batch/history` — returns persisted batch history.
- `GET /api/ai/usage` — returns historical/explicit-paid-mode Browser Use usage plus answer-memory metrics.
- `GET /api/jobs` — returns locally stored vacancies.
- `GET /api/jobs/{id}` — returns full vacancy detail.
- `POST /api/jobs/{id}/status` — changes a review state.
- `POST /api/jobs/{id}/prepare` — starts an individual automatic application.
- `GET /api/jobs/{id}/draft` — loads the latest stored answers/result.
- `POST /api/jobs/{id}/draft` — edits locally stored answers and remembers explicit corrections.
- `GET /api/jobs/{id}/attempts` — returns application-attempt history.
- `GET /api/prepare/status` — returns individual-application status.
- `GET /api/stats` — returns dashboard KPIs.
- `GET /api/profile` — loads the personal candidate profile.
- `POST /api/profile` — validates and saves the personal candidate profile.

## Safety and cost invariants

- paid AI/API calls are forbidden by default;
- an API key in `.env` cannot override zero-cost mode;
- the metered paid client checks zero-cost mode before network invocation;
- no invented personal facts;
- no CAPTCHA, 2FA, anti-bot or access-control bypass;
- no unrelated profile/account modification;
- duplicate applications are skipped when local state already says `applied`;
- success is recorded only with positive submission evidence;
- automatic answer learning requires confirmed/high-confidence evidence.

## Decision bands

- `< min_score`: ignore
- `min_score–74`: save
- `75–prepare_application_score-1`: recommend
- `>= prepare_application_score`: auto-apply candidate

## Development branch

All current Job Agent work lives on `develop/computrabajo-agent`. `main` remains untouched until the local deterministic flow is tested sufficiently. Upstream-derived Browser Use code remains isolated from application-specific code where practical so future upstream updates remain manageable.
