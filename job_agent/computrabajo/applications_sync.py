from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

from browser_use import Browser

from job_agent.computrabajo.browser_config import allowed_domains
from job_agent.storage import DEFAULT_DB_PATH, JobStore


MATCH_URL = "https://candidato.co.computrabajo.com/candidate/match/"
CANDIDATE_HOST = "candidato.co.computrabajo.com"
PUBLIC_HOST = "co.computrabajo.com"
PUBLIC_VACANCY_TOKEN = "/ofertas-de-trabajo/oferta-de-trabajo-de-"


@dataclass(frozen=True)
class SyncedApplication:
    external_key: str
    title: str
    company: str = ""
    location: str = ""
    status_text: str = ""
    date_text: str = ""
    candidate_url: str = ""
    public_job_url: str = ""
    raw_text: str = ""


@dataclass(frozen=True)
class ApplicationsReadResult:
    applications: tuple[SyncedApplication, ...] = ()
    source_url: str = MATCH_URL
    login_required: bool = False
    blocked_reason: str = ""


def _normalize_text(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    ascii_value = "".join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return urlunparse(("https", parsed.hostname.casefold(), parsed.path.rstrip("/") or "/", "", "", ""))


def _safe_candidate_url(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and parsed.hostname == CANDIDATE_HOST and "/match/" in parsed.path


def _safe_public_job_url(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and parsed.hostname == PUBLIC_HOST and PUBLIC_VACANCY_TOKEN in parsed.path


def _runtime_value(result: Any) -> Any:
    if isinstance(result, dict):
        payload = result.get("result")
        if isinstance(payload, dict):
            return payload.get("value")
    return None


class ComputrabajoApplicationsStore:
    """Persist applications observed in the candidate portal without fabricating job attempts."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH, job_store: JobStore | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.job_store = job_store or JobStore(self.path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS computrabajo_synced_applications (
                    external_key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    status_text TEXT NOT NULL DEFAULT '',
                    date_text TEXT NOT NULL DEFAULT '',
                    candidate_url TEXT NOT NULL DEFAULT '',
                    public_job_url TEXT NOT NULL DEFAULT '',
                    raw_text TEXT NOT NULL DEFAULT '',
                    job_id INTEGER,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_computrabajo_synced_job_id
                    ON computrabajo_synced_applications(job_id);
                CREATE INDEX IF NOT EXISTS idx_computrabajo_synced_last_seen
                    ON computrabajo_synced_applications(last_seen_at DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _local_jobs(self) -> list[dict[str, object]]:
        return [
            item
            for item in self.job_store.list_jobs(limit=10000)
            if str(item.get("source") or "") == "computrabajo"
        ]

    def _match_job_id(self, item: SyncedApplication, jobs: list[dict[str, object]]) -> int | None:
        public_url = _canonical_url(item.public_job_url)
        if public_url:
            exact = [job for job in jobs if _canonical_url(job.get("url")) == public_url]
            if len(exact) == 1:
                return int(exact[0]["id"])

        title = _normalize_text(item.title)
        company = _normalize_text(item.company)
        if not title or not company:
            return None
        exact = [
            job
            for job in jobs
            if _normalize_text(job.get("title")) == title and _normalize_text(job.get("company")) == company
        ]
        return int(exact[0]["id"]) if len(exact) == 1 else None

    def sync(self, applications: tuple[SyncedApplication, ...]) -> dict[str, int]:
        jobs = self._local_jobs()
        linked = 0
        promoted = 0
        with self._connect() as connection:
            for item in applications:
                job_id = self._match_job_id(item, jobs)
                if job_id is not None:
                    linked += 1
                    local = next((job for job in jobs if int(job["id"]) == job_id), None)
                    if local and str(local.get("status") or "") != "applied":
                        connection.execute("UPDATE jobs SET status = 'applied' WHERE id = ?", (job_id,))
                        local["status"] = "applied"
                        promoted += 1
                connection.execute(
                    """
                    INSERT INTO computrabajo_synced_applications(
                        external_key, title, company, location, status_text, date_text,
                        candidate_url, public_job_url, raw_text, job_id, first_seen_at, last_seen_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(external_key) DO UPDATE SET
                        title=excluded.title,
                        company=excluded.company,
                        location=excluded.location,
                        status_text=excluded.status_text,
                        date_text=excluded.date_text,
                        candidate_url=excluded.candidate_url,
                        public_job_url=excluded.public_job_url,
                        raw_text=excluded.raw_text,
                        job_id=COALESCE(excluded.job_id, computrabajo_synced_applications.job_id),
                        last_seen_at=CURRENT_TIMESTAMP
                    """,
                    (
                        item.external_key,
                        item.title,
                        item.company,
                        item.location,
                        item.status_text,
                        item.date_text,
                        item.candidate_url,
                        item.public_job_url,
                        item.raw_text[:3000],
                        job_id,
                    ),
                )
        return {
            "found": len(applications),
            "linked": linked,
            "promoted": promoted,
            "unlinked": max(0, len(applications) - linked),
        }

    def _has_local_submission(self, connection: sqlite3.Connection, job_id: int) -> bool:
        row = connection.execute(
            "SELECT 1 FROM application_attempts WHERE job_id = ? AND submitted = 1 LIMIT 1",
            (job_id,),
        ).fetchone()
        return row is not None

    def list_combined(self) -> list[dict[str, object]]:
        local_applied = self.job_store.list_jobs(limit=10000, status="applied")
        with self._connect() as connection:
            synced_rows = connection.execute(
                "SELECT * FROM computrabajo_synced_applications ORDER BY last_seen_at DESC, external_key"
            ).fetchall()
            synced_by_job = {
                int(row["job_id"]): row
                for row in synced_rows
                if row["job_id"] is not None
            }
            items: list[dict[str, object]] = []
            local_ids: set[int] = set()
            for job in local_applied:
                job_id = int(job["id"])
                local_ids.add(job_id)
                synced = synced_by_job.get(job_id)
                local_submission = self._has_local_submission(connection, job_id)
                if synced is not None:
                    origin = "Job Agent + Computrabajo" if local_submission else "Computrabajo"
                    candidate_url = str(synced["candidate_url"] or "")
                    status_text = str(synced["status_text"] or "")
                    date_text = str(synced["date_text"] or "")
                    last_seen_at = str(synced["last_seen_at"] or "")
                else:
                    origin = "Job Agent"
                    candidate_url = ""
                    status_text = "Postulada"
                    date_text = ""
                    last_seen_at = str(job.get("created_at") or "")
                items.append(
                    {
                        "key": f"job:{job_id}",
                        "job_id": job_id,
                        "title": str(job.get("title") or ""),
                        "company": str(job.get("company") or ""),
                        "location": str(job.get("location") or ""),
                        "score": int(job.get("score") or 0),
                        "status": status_text or "Postulada",
                        "origin": origin,
                        "verified_in_computrabajo": synced is not None,
                        "date_text": date_text,
                        "candidate_url": candidate_url,
                        "public_job_url": str(job.get("url") or ""),
                        "last_seen_at": last_seen_at,
                    }
                )

            for row in synced_rows:
                job_id = int(row["job_id"]) if row["job_id"] is not None else None
                if job_id is not None and job_id in local_ids:
                    continue
                items.append(
                    {
                        "key": f"sync:{row['external_key']}",
                        "job_id": None,
                        "title": str(row["title"] or ""),
                        "company": str(row["company"] or ""),
                        "location": str(row["location"] or ""),
                        "score": None,
                        "status": str(row["status_text"] or "Postulada"),
                        "origin": "Computrabajo",
                        "verified_in_computrabajo": True,
                        "date_text": str(row["date_text"] or ""),
                        "candidate_url": str(row["candidate_url"] or ""),
                        "public_job_url": str(row["public_job_url"] or ""),
                        "last_seen_at": str(row["last_seen_at"] or ""),
                    }
                )

        items.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
        return items


class DeterministicApplicationsReader:
    """Read the user's Computrabajo application history via local Chrome/CDP, without an LLM."""

    def __init__(self, profile_dir: Path | str = Path("data/browser-profile")) -> None:
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    async def collect(self, *, max_results: int = 500) -> ApplicationsReadResult:
        browser = Browser(
            user_data_dir=str(self.profile_dir.resolve()),
            headless=False,
            allowed_domains=allowed_domains(),
        )
        applications: dict[str, SyncedApplication] = {}
        try:
            await browser.start()
            cdp = await browser.get_or_create_cdp_session(browser.agent_focus_target_id, focus=True)
            await cdp.cdp_client.send.Page.enable(session_id=cdp.session_id)
            await self._navigate(cdp, MATCH_URL)

            stagnant = 0
            visited_pages: set[str] = set()
            for _ in range(16):
                state = await self._evaluate(cdp, self._snapshot_script())
                if not isinstance(state, dict):
                    return ApplicationsReadResult(tuple(applications.values()), blocked_reason="No se pudo leer Mis postulaciones.")

                current_url = _clean(state.get("url"))
                body = _clean(state.get("body"))
                parsed = urlparse(current_url)
                if parsed.hostname != CANDIDATE_HOST:
                    if self._looks_like_login(current_url, body):
                        return ApplicationsReadResult(tuple(applications.values()), current_url, login_required=True)
                    return ApplicationsReadResult(
                        tuple(applications.values()),
                        current_url,
                        blocked_reason=f"Redirección inesperada durante la sincronización: {current_url or 'sin URL'}",
                    )

                block = self._block_reason(body)
                if block:
                    return ApplicationsReadResult(tuple(applications.values()), current_url, blocked_reason=block)

                before = len(applications)
                raw_items = state.get("applications") or []
                if isinstance(raw_items, list):
                    for raw in raw_items:
                        item = self._parse_item(raw)
                        if item is not None:
                            applications[item.external_key] = item
                            if len(applications) >= max_results:
                                return ApplicationsReadResult(tuple(applications.values()), current_url)

                stagnant = stagnant + 1 if len(applications) == before else 0
                next_url = _canonical_url(state.get("next_url"))
                if stagnant >= 2 and next_url and next_url not in visited_pages and _safe_candidate_url(next_url):
                    visited_pages.add(next_url)
                    await self._navigate(cdp, next_url)
                    stagnant = 0
                    continue
                if stagnant >= 3:
                    break

                await self._evaluate(cdp, "(() => { window.scrollTo(0, document.body.scrollHeight); return true; })()")
                await asyncio.sleep(0.8)

            return ApplicationsReadResult(tuple(applications.values()), MATCH_URL)
        finally:
            await browser.stop()

    @staticmethod
    def _parse_item(raw: object) -> SyncedApplication | None:
        if not isinstance(raw, dict):
            return None
        title = _clean(raw.get("title"))
        company = _clean(raw.get("company"))
        candidate_url = _canonical_url(raw.get("candidate_url"))
        public_url = _canonical_url(raw.get("public_job_url"))
        if not title or title.casefold() in {"mis postulaciones", "postulaciones", "ver oferta", "ver vacante"}:
            return None
        if candidate_url and not _safe_candidate_url(candidate_url):
            candidate_url = ""
        if public_url and not _safe_public_job_url(public_url):
            public_url = ""
        if not candidate_url and not public_url:
            return None
        seed = candidate_url or public_url or f"{_normalize_text(title)}|{_normalize_text(company)}"
        key = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
        return SyncedApplication(
            external_key=key,
            title=title,
            company=company,
            location=_clean(raw.get("location")),
            status_text=_clean(raw.get("status_text")),
            date_text=_clean(raw.get("date_text")),
            candidate_url=candidate_url,
            public_job_url=public_url,
            raw_text=_clean(raw.get("raw_text")),
        )

    @staticmethod
    def _looks_like_login(url: str, body: str) -> bool:
        text = _normalize_text(f"{url} {body[:1500]}")
        return any(token in text for token in ("iniciar sesion", "login", "ingresa a tu cuenta", "correo contrasena"))

    @staticmethod
    def _block_reason(body: str) -> str:
        text = _normalize_text(body[:2500])
        markers = {
            "403 forbidden": "Computrabajo respondió 403 Forbidden durante la sincronización.",
            "access denied": "Computrabajo bloqueó el acceso durante la sincronización.",
            "acceso denegado": "Computrabajo bloqueó el acceso durante la sincronización.",
            "captcha": "Computrabajo solicita CAPTCHA; la sincronización se detuvo.",
            "verifica que eres humano": "Computrabajo solicita verificación humana; la sincronización se detuvo.",
            "too many redirects": "La sesión de Computrabajo entró en demasiadas redirecciones.",
        }
        for marker, message in markers.items():
            if marker in text:
                return message
        return ""

    async def _navigate(self, cdp: Any, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != CANDIDATE_HOST:
            raise ValueError(f"Synchronization refused non-candidate Computrabajo URL: {url}")
        await cdp.cdp_client.send.Page.navigate(params={"url": url}, session_id=cdp.session_id)
        for _ in range(40):
            await asyncio.sleep(0.25)
            state = await self._evaluate(cdp, "(() => ({ready: document.readyState, url: location.href}))()")
            if isinstance(state, dict) and state.get("ready") in {"interactive", "complete"}:
                await asyncio.sleep(0.45)
                return
        raise TimeoutError("Computrabajo no terminó de cargar Mis postulaciones.")

    @staticmethod
    async def _evaluate(cdp: Any, expression: str) -> Any:
        result = await cdp.cdp_client.send.Runtime.evaluate(
            params={"expression": expression, "returnByValue": True, "awaitPromise": True},
            session_id=cdp.session_id,
        )
        return _runtime_value(result)

    @staticmethod
    def _snapshot_script() -> str:
        return r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const norm = (v) => clean(v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const candidateHost = 'candidato.co.computrabajo.com';
  const publicHost = 'co.computrabajo.com';
  const vacancyToken = '/ofertas-de-trabajo/oferta-de-trabajo-de-';
  const safeUrl = (href) => { try { return new URL(href, location.href); } catch (_) { return null; } };
  const meaningfulTitle = (value) => {
    const n = norm(value);
    return n && !['ver oferta','ver vacante','detalle','detalles','aplicar','postular'].includes(n);
  };
  const roots = [];
  const seenRoots = new Set();
  for (const anchor of document.querySelectorAll('a[href]')) {
    const url = safeUrl(anchor.href);
    if (!url) continue;
    const candidateMatch = url.hostname === candidateHost && url.pathname.includes('/match/') && !/^\/candidate\/match\/?$/.test(url.pathname);
    const publicVacancy = url.hostname === publicHost && url.pathname.includes(vacancyToken);
    if (!candidateMatch && !publicVacancy) continue;
    const root = anchor.closest('article, li, [class*="card"], [class*="item"], [class*="offer"], [class*="vacan"], [class*="application"], [data-id]') || anchor.parentElement;
    if (!root || seenRoots.has(root)) continue;
    seenRoots.add(root);
    roots.push(root);
  }

  const applications = [];
  for (const root of roots) {
    const links = Array.from(root.querySelectorAll('a[href]')).map((a) => ({node:a, url:safeUrl(a.href)})).filter((x) => x.url);
    const candidate = links.find((x) => x.url.hostname === candidateHost && x.url.pathname.includes('/match/') && !/^\/candidate\/match\/?$/.test(x.url.pathname));
    const publicJob = links.find((x) => x.url.hostname === publicHost && x.url.pathname.includes(vacancyToken));
    if (!candidate && !publicJob) continue;

    const headings = Array.from(root.querySelectorAll('h1,h2,h3,h4,[class*="title"],[class*="puesto"],[class*="position"]'));
    let title = clean(headings.map((x) => clean(x.innerText)).find(meaningfulTitle) || '');
    if (!title) {
      const anchorText = clean((candidate?.node || publicJob?.node)?.innerText);
      if (meaningfulTitle(anchorText)) title = anchorText;
    }
    if (!title) continue;

    const companyNode = root.querySelector('[class*="company"],[class*="empresa"],[data-company]');
    const locationNode = root.querySelector('[class*="location"],[class*="ubicacion"],[class*="city"],[class*="place"]');
    const statusNode = root.querySelector('[class*="status"],[class*="estado"],[class*="stage"],[class*="state"],[class*="process"]');
    const timeNode = root.querySelector('time,[class*="date"],[class*="fecha"]');
    const raw = clean(root.innerText);
    let status = clean(statusNode?.innerText || '');
    if (!status) {
      const n = norm(raw);
      if (n.includes('ya te postulaste') || n.includes('postulad')) status = 'Postulada';
      else if (n.includes('proceso finalizado')) status = 'Proceso finalizado';
      else if (n.includes('cv visto') || n.includes('hoja de vida vista')) status = 'CV visto';
      else if (n.includes('descartad')) status = 'Descartada';
    }
    let dateText = clean(timeNode?.getAttribute('datetime') || timeNode?.innerText || '');
    if (!dateText) {
      const match = raw.match(/(?:\b\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}\b|\bhace\s+\d+\s+(?:minutos?|horas?|d[ií]as?|semanas?|meses?)\b)/i);
      if (match) dateText = clean(match[0]);
    }
    applications.push({
      title,
      company: clean(companyNode?.innerText || ''),
      location: clean(locationNode?.innerText || ''),
      status_text: status,
      date_text: dateText,
      candidate_url: candidate?.url?.toString() || '',
      public_job_url: publicJob?.url?.toString() || '',
      raw_text: raw.slice(0, 3000),
    });
  }

  let nextUrl = '';
  const nextCandidates = Array.from(document.querySelectorAll('a[href]'));
  const next = nextCandidates.find((a) => a.rel === 'next' || ['siguiente','next','ver mas','ver más','cargar mas','cargar más'].includes(norm(a.innerText || a.getAttribute('aria-label'))));
  if (next) {
    const url = safeUrl(next.href);
    if (url && url.hostname === candidateHost) nextUrl = url.toString();
  }
  return {
    url: location.href,
    body: clean(document.body?.innerText || '').slice(0, 12000),
    applications,
    next_url: nextUrl,
  };
})()
"""


class ComputrabajoApplicationsSync:
    """Background coordinator for the read-only deterministic synchronization."""

    def __init__(
        self,
        store: ComputrabajoApplicationsStore,
        reader: DeterministicApplicationsReader | None = None,
    ) -> None:
        self.store = store
        self.reader = reader or DeterministicApplicationsReader()
        self._lock = threading.Lock()
        self._status: dict[str, object] = {
            "state": "idle",
            "found": 0,
            "linked": 0,
            "promoted": 0,
            "unlinked": 0,
            "login_required": False,
            "message": "Listo para sincronizar Mis postulaciones desde Computrabajo.",
        }

    def status(self) -> dict[str, object]:
        with self._lock:
            return dict(self._status)

    def start(self) -> bool:
        with self._lock:
            if self._status.get("state") == "running":
                return False
            self._status = {
                "state": "running",
                "found": 0,
                "linked": 0,
                "promoted": 0,
                "unlinked": 0,
                "login_required": False,
                "message": "Leyendo Mis postulaciones de Computrabajo sin IA…",
            }
        threading.Thread(target=self._worker, daemon=True, name="computrabajo-applications-sync").start()
        return True

    def _finish(self, state: Literal["completed", "error"], **values: object) -> None:
        with self._lock:
            self._status = {**self._status, **values, "state": state}

    def _worker(self) -> None:
        try:
            result = asyncio.run(self.reader.collect())
            if result.login_required:
                self._finish(
                    "error",
                    login_required=True,
                    message="La sesión de Computrabajo no está iniciada. Inicia sesión en el Chrome de Job Agent y vuelve a sincronizar.",
                )
                return
            if result.blocked_reason:
                self._finish("error", message=result.blocked_reason)
                return
            stats = self.store.sync(result.applications)
            self._finish(
                "completed",
                **stats,
                login_required=False,
                message=(
                    f"Sincronización terminada: {stats['found']} postulaciones visibles, "
                    f"{stats['linked']} vinculadas y {stats['unlinked']} importadas como historial externo."
                ),
            )
        except Exception as exc:
            self._finish("error", message=f"No se pudo sincronizar Computrabajo: {type(exc).__name__}: {exc}")
