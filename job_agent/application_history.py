from __future__ import annotations

import math
from typing import Any

from job_agent.storage import JobStore


def list_confirmed_applications(
    store: JobStore,
    *,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """Return jobs with at least one confirmed submitted application attempt.

    TEST attempts are intentionally excluded because they persist with submitted=0.
    When a job has multiple real submissions/confirmations, the latest confirmed
    attempt supplies the displayed application timestamp and confirmation metadata.
    """
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")

    with store.connect() as connection:
        count_row = connection.execute(
            "SELECT COUNT(DISTINCT job_id) FROM application_attempts WHERE submitted = 1"
        ).fetchone()
        total = int(count_row[0]) if count_row else 0
        pages = max(1, math.ceil(total / page_size))
        effective_page = min(page, pages) if total else 1
        offset = (effective_page - 1) * page_size

        rows = connection.execute(
            """
            WITH latest_submissions AS (
                SELECT job_id, MAX(id) AS attempt_id
                FROM application_attempts
                WHERE submitted = 1
                GROUP BY job_id
            )
            SELECT
                j.*,
                a.created_at AS applied_at,
                a.submission_status AS application_status,
                a.confirmation_text AS application_confirmation,
                a.confirmation_url AS application_confirmation_url
            FROM latest_submissions latest
            JOIN application_attempts a ON a.id = latest.attempt_id
            JOIN jobs j ON j.id = latest.job_id
            ORDER BY a.created_at DESC, a.id DESC, j.score DESC, j.id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()

    items = [store._decode_row(row) for row in rows]
    start = offset + 1 if total else 0
    end = min(offset + len(items), total) if total else 0
    return {
        "items": items,
        "page": effective_page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
        "start": start,
        "end": end,
        "has_previous": effective_page > 1,
        "has_next": effective_page < pages,
    }
