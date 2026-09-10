from __future__ import annotations

import json
import re
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from job_agent.computrabajo import AssistedApplicationPreparer, ComputrabajoCollector, SearchRequest
from job_agent.computrabajo.application import ApplicationDraftOutput
from job_agent.profile import ProfileStore, UserProfile
from job_agent.storage import JobStore


STATIC_DIR = Path(__file__).with_name("dashboard_static")
STORE = JobStore()
PROFILE_STORE = ProfileStore(STORE.path)
COLLECTOR = ComputrabajoCollector(store=STORE)
PREPARER = AssistedApplicationPreparer(store=STORE)
JOB_DETAIL_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)$")
JOB_STATUS_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/status$")
JOB_PREPARE_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/prepare$")
JOB_DRAFT_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/draft$")


class DashboardHandler(BaseHTTPRequestHandler):
	store = STORE
	profile_store = PROFILE_STORE
	collector = COLLECTOR
	preparer = PREPARER

	def _send_json(self, payload: object, status: int = HTTPStatus.OK) -> None:
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _read_json(self) -> dict[str, object]:
		length = int(self.headers.get("Content-Length", "0"))
		if length <= 0:
			return {}
		if length > 131_072:
			raise ValueError("Request body too large")
		decoded = json.loads(self.rfile.read(length).decode("utf-8"))
		if not isinstance(decoded, dict):
			raise ValueError("JSON body must be an object")
		return decoded

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
		static = {
			"/": ("index.html", "text/html; charset=utf-8"),
			"/app.css": ("app.css", "text/css; charset=utf-8"),
			"/application.css": ("application.css", "text/css; charset=utf-8"),
			"/app.js": ("app.js", "text/javascript; charset=utf-8"),
		}
		if parsed.path in static:
			self._send_static(*static[parsed.path])
			return
		if parsed.path == "/api/stats":
			self._send_json(self.store.stats())
			return
		if parsed.path == "/api/profile":
			self._send_json(self.profile_store.get().model_dump())
			return
		if parsed.path == "/api/search/status":
			self._send_json(self.collector.status())
			return
		if parsed.path == "/api/prepare/status":
			self._send_json(self.preparer.status())
			return
		if parsed.path == "/api/jobs":
			query = parse_qs(parsed.query)
			try:
				min_score = max(0, min(100, int(query.get("min_score", ["0"])[0])))
			except ValueError:
				self._send_json({"error": "min_score must be an integer"}, HTTPStatus.BAD_REQUEST)
				return
			status = query.get("status", [None])[0] or None
			self._send_json(self.store.list_jobs(min_score=min_score, status=status))
			return

		match = JOB_DETAIL_RE.match(parsed.path)
		if match:
			job = self.store.get_job(int(match.group("job_id")))
			if not job:
				self._send_json({"error": "Vacante no encontrada."}, HTTPStatus.NOT_FOUND)
				return
			self._send_json(job)
			return

		match = JOB_DRAFT_RE.match(parsed.path)
		if match:
			draft = self.store.get_application_draft(int(match.group("job_id")))
			if not draft:
				self._send_json({"error": "Aún no hay borrador para esta vacante."}, HTTPStatus.NOT_FOUND)
				return
			self._send_json(draft)
			return
		self.send_error(HTTPStatus.NOT_FOUND)

	def do_POST(self) -> None:  # noqa: N802
		parsed = urlparse(self.path)
		try:
			body = self._read_json()
			if parsed.path == "/api/profile":
				profile = UserProfile.model_validate(body)
				self._send_json(self.profile_store.save(profile).model_dump())
				return
			if parsed.path == "/api/search":
				if self.preparer.status()["state"] == "running":
					self._send_json({"error": "Hay una postulación en preparación. Espera a que termine antes de buscar."}, HTTPStatus.CONFLICT)
					return
				request = SearchRequest.model_validate(body)
				if not self.collector.start(request):
					self._send_json({"error": "Ya hay una búsqueda en ejecución.", "status": self.collector.status()}, HTTPStatus.CONFLICT)
					return
				self._send_json(self.collector.status(), HTTPStatus.ACCEPTED)
				return

			match = JOB_STATUS_RE.match(parsed.path)
			if match:
				job = self.store.update_status(int(match.group("job_id")), str(body.get("status", "")))
				if not job:
					self._send_json({"error": "Vacante no encontrada."}, HTTPStatus.NOT_FOUND)
					return
				self._send_json(job)
				return

			match = JOB_DRAFT_RE.match(parsed.path)
			if match:
				job_id = int(match.group("job_id"))
				draft = ApplicationDraftOutput.model_validate(body)
				self._send_json(self.store.save_application_draft(job_id, draft.model_dump()))
				return

			match = JOB_PREPARE_RE.match(parsed.path)
			if match:
				if self.collector.status()["state"] == "running":
					self._send_json({"error": "Hay una búsqueda en ejecución. Espera a que termine antes de preparar la postulación."}, HTTPStatus.CONFLICT)
					return
				job_id = int(match.group("job_id"))
				if not self.preparer.start(job_id):
					self._send_json({"error": "Ya hay una preparación en ejecución.", "status": self.preparer.status()}, HTTPStatus.CONFLICT)
					return
				self._send_json(self.preparer.status(), HTTPStatus.ACCEPTED)
				return
		except (ValidationError, ValueError, json.JSONDecodeError) as exc:
			self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
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
