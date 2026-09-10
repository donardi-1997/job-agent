from __future__ import annotations

import asyncio
import threading

from job_agent.async_runtime import AsyncRuntime, run_async


def test_async_runtime_reuses_one_event_loop() -> None:
    runtime = AsyncRuntime(thread_name="test-job-agent-async-runtime")

    async def identify() -> tuple[int, str]:
        await asyncio.sleep(0)
        return id(asyncio.get_running_loop()), threading.current_thread().name

    try:
        first_loop, first_thread = runtime.run(identify())
        second_loop, second_thread = runtime.run(identify())
    finally:
        runtime.shutdown()

    assert first_loop == second_loop
    assert first_thread == "test-job-agent-async-runtime"
    assert second_thread == first_thread
    assert runtime.closed is True


def test_async_runtime_propagates_coroutine_result() -> None:
    runtime = AsyncRuntime(thread_name="test-job-agent-result-runtime")

    async def calculate() -> int:
        await asyncio.sleep(0)
        return 42

    try:
        assert runtime.run(calculate()) == 42
    finally:
        runtime.shutdown()


def test_computrabajo_workers_route_asyncio_run_to_persistent_runtime() -> None:
    import job_agent.computrabajo.application as application_module
    import job_agent.computrabajo.batch as batch_module
    import job_agent.computrabajo.collector as collector_module

    assert application_module.asyncio.run is run_async
    assert batch_module.asyncio.run is run_async
    assert collector_module.asyncio.run is run_async
