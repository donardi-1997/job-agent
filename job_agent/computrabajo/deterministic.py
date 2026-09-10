from __future__ import annotations

import asyncio
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from browser_use import Browser
from job_agent.computrabajo.browser_config import allowed_domains
from job_agent.storage import DEFAULT_DB_PATH


COMPUTRABAJO_HOST = "co.computrabajo.com"
VACANCY_PATH_TOKEN = "/ofertas-de-trabajo/oferta-de-trabajo-de-"


@dataclass(frozen=True)
class DeterministicJob:
    title: str
    company: str
    location: str
    description: str
    url: str


@dataclass(frozen=True)
class DeterministicSearchResult:
    jobs: tuple[DeterministicJob, ...]
    search_url: str
    reason: str = ""


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    # Computrabajo commonly collapses dotted abbreviations such as D.C. -> dc.
    ascii_value = ascii_value.replace(".", "")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")


def build_search_url(keyword: str, location: str = "Colombia") -> str:
    """Build a public Computrabajo result URL without invoking an LLM."""
    term = _slug(keyword)
    if not term:
        raise ValueError("El término de búsqueda está vacío.")
    path = f"https://{COMPUTRABAJO_HOST}/trabajo-de-{term}"
    location_slug = _slug(location)
    if location_slug and location_slug not in {"colombia", "co"}:
        path += f"-en-{location_slug}"
    return path


def search_keyword_variants(keyword: str) -> tuple[str, ...]:
    """Return conservative deterministic broadening variants for job-title queries.

    Computrabajo can return zero results for a precise title such as
    ``Node.js Developer`` while ``Node.js`` has matching vacancies. Try a few
    progressively broader local URLs before paying for an AI search fallback.
    """
    cleaned = " ".join(str(keyword or "").strip().split())
    if not cleaned:
        return ()

    variants: list[str] = [cleaned]
    lowered = cleaned.casefold()
    suffixes = (
        " developer",
        " desarrollador",
        " engineer",
        " ingeniero",
    )
    broader = cleaned
    for suffix in suffixes:
        if lowered.endswith(suffix):
            broader = cleaned[: -len(suffix)].strip()
            break
    if broader and broader.casefold() != cleaned.casefold():
        variants.append(broader)

    # A compound technical title can still be too narrow. Preserve the leading
    # technology token as a final conservative variant (Python Backend -> Python).
    parts = broader.split()
    if len(parts) > 1:
        first = parts[0]
        # Keep dotted technology names such as Node.js intact.
        if len(first) >= 2 and first.casefold() not in {item.casefold() for item in variants}:
            variants.append(first)

    result: list[str] = []
    seen: set[str] = set()
    for value in variants:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result[:3])


def is_safe_computrabajo_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == COMPUTRABAJO_HOST


def _runtime_value(result: Any) -> Any:
    if isinstance(result, dict):
        payload = result.get("result")
        if isinstance(payload, dict):
            return payload.get("value")
    return None


class SearchExecutionStore:
    """Tracks how often discovery is resolved locally versus with the AI fallback."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS search_execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    location TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK(mode IN ('deterministic', 'ai_fallback')),
                    found INTEGER NOT NULL DEFAULT 0,
                    fallback_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def record(self, *, keyword: str, location: str, mode: str, found: int, fallback_reason: str = "") -> None:
        if mode not in {"deterministic", "ai_fallback"}:
            raise ValueError(f"Unsupported search mode: {mode}")
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO search_execution_log(keyword, location, mode, found, fallback_reason) VALUES(?, ?, ?, ?, ?)",
                (keyword, location, mode, int(found), fallback_reason[:1000]),
            )

    def summary(self) -> dict[str, object]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN mode='deterministic' THEN 1 ELSE 0 END), 0) AS deterministic,
                    COALESCE(SUM(CASE WHEN mode='ai_fallback' THEN 1 ELSE 0 END), 0) AS ai_fallback,
                    COALESCE(SUM(found), 0) AS jobs_found
                FROM search_execution_log
                """
            ).fetchone()
        total = int(row[0]) if row else 0
        deterministic = int(row[1]) if row else 0
        fallback = int(row[2]) if row else 0
        jobs_found = int(row[3]) if row else 0
        return {
            "total": total,
            "deterministic": deterministic,
            "ai_fallback": fallback,
            "jobs_found": jobs_found,
            "deterministic_rate": round((deterministic / total) * 100, 1) if total else 0.0,
        }


class DeterministicComputrabajoSearch:
    """Read public Computrabajo pages through Chrome/CDP without an LLM.

    It uses the same persistent local browser profile as Browser Use, but navigation
    and extraction are deterministic. The AI agent is expected to be used only by
    the caller as a fallback when this layer cannot obtain any valid vacancies.
    """

    def __init__(self, profile_dir: Path | str) -> None:
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    async def collect(self, *, keyword: str, location: str, max_results: int) -> DeterministicSearchResult:
        variants = search_keyword_variants(keyword)
        search_url = build_search_url(variants[0] if variants else keyword, location)
        browser = Browser(
            user_data_dir=str(self.profile_dir.resolve()),
            headless=False,
            allowed_domains=allowed_domains(),
        )
        try:
            await browser.start()
            cdp = await browser.get_or_create_cdp_session(browser.agent_focus_target_id, focus=True)
            await cdp.cdp_client.send.Page.enable(session_id=cdp.session_id)

            listing: dict[str, object] | None = None
            attempted_urls: list[str] = []
            for variant in variants or (keyword,):
                candidate_search_url = build_search_url(variant, location)
                attempted_urls.append(candidate_search_url)
                await self._navigate(cdp, candidate_search_url)
                candidate_listing = await self._read_listing(cdp)
                if not isinstance(candidate_listing, dict):
                    continue

                current_url = str(candidate_listing.get("url") or "")
                body = str(candidate_listing.get("body") or "")
                if not is_safe_computrabajo_url(current_url):
                    return DeterministicSearchResult(
                        (), candidate_search_url, f"Redirección inesperada: {current_url or 'sin URL'}"
                    )
                block_reason = self._detect_block(body)
                if block_reason:
                    return DeterministicSearchResult((), candidate_search_url, block_reason)

                candidates = candidate_listing.get("jobs") or []
                if isinstance(candidates, list) and candidates:
                    listing = candidate_listing
                    search_url = candidate_search_url
                    break

            if listing is None:
                attempted = ", ".join(attempted_urls)
                return DeterministicSearchResult(
                    (),
                    search_url,
                    f"No se encontraron enlaces de vacantes reconocibles tras variantes determinísticas: {attempted}",
                )

            candidates = listing.get("jobs") or []
            if not isinstance(candidates, list):
                candidates = []

            jobs: list[DeterministicJob] = []
            seen: set[str] = set()
            for candidate in candidates:
                if len(jobs) >= max_results:
                    break
                if not isinstance(candidate, dict):
                    continue
                url = str(candidate.get("url") or "").split("#", 1)[0].split("?", 1)[0]
                if not url or url in seen or not is_safe_computrabajo_url(url) or VACANCY_PATH_TOKEN not in urlparse(url).path:
                    continue
                seen.add(url)
                card_title = self._clean(str(candidate.get("title") or ""))
                card_text = self._clean(str(candidate.get("card_text") or ""))

                detail: dict[str, object] = {}
                try:
                    await self._navigate(cdp, url)
                    extracted = await self._evaluate(cdp, self._detail_script())
                    if isinstance(extracted, dict) and is_safe_computrabajo_url(str(extracted.get("url") or "")):
                        detail = extracted
                except Exception:
                    # A single detail page must not invalidate all listing results.
                    detail = {}

                title = self._clean(str(detail.get("title") or card_title))
                if not title:
                    continue
                company = self._clean(str(detail.get("company") or ""))
                job_location = self._clean(str(detail.get("location") or ""))
                description = self._clean(str(detail.get("description") or card_text))
                if len(description) > 8000:
                    description = description[:8000]
                jobs.append(
                    DeterministicJob(
                        title=title,
                        company=company,
                        location=job_location,
                        description=description,
                        url=url,
                    )
                )

            reason = "" if jobs else "El listado tenía enlaces, pero ninguna vacante válida pudo normalizarse."
            return DeterministicSearchResult(tuple(jobs), search_url, reason)
        finally:
            await browser.stop()

    async def _read_listing(self, cdp: Any) -> dict[str, object] | None:
        """Poll briefly for client-rendered vacancy links before declaring no results."""
        latest: dict[str, object] | None = None
        for attempt in range(10):
            value = await self._evaluate(cdp, self._listing_script())
            if isinstance(value, dict):
                latest = value
                jobs = value.get("jobs") or []
                if isinstance(jobs, list) and jobs:
                    return value
            if attempt < 9:
                await asyncio.sleep(0.3)
        return latest

    async def _navigate(self, cdp: Any, url: str) -> None:
        if not is_safe_computrabajo_url(url):
            raise ValueError(f"Deterministic navigation refused non-Computrabajo URL: {url}")
        await cdp.cdp_client.send.Page.navigate(params={"url": url}, session_id=cdp.session_id)
        for _ in range(40):
            await asyncio.sleep(0.25)
            state = await self._evaluate(
                cdp,
                "(() => ({ready: document.readyState, href: location.href, text: (document.body?.innerText || '').slice(0,300)}))()",
            )
            if isinstance(state, dict) and state.get("ready") in {"interactive", "complete"}:
                # Give client-rendered listing cards a short deterministic grace period.
                await asyncio.sleep(0.35)
                return
        raise TimeoutError(f"Computrabajo no terminó de cargar: {url}")

    @staticmethod
    async def _evaluate(cdp: Any, expression: str) -> Any:
        result = await cdp.cdp_client.send.Runtime.evaluate(
            params={"expression": expression, "returnByValue": True, "awaitPromise": True},
            session_id=cdp.session_id,
        )
        return _runtime_value(result)

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _detect_block(body: str) -> str:
        text = body.casefold()
        markers = {
            "captcha": "CAPTCHA detectado en la búsqueda determinística.",
            "verifica que eres humano": "Verificación humana detectada.",
            "verify you are human": "Verificación humana detectada.",
            "access denied": "Acceso bloqueado por Computrabajo.",
            "acceso denegado": "Acceso bloqueado por Computrabajo.",
        }
        for marker, reason in markers.items():
            if marker in text:
                return reason
        return ""

    @staticmethod
    def _listing_script() -> str:
        return r"""
(() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const links = Array.from(document.querySelectorAll('a[href*="/ofertas-de-trabajo/oferta-de-trabajo-de-"]'));
  const seen = new Set();
  const jobs = [];
  for (const anchor of links) {
    let parsed;
    try { parsed = new URL(anchor.href, location.href); } catch (_) { continue; }
    if (parsed.hostname !== 'co.computrabajo.com') continue;
    parsed.search = '';
    parsed.hash = '';
    const url = parsed.toString();
    if (seen.has(url)) continue;
    seen.add(url);
    const root = anchor.closest('article, li, [class*="offer"], [class*="job"], [data-id]') || anchor.parentElement;
    const heading = root?.querySelector('h1, h2, h3, [class*="title"]');
    const title = clean(heading?.innerText || anchor.innerText);
    const cardText = clean(root?.innerText || anchor.innerText);
    if (title || cardText) jobs.push({ title, card_text: cardText, url });
  }
  return {
    url: location.href,
    title: document.title,
    body: clean(document.body?.innerText || '').slice(0, 6000),
    jobs: jobs.slice(0, 100),
  };
})()
"""

    @staticmethod
    def _detail_script() -> str:
        return r"""
(() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const textFromHtml = (html) => {
    const node = document.createElement('div');
    node.innerHTML = String(html || '');
    return clean(node.innerText || node.textContent || '');
  };
  const flatten = (value, out) => {
    if (Array.isArray(value)) { value.forEach((item) => flatten(item, out)); return; }
    if (!value || typeof value !== 'object') return;
    const type = value['@type'];
    const types = Array.isArray(type) ? type : [type];
    if (types.some((item) => String(item || '').toLowerCase() === 'jobposting')) out.push(value);
    if (Array.isArray(value['@graph'])) flatten(value['@graph'], out);
  };
  const salaryText = (salary) => {
    if (!salary) return '';
    const currency = clean(salary.currency || salary.value?.currency || 'COP');
    const value = salary.value ?? salary;
    if (typeof value === 'number' || typeof value === 'string') {
      return clean(`Salario: ${currency} ${value}`);
    }
    if (!value || typeof value !== 'object') return '';
    const unit = clean(value.unitText || value.unitCode || '');
    const fixed = value.value;
    const min = value.minValue;
    const max = value.maxValue;
    if (fixed != null) return clean(`Salario: ${currency} ${fixed} ${unit}`);
    if (min != null && max != null) return clean(`Rango salarial: ${currency} ${min} a ${max} ${unit}`);
    if (min != null) return clean(`Salario: desde ${currency} ${min} ${unit}`);
    if (max != null) return clean(`Salario: hasta ${currency} ${max} ${unit}`);
    return '';
  };
  const postings = [];
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { flatten(JSON.parse(script.textContent || '{}'), postings); } catch (_) {}
  }
  const posting = postings[0] || null;
  const org = posting?.hiringOrganization;
  const companyFromSchema = typeof org === 'string' ? org : org?.name;
  const locations = Array.isArray(posting?.jobLocation) ? posting.jobLocation : posting?.jobLocation ? [posting.jobLocation] : [];
  const locationParts = [];
  for (const item of locations) {
    const address = item?.address || item;
    if (typeof address === 'string') { locationParts.push(address); continue; }
    if (address && typeof address === 'object') {
      const country = typeof address.addressCountry === 'object' ? address.addressCountry?.name : address.addressCountry;
      const joined = [address.addressLocality, address.addressRegion, country].filter(Boolean).join(', ');
      if (joined) locationParts.push(joined);
    }
  }
  const domCompany = document.querySelector('[itemprop="hiringOrganization"], [class*="company"] a, a[href*="/empresas/"]');
  const domLocation = document.querySelector('[itemprop="jobLocation"], [class*="location"], [class*="place"]');
  const domDescription = document.querySelector('[itemprop="description"], [class*="description"], article');
  const description = clean(posting?.description ? textFromHtml(posting.description) : (domDescription?.innerText || ''));
  const salary = salaryText(posting?.baseSalary);
  return {
    url: location.href,
    title: clean(posting?.title || document.querySelector('h1')?.innerText || ''),
    company: clean(companyFromSchema || domCompany?.innerText || ''),
    location: clean(locationParts.join(' · ') || domLocation?.innerText || ''),
    description: clean([salary, description].filter(Boolean).join(' · ')),
  };
})()
"""
