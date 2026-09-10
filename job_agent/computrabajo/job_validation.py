from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from job_agent.storage import DEFAULT_DB_PATH


COMPUTRABAJO_JOB_HOST = "co.computrabajo.com"
COMPUTRABAJO_JOB_PATH_TOKEN = "/ofertas-de-trabajo/oferta-de-trabajo-de-"

_ERROR_TITLE_MARKERS = (
    "403 forbidden",
    "forbidden",
    "access denied",
    "acceso denegado",
    "404 not found",
    "not found",
    "too many redirects",
    "err_too_many_redirects",
    "internal server error",
    "service unavailable",
)


def _normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def invalid_computrabajo_job_reason(*, title: object, url: object, description: object = "") -> str:
    """Return why a record cannot be considered a real Computrabajo vacancy.

    This is intentionally strict: discovery records must point to the canonical
    public vacancy route and must not represent browser/server error pages.
    """
    raw_url = str(url or "").strip()
    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or parsed.hostname != COMPUTRABAJO_JOB_HOST:
        return "URL fuera del host público de vacantes de Computrabajo."
    if COMPUTRABAJO_JOB_PATH_TOKEN not in parsed.path:
        return "URL no corresponde a una vacante canónica de Computrabajo."

    normalized_title = _normalize(title)
    if not normalized_title:
        return "La vacante no tiene título."
    if any(marker == normalized_title or normalized_title.startswith(f"{marker} ") for marker in _ERROR_TITLE_MARKERS):
        return f"Título de página de error detectado: {str(title or '').strip()}"

    normalized_description = _normalize(description)
    # Only reject description text when it is clearly the whole error page. Do
    # not reject legitimate job descriptions that merely mention an HTTP code.
    if normalized_description and len(normalized_description) < 500:
        if normalized_description.startswith(("403 forbidden", "access denied", "acceso denegado", "err_too_many_redirects")):
            return "Contenido de página de error detectado en la descripción."
    return ""


def is_valid_computrabajo_job(*, title: object, url: object, description: object = "") -> bool:
    return not invalid_computrabajo_job_reason(title=title, url=url, description=description)


def purge_invalid_computrabajo_jobs(path: Path | str = DEFAULT_DB_PATH) -> int:
    """Delete historical error-page records and their local child data.

    We explicitly clean child tables because SQLite foreign key cascades are not
    guaranteed to be enabled on every existing local connection.
    """
    db_path = Path(path)
    if not db_path.exists():
        return 0

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        existing_tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "jobs" not in existing_tables:
            return 0
        rows = connection.execute(
            "SELECT id, title, url, description FROM jobs WHERE source = 'computrabajo'"
        ).fetchall()
        invalid_ids = [
            int(row["id"])
            for row in rows
            if not is_valid_computrabajo_job(
                title=row["title"],
                url=row["url"],
                description=row["description"],
            )
        ]
        if not invalid_ids:
            return 0

        placeholders = ",".join("?" for _ in invalid_ids)
        child_tables = (
            "application_attempts",
            "application_drafts",
            "application_contacts",
            "application_execution_log",
        )
        for table in child_tables:
            if table in existing_tables:
                connection.execute(f"DELETE FROM {table} WHERE job_id IN ({placeholders})", invalid_ids)
        connection.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", invalid_ids)
        return len(invalid_ids)
