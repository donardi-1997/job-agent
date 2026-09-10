from __future__ import annotations

import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from job_agent.storage import JobStore


STATIC_DIR = Path(__file__).with_name("dashboard_static")


class DashboardHandler(BaseHTTPRequestHandler):
	store = JobStore()

	def _send_json(self, payload: object, status: int = HTTPStatus.OK) -> None:
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _send_static(self, filename: str, content_type: str) -> None:
		path = STATIC_DIR / filename
		if not path.exists():
			self.send_error(HTTPStatus.NOT_FOUND)
			return
		body = path.read_bytes()
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self) -> None:  # noqa: N802
		parsed = urlparse(self.path)
		if parsed.path == "/":
			self._send_static("index.html", "text/html; charset=utf-8")
			return
		if parsed.path == "/app.css":
			self._send_static("app.css", "text/css; charset=utf-8")
			return
		if parsed.path == "/app.js":
			self._send_static("app.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/api/stats":
			self._send_json(self.store.stats())
			return
		if parsed.path == "/api/jobs":
			query = parse_qs(parsed.query)
			min_score = max(0, min(100, int(query.get("min_score", ["0"])[0])))
			status = query.get("status", [None])[0] or None
			self._send_json(self.store.list_jobs(min_score=min_score, status=status))
			return
		self.send_error(HTTPStatus.NOT_FOUND)

	def log_message(self, format: str, *args: object) -> None:
		return


def run_dashboard(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> None:
	server = ThreadingHTTPServer((host, port), DashboardHandler)
	url = f"http://{host}:{port}"
	print(f"Job Agent dashboard running at {url}")
	if open_browser:
		webbrowser.open(url)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()
