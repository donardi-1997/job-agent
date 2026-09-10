from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any, TypeVar


T = TypeVar("T")


class AsyncRuntime:
    """Long-lived asyncio loop for browser/subprocess work.

    Browser Use and Chromium create subprocess/CDP transports on Windows. Repeatedly
    wrapping those operations in asyncio.run() destroys the event loop immediately
    after every job, which can leave Proactor pipe callbacks with a closed loop.
    Keeping one loop alive for the lifetime of Job Agent gives those transports time
    to finish their normal cleanup and avoids the repeated closed-pipe finalizers.
    """

    def __init__(self, *, thread_name: str = "job-agent-async-runtime") -> None:
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(
            target=self._run_loop,
            name=thread_name,
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        self._ready.wait()
        if self._loop is None or self._loop.is_closed() or self._closed.is_set():
            raise RuntimeError("Job Agent async runtime is closed.")
        return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self._closed.set()

    def submit(self, coroutine: Coroutine[Any, Any, T]) -> Future[T]:
        if not asyncio.iscoroutine(coroutine):
            raise TypeError("submit() requires a coroutine object")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def run(self, coroutine: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
        """Run a coroutine on the persistent loop and block the caller for its result."""
        return self.submit(coroutine).result(timeout=timeout)

    def shutdown(self, *, timeout: float = 2.0) -> None:
        loop = self._loop
        if loop is None or loop.is_closed() or self._closed.is_set():
            return
        loop.call_soon_threadsafe(loop.stop)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=timeout)


_runtime: AsyncRuntime | None = None
_runtime_lock = threading.Lock()


def get_async_runtime() -> AsyncRuntime:
    global _runtime
    if _runtime is None or _runtime._closed.is_set():
        with _runtime_lock:
            if _runtime is None or _runtime._closed.is_set():
                _runtime = AsyncRuntime()
    return _runtime


def run_async(coroutine: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
    return get_async_runtime().run(coroutine, timeout=timeout)


def _shutdown_runtime() -> None:
    if _runtime is not None:
        _runtime.shutdown()


atexit.register(_shutdown_runtime)
