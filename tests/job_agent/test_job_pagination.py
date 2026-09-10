from pathlib import Path

import pytest

from job_agent.job_pagination import paginate_jobs
from job_agent.storage import JobRecord, JobStore


def _seed_jobs(store: JobStore, count: int = 25) -> None:
    records = []
    for index in range(count):
        score = 100 - index
        records.append(
            JobRecord(
                id=None,
                source="computrabajo",
                external_id=f"job-{index:02d}",
                title=f"Job {index:02d}",
                company="Example SAS",
                location="Colombia",
                url=f"https://co.computrabajo.com/job-{index:02d}",
                score=score,
                band="prepare" if score >= 85 else "recommend",
                status="saved" if index % 2 == 0 else "discovered",
            )
        )
    store.upsert_jobs(records)


def test_paginate_jobs_returns_stable_second_page(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    _seed_jobs(store)

    payload = paginate_jobs(store, page=2, page_size=10)

    assert payload["total"] == 25
    assert payload["pages"] == 3
    assert payload["page"] == 2
    assert payload["start"] == 11
    assert payload["end"] == 20
    assert payload["has_previous"] is True
    assert payload["has_next"] is True
    assert [item["title"] for item in payload["items"]] == [f"Job {index:02d}" for index in range(10, 20)]


def test_paginate_jobs_filters_before_counting_and_paging(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    _seed_jobs(store)

    payload = paginate_jobs(store, page=1, page_size=5, min_score=90, status="saved")

    assert payload["total"] == 5
    assert payload["pages"] == 1
    assert len(payload["items"]) == 5
    assert all(item["score"] >= 90 for item in payload["items"])
    assert all(item["status"] == "saved" for item in payload["items"])


def test_paginate_jobs_clamps_page_after_filters_reduce_results(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    _seed_jobs(store, 12)

    payload = paginate_jobs(store, page=99, page_size=10, min_score=95)

    assert payload["total"] == 6
    assert payload["page"] == 1
    assert payload["pages"] == 1
    assert payload["start"] == 1
    assert payload["end"] == 6


def test_paginate_jobs_validates_bounds(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")

    with pytest.raises(ValueError, match="page must"):
        paginate_jobs(store, page=0)
    with pytest.raises(ValueError, match="page_size"):
        paginate_jobs(store, page_size=101)
    with pytest.raises(ValueError, match="min_score"):
        paginate_jobs(store, min_score=101)
