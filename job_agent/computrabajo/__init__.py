"""Computrabajo integration for the local Job Agent application."""

from __future__ import annotations

import importlib
import sys

from job_agent.async_runtime import run_async


class _PersistentAsyncioRunAdapter:
    """Route legacy worker asyncio.run() calls through the persistent runtime."""

    run = staticmethod(run_async)


_EXPORTS: dict[str, tuple[str, str]] = {
    "AssistedApplicationPreparer": (
        "job_agent.computrabajo.smart_application",
        "SmartApplicationPreparer",
    ),
    "BatchApplyRequest": ("job_agent.computrabajo.batch", "BatchApplyRequest"),
    "BatchApplyRunner": ("job_agent.computrabajo.batch", "BatchApplyRunner"),
    "BatchApplyStatus": ("job_agent.computrabajo.batch", "BatchApplyStatus"),
    "ComputrabajoCollector": ("job_agent.computrabajo.collector", "ComputrabajoCollector"),
    "PreparationStatus": ("job_agent.computrabajo.application", "PreparationStatus"),
    "SearchRequest": ("job_agent.computrabajo.collector", "SearchRequest"),
    "SearchRunStatus": ("job_agent.computrabajo.collector", "SearchRunStatus"),
}


def _patch_runtime_modules() -> None:
    for module_name in (
        "job_agent.computrabajo.application",
        "job_agent.computrabajo.batch",
        "job_agent.computrabajo.collector",
    ):
        module = sys.modules.get(module_name)
        if module is not None:
            module.asyncio = _PersistentAsyncioRunAdapter


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    module = importlib.import_module(module_name)
    _patch_runtime_modules()
    value = getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = list(_EXPORTS)
