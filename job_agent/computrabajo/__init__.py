"""Computrabajo integration for the local Job Agent application."""

import sys

from job_agent.async_runtime import run_async
from job_agent.computrabajo.application import PreparationStatus
from job_agent.computrabajo.batch import BatchApplyRequest, BatchApplyRunner, BatchApplyStatus
from job_agent.computrabajo.collector import ComputrabajoCollector, SearchRequest, SearchRunStatus
from job_agent.computrabajo.cost_aware_application import CostAwareApplicationPreparer as AssistedApplicationPreparer


class _PersistentAsyncioRunAdapter:
    """Keep legacy module calls on Job Agent's long-lived browser event loop.

    collector.py, application.py and batch.py historically call asyncio.run() from
    worker threads. On Windows that closes the Proactor loop immediately after each
    Chromium/CDP operation and can leave pipe transports finalizing against a closed
    loop. Until those workers are fully converted to async services, route only their
    module-local ``asyncio.run`` calls through the persistent runtime. This does not
    monkey-patch the stdlib asyncio module globally.
    """

    run = staticmethod(run_async)


for _module_name in (
    "job_agent.computrabajo.application",
    "job_agent.computrabajo.batch",
    "job_agent.computrabajo.collector",
):
    _module = sys.modules.get(_module_name)
    if _module is not None:
        _module.asyncio = _PersistentAsyncioRunAdapter


__all__ = [
    "AssistedApplicationPreparer",
    "BatchApplyRequest",
    "BatchApplyRunner",
    "BatchApplyStatus",
    "ComputrabajoCollector",
    "PreparationStatus",
    "SearchRequest",
    "SearchRunStatus",
]
