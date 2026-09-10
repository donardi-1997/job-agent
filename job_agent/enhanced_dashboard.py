from __future__ import annotations

import json
import os
import re
import webbrowser
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from job_agent.credentials import CredentialStore
from job_agent.dashboard import DashboardHandler, STATIC_DIR
from job_agent.followup import ContactTracker, ContactUpdate
from job_agent.job_pagination import paginate_jobs
from job_agent.profile import UserProfile
from job_agent.search_terms import build_personal_search_terms


CONTACT_RE = re.compile(r"^/api/jobs/(?P<job_id>\d+)/contact$")
CONTACT_TRACKER = ContactTracker(DashboardHandler.store.path)
CREDENTIAL_STORE = CredentialStore(DashboardHandler.store.path)
DEFAULT_USD_COP_RATE = 4000.0


def _usd_cop_rate() -> float:
	try:
		rate = float(os.getenv("JOB_AGENT_USD_COP_RATE", str(DEFAULT_USD_COP_RATE)))
		return rate if rate > 0 else DEFAULT_USD_COP_RATE
	except ValueError:
		return DEFAULT_USD_COP_RATE


class EnhancedDashboardHandler(DashboardHandler):
	contact_tracker = CONTACT_TRACKER
	credential_store = CREDENTIAL_STORE

	def _send_static(self, filename: str, content_type: str) -> None:
		path = STATIC_DIR / filename
		if not path.exists():
			self.send_error(HTTPStatus.NOT_FOUND)
			return
		body = path.read_bytes()
		if filename == "app.js":
			for extra_name in (
				"costs.js",
				"automation_control.js",
				"cv_control.js",
				"profile_summary_control.js",
				"search_plan_control.js",
				"application_efficiency.js",
				"application_workflow.js",
				"pagination_control.js",
				"contact_tracking.js",
				"credentials_control.js",
			):
				extra = STATIC_DIR / extra_name
				if extra.exists():
					body += b"\n\n" + extra.read_bytes()
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _is_loopback_client(self) -> bool:
		return self.client_address[0] in {"127.0.0.1", "::1"}

	def do_GET(self) -> None:  # noqa: N802
		parsed = urlparse(self.path)
		if parsed.path == "/contact_tracking.js":
			self._send_static("contact_tracking.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/credentials_control.js":
			self._send_static("credentials_control.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/profile_summary_control.js":
			self._send_static("profile_summary_control.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/search_plan_control.js":
			self._send_static("search_plan_control.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/application_efficiency.js":
			self._send_static("application_efficiency.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/application_workflow.js":
			self._send_static("application_workflow.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/pagination_control.js":
			self._send_static("pagination_control.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/api/search/plan":
			profile = self.profile_store.get()
			terms = build_personal_search_terms(profile, limit=8)
			self._send_json({
				"terms": terms,
				"skills_count": len(profile.skills),
				"roles_count": len(profile.target_roles),
				"generator": "deterministic",
				"uses_ai": False,
			})
			return
		if parsed.path == "/api/search/efficiency":
			payload = self.collector.search_efficiency()
			payload["strategy"] = "deterministic_first"
			payload["ai_is_fallback"] = True
			self._send_json(payload)
			return
		if parsed.path == "/api/application/efficiency":
			payload = self.preparer.application_efficiency()
			payload["strategy"] = "deterministic_first"
			payload["ai_is_fallback"] = True
			self._send_json(payload)
			return
		if parsed.path == "/api/jobs":
			query = parse_qs(parsed.query)
			if "page" in query or "page_size" in query:
				try:
					page = int(query.get("page", ["1"])[0])
					page_size = int(query.get("page_size", ["10"])[0])
					min_score = int(query.get("min_score", ["0"])[0])
					status = query.get("status", [None])[0] or None
					payload = paginate_jobs(
						self.store,
						page=page,
						page_size=page_size,
						min_score=min_score,
						status=status,
					)
				except ValueError as exc:
					self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
					return
				self._send_json(payload)
				return
		if parsed.path == "/api/currency":
			rate = _usd_cop_rate()
			self._send_json({
				"display_currency": "COP",
				"usd_cop_rate": rate,
				"source": "JOB_AGENT_USD_COP_RATE",
				"note": "Tasa configurable localmente; los costos base se conservan en USD.",
			})
			return
		if parsed.path == "/api/contact/stats":
			self._send_json(self.contact_tracker.stats())
			return
		if parsed.path == "/api/computrabajo/credentials":
			self._send_json(self.credential_store.computrabajo_status())
			return
		match = CONTACT_RE.match(parsed.path)
		if match:
			job_id = int(match.group("job_id"))
			if not self.store.get_job(job_id):
				self._send_json({"error": "Vacante no encontrada."}, HTTPStatus.NOT_FOUND)
				return
			self._send_json(self.contact_tracker.get(job_id))
			return
		super().do_GET()

	def do_POST(self) -> None:  # noqa: N802
		parsed = urlparse(self.path)
		if parsed.path == "/api/profile/summary":
			try:
				body = self._read_json()
				summary = body.get("professional_summary")
				if not isinstance(summary, str):
					raise ValueError("professional_summary must be a string")
				current = self.profile_store.get()
				profile = UserProfile.model_validate({**current.model_dump(), "professional_summary": summary})
				self.profile_store.save(profile)
				rescored = self.collector.rescore_existing_jobs()
				self._send_json({
					"professional_summary": profile.professional_summary,
					"chars": len(profile.professional_summary),
					"rescored_jobs": rescored,
					"message": f"Descripción profesional guardada. {rescored} vacantes recalculadas localmente.",
				})
			except (ValidationError, ValueError, json.JSONDecodeError) as exc:
				self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
			return
		if parsed.path == "/api/profile":
			try:
				body = self._read_json()
				current = self.profile_store.get()
				body.setdefault("automation_enabled", current.automation_enabled)
				body.setdefault("professional_summary", current.professional_summary)
				profile = UserProfile.model_validate(body)
				saved = self.profile_store.save(profile)
				self.collector.rescore_existing_jobs()
				self._send_json(saved.model_dump())
			except (ValidationError, ValueError, json.JSONDecodeError) as exc:
				self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
			return
		if parsed.path == "/api/computrabajo/credentials":
			if not self._is_loopback_client():
				self._send_json({"error": "Las credenciales solo pueden modificarse desde este PC."}, HTTPStatus.FORBIDDEN)
				return
			try:
				body = self._read_json()
				username = str(body.get("username") or "")
				password = str(body.get("password") or "")
				self._send_json(self.credential_store.save_computrabajo(username, password))
			except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
				self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
			return
		if parsed.path == "/api/computrabajo/credentials/clear":
			if not self._is_loopback_client():
				self._send_json({"error": "Las credenciales solo pueden modificarse desde este PC."}, HTTPStatus.FORBIDDEN)
				return
			self.credential_store.clear_computrabajo()
			self._send_json({"configured": False, "message": "Credenciales eliminadas."})
			return
		match = CONTACT_RE.match(parsed.path)
		if match:
			try:
				body = self._read_json()
				update = ContactUpdate.model_validate(body)
				self._send_json(self.contact_tracker.save(int(match.group("job_id")), update))
			except (ValidationError, ValueError, json.JSONDecodeError) as exc:
				self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
			return
		super().do_POST()


def run_dashboard(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> None:
	server = ThreadingHTTPServer((host, port), EnhancedDashboardHandler)
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
