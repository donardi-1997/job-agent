from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest

from job_agent.dashboard import DashboardHandler, STATIC_DIR


@pytest.mark.parametrize(
	("path", "filename", "content_type"),
	[
		("/ux.css", "ux.css", "text/css; charset=utf-8"),
		("/ux.js", "ux.js", "text/javascript; charset=utf-8"),
	],
)
def test_dashboard_serves_progressive_ux_assets(
	path: str,
	filename: str,
	content_type: str,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	handler = object.__new__(DashboardHandler)
	handler.path = path
	served: list[tuple[str, str]] = []

	monkeypatch.setattr(handler, "_send_static", lambda name, mime: served.append((name, mime)))
	monkeypatch.setattr(
		handler,
		"send_error",
		lambda status, *args, **kwargs: pytest.fail(f"unexpected HTTP error: {status}"),
	)

	handler.do_GET()

	assert served == [(filename, content_type)]
	assert (STATIC_DIR / filename).is_file()


def test_dashboard_index_loads_progressive_ux_assets() -> None:
	index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

	assert '<link rel="stylesheet" href="/ux.css">' in index
	assert '<script src="/ux.js"></script>' in index
