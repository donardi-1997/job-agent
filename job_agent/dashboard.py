from __future__ import annotations

import base64
import binascii
import json
import re
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from job_agent.ai_usage import AIUsageStore
from job_agent.answer_memory import AnswerMemory
from job_agent.computrabajo import (
	AssistedApplicationPreparer,
	BatchApplyRequest,
	BatchApplyRunner,
	ComputrabajoCollector,
	SearchRequest,
)
from job_agent.computrabajo.application import ApplicationDraftOutput
from job_agent.cv_profile import CVProfileService, MAX_CV_BYTES
from job_agent.profile import ProfileStore, UserProfile
from job_agent.storage import JobStore


STATIC_DIR = Path(__file__).with_name("dashboard_static")
STORE = JobStore()
PROFILE_STORE = ProfileStore(STORE.path)
AI_USAGE_STORE = AIUsageStore(STORE.path)
ANSWER_MEMORY = AnswerMemory(STORE.path)
CV_PROFILE = CVProfileService(STORE.path)
COLLECTOR = ComputrabajoCollector(store=STORE)
PREPARER = AssistedApplicationPreparer(store=STORE)
BATCH_RUNNER = BatchApplyRunner(store=STORE, collector=COLLECTOR, preparer=PREPARER)
JOB_DETAIL_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)$")
JOB_STATUS_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/status$")
JOB_PREPARE_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/prepare$")
JOB_DRAFT_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/draft$")
JOB_ATTEMPTS_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/attempts$")


class DashboardHandler(BaseHTTPRequestHandler):
	store = STORE
	profile_store = PROFILE_STORE
	ai_usage_store = AI_USAGE_STORE
	answer_memory = ANSWER_MEMORY
	cv_profile = CV_PROFILE
	collector = COLLECTOR
	preparer = PREPARER
	batch_runner = BATCH_RUNNER

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
		# CV upload uses base64, so allow enough room for an 8 MB binary file plus JSON overhead.
		max_json_bytes = int(MAX_CV_BYTES * 4 / 3) + 262_144
		if length > max_json_bytes:
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
		if filename == "app.js":
			for extra_name in ("costs.js", "automation_control.js", "cv_control.js"):
				extra = STATIC_DIR / extra_name
				if extra.exists():
					body += b"\n\n" + extra.read_bytes()
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _automation_busy(self) -> bool:
		return self.batch_runner.status()["state"] in {"searching", "applying"}

	def _automation_enabled(self) -> bool:
		return self.profile_store.get().automation_enabled

	def do_GET(self) -> None:  # noqa: N802
		parsed = urlparse(self.path)
		static = {
			"/": ("index.html", "text/html; charset=utf-8"),
			"/app.css": ("app.css", "text/css; charset=utf-8"),
			"/application.css": ("application.css", "text/css; charset=utf-8"),
			"/app.js": ("app.js", "text/javascript; charset=utf-8"),
			"/costs.js": ("costs.js", "text/javascript; charset=utf-8"),
			"/automation_control.js": ("automation_control.js", "text/javascript; charset=utf-8"),
			"/cv_control.js": ("cv_control.js", "text/javascript; charset=utf-8"),
		}
		if parsed.path in static:
			self._send_static(*static[parsed.path])
			return
		if parsed.path == "/api/stats":
			self._send_json(self.store.stats())
			return
		if parsed.path == "/api/ai/usage":
			payload = self.ai_usage_store.summary()
			payload["answer_memory"] = self.answer_memory.stats()
			self._send_json(payload)
			return
		if parsed.path == "/api/profile":
			self._send_json(self.profile_store.get().model_dump())
			return
		if parsed.path == "/api/cv":
			self._send_json(self.cv_profile.status())
			return
		if parsed.path == "/api/automation":
			self._send_json({"enabled": self._automation_enabled()})
			return
		if parsed.path == "/api/search/status":
			self._send_json(self.collector.status())
			return
		if parsed.path == "/api/prepare/status":
			self._send_json(self.preparer.status())
			return
		if parsed.path == "/api/batch/status":
			self._send_json(self.batch_runner.status())
			return
		if parsed.path == "/api/batch/history":
			self._send_json(self.store.list_batch_runs())
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
				self._send_json({"error": "Aún no hay respuestas guardadas para esta vacante."}, HTTPStatus.NOT_FOUND)
				return
			self._send_json(draft)
			return
		match = JOB_ATTEMPTS_RE.match(parsed.path)
		if match:
			self._send_json(self.store.list_application_attempts(int(match.group("job_id"))))
			return
		self.send_error(HTTPStatus.NOT_FOUND)

	def do_POST(self) -> None:  # noqa: N802
		parsed = urlparse(self.path)
		try:
			body = self._read_json()
			if parsed.path == "/api/profile":
				if "automation_enabled" not in body:
					body["automation_enabled"] = self.profile_store.get().automation_enabled
				profile = UserProfile.model_validate(body)
				self._send_json(self.profile_store.save(profile).model_dump())
				return
			if parsed.path == "/api/cv":
				filename = body.get("filename")
				encoded = body.get("content_base64")
				if not isinstance(filename, str) or not filename.strip():
					raise ValueError("filename is required")
				if not isinstance(encoded, str) or not encoded:
					raise ValueError("content_base64 is required")
				try:
					content = base64.b64decode(encoded, validate=True)
				except (binascii.Error, ValueError) as exc:
					raise ValueError("El contenido del CV no es base64 válido.") from exc
				result = self.cv_profile.import_bytes(filename, content)
				self._send_json(
					{
						"cv": self.cv_profile.status(),
						"profile": self.profile_store.get().model_dump(),
						"detected_roles": list(result.detected_roles),
						"detected_skills": list(result.detected_skills),
					}
				)
				return
			if parsed.path == "/api/automation":
				enabled = body.get("enabled")
				if not isinstance(enabled, bool):
					self._send_json({"error": "enabled must be a boolean"}, HTTPStatus.BAD_REQUEST)
					return
				profile = self.profile_store.get().model_copy(update={"automation_enabled": enabled})
				self.profile_store.save(profile)
				self._send_json({"enabled": enabled, "message": "Automatización activada." if enabled else "Automatización pausada. Las búsquedas manuales siguen disponibles."})
				return
			if parsed.path == "/api/batch":
				if not self._automation_enabled():
					self._send_json({"error": "La automatización está desactivada. Actívala para ejecutar lotes de auto-postulación."}, HTTPStatus.CONFLICT)
					return
				if self.collector.status()["state"] == "running" or self.preparer.status()["state"] == "running":
					self._send_json({"error": "Hay otra operación de navegador en ejecución."}, HTTPStatus.CONFLICT)
					return
				request = BatchApplyRequest.model_validate(body)
				if not self.batch_runner.start(request):
					self._send_json({"error": "Ya hay un lote en ejecución.", "status": self.batch_runner.status()}, HTTPStatus.CONFLICT)
					return
				self._send_json(self.batch_runner.status(), HTTPStatus.ACCEPTED)
				return
			if parsed.path == "/api/search":
				if self._automation_busy() or self.preparer.status()["state"] == "running":
					self._send_json({"error": "Hay otra operación de navegador en ejecución."}, HTTPStatus.CONFLICT)
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
				for item in draft.questions:
					if item.suggested_answer and not item.requires_user_input:
						self.answer_memory.remember(item.question, item.suggested_answer, source="manual", confidence=100)
				self._send_json(self.store.save_application_draft(job_id, draft.model_dump()))
				return
			match = JOB_PREPARE_RE.match(parsed.path)
			if match:
				if not self._automation_enabled():
					self._send_json({"error": "La automatización está desactivada. Actívala antes de postular automáticamente."}, HTTPStatus.CONFLICT)
					return
				if self._automation_busy() or self.collector.status()["state"] == "running":
					self._send_json({"error": "Hay otra operación de navegador en ejecución."}, HTTPStatus.CONFLICT)
					return
				job_id = int(match.group("job_id"))
				job = self.store.get_job(job_id)
				if not job:
					self._send_json({"error": "Vacante no encontrada."}, HTTPStatus.NOT_FOUND)
					return
				if job.get("status") == "applied":
					self._send_json({"error": "Esta vacante ya figura como postulada."}, HTTPStatus.CONFLICT)
					return
				if not self.preparer.start(job_id):
					self._send_json({"error": "Ya hay una postulación en ejecución.", "status": self.preparer.status()}, HTTPStatus.CONFLICT)
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
