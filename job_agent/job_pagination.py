from __future__ import annotations

import math
from typing import Any

from job_agent.storage import JobStore


def paginate_jobs(
    store: JobStore,
    *,
    page: int = 1,
    page_size: int = 10,
    min_score: int = 0,
    status: str | None = None,
) -> dict[str, Any]:
    """Return a stable, filtered page of locally stored vacancies.

    This is intentionally separate from ``JobStore.list_jobs`` so existing callers
    keep their current list contract while the dashboard can use a paginated API.
    """
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if not 0 <= min_score <= 100:
        raise ValueError("min_score must be between 0 and 100")

    where = ["score >= ?"]
    params: list[object] = [min_score]
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = " AND ".join(where)

    with store.connect() as connection:
        count_row = connection.execute(
            f"SELECT COUNT(*) FROM jobs WHERE {where_sql}",
            params,
        ).fetchone()
        total = int(count_row[0]) if count_row else 0
        pages = max(1, math.ceil(total / page_size))
        effective_page = min(page, pages) if total else 1
        offset = (effective_page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT * FROM jobs
            WHERE {where_sql}
            ORDER BY score DESC, created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
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
