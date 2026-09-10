from pathlib import Path

import pytest

from job_agent.computrabajo.collector import ComputrabajoCollector, ExtractedJob, SearchOutput, SearchRequest
from job_agent.computrabajo.deterministic import (
    DeterministicJob,
    DeterministicSearchResult,
    SearchExecutionStore,
    build_search_url,
    is_safe_computrabajo_url,
    search_keyword_variants,
)
from job_agent.storage import JobStore


def test_build_search_url_is_deterministic_and_slugged() -> None:
    assert build_search_url("Full Stack Developer", "Colombia") == (
        "https://co.computrabajo.com/trabajo-de-full-stack-developer"
    )
    assert build_search_url("Python Developer", "Bogotá D.C.") == (
        "https://co.computrabajo.com/trabajo-de-python-developer-en-bogota-dc"
    )


def test_search_keyword_variants_broaden_precise_titles_before_ai() -> None:
    assert search_keyword_variants("Node.js Developer") == ("Node.js Developer", "Node.js")
    assert search_keyword_variants("Python Backend Developer") == (
        "Python Backend Developer",
        "Python Backend",
        "Python",
    )
    assert search_keyword_variants("DevOps Engineer") == ("DevOps Engineer", "DevOps")


def test_deterministic_navigation_accepts_only_computrabajo_https() -> None:
    assert is_safe_computrabajo_url("https://co.computrabajo.com/trabajo-de-python") is True
    assert is_safe_computrabajo_url("http://co.computrabajo.com/trabajo-de-python") is False
    assert is_safe_computrabajo_url("https://accounts.google.com/signin") is False
    assert is_safe_computrabajo_url("https://co.computrabajo.com.evil.test/job") is False


def test_search_execution_store_reports_ai_avoidance_rate(tmp_path: Path) -> None:
    store = SearchExecutionStore(tmp_path / "jobs.db")
    store.record(keyword="Python", location="Colombia", mode="deterministic", found=8)
    store.record(keyword="AWS", location="Colombia", mode="deterministic", found=6)
    store.record(keyword="React", location="Colombia", mode="ai_fallback", found=5, fallback_reason="DOM changed")

    stats = store.summary()

    assert stats["total"] == 3
    assert stats["deterministic"] == 2
    assert stats["ai_fallback"] == 1
    assert stats["jobs_found"] == 19
    assert stats["deterministic_rate"] == 66.7


@pytest.mark.asyncio
async def test_collector_uses_deterministic_results_without_ai(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    collector = ComputrabajoCollector(store=store, profile_dir=tmp_path / "browser")

    class LocalSearch:
        async def collect(self, **_: object) -> DeterministicSearchResult:
            return DeterministicSearchResult(
                jobs=(
                    DeterministicJob(
                        title="Python Backend Developer",
                        company="Example SAS",
                        location="Bogotá, Colombia",
                        description="Python FastAPI AWS backend role",
                        url="https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-backend-ABC123",
                    ),
                ),
                search_url="https://co.computrabajo.com/trabajo-de-python-backend-developer",
            )

    async def ai_must_not_run(_: SearchRequest) -> SearchOutput:
        raise AssertionError("AI fallback should not run when deterministic extraction succeeds")

    collector.deterministic_search = LocalSearch()  # type: ignore[assignment]
    collector._collect_with_ai = ai_must_not_run  # type: ignore[method-assign]

    output = await collector._collect(SearchRequest(keyword="Python Backend Developer", max_results=10))

    assert len(output.jobs) == 1
    assert output.jobs[0].title == "Python Backend Developer"
    assert collector.last_collection_info()["mode"] == "deterministic"
    assert collector.search_efficiency()["deterministic"] == 1
    assert collector.search_efficiency()["ai_fallback"] == 0


@pytest.mark.asyncio
async def test_collector_uses_ai_only_when_local_extraction_has_zero_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JobStore(tmp_path / "jobs.db")
    collector = ComputrabajoCollector(store=store, profile_dir=tmp_path / "browser")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-key")

    class EmptyLocalSearch:
        async def collect(self, **_: object) -> DeterministicSearchResult:
            return DeterministicSearchResult(
                jobs=(),
                search_url="https://co.computrabajo.com/trabajo-de-python",
                reason="DOM changed",
            )

    async def fake_ai(_: SearchRequest) -> SearchOutput:
        return SearchOutput(
            jobs=[
                ExtractedJob(
                    title="Python Developer",
                    company="Fallback SAS",
                    location="Colombia",
                    description="Python role",
                    url="https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-XYZ789",
                )
            ]
        )

    collector.deterministic_search = EmptyLocalSearch()  # type: ignore[assignment]
    collector._collect_with_ai = fake_ai  # type: ignore[method-assign]

    output = await collector._collect(SearchRequest(keyword="Python Developer", max_results=10))

    assert len(output.jobs) == 1
    assert collector.last_collection_info() == {"mode": "ai_fallback", "fallback_reason": "DOM changed"}
    assert collector.search_efficiency()["deterministic"] == 0
    assert collector.search_efficiency()["ai_fallback"] == 1
