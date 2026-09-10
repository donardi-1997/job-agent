from __future__ import annotations

import webbrowser
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from job_agent.computrabajo.applications_sync import (
    ComputrabajoApplicationsStore,
    ComputrabajoApplicationsSync,
)
from job_agent.computrabajo.eligibility import assess_hard_eligibility
from job_agent.enhanced_dashboard import EnhancedDashboardHandler, PREPARE_RE


APPLICATIONS_STORE = ComputrabajoApplicationsStore(
    EnhancedDashboardHandler.store.path,
    job_store=EnhancedDashboardHandler.store,
)
APPLICATIONS_SYNC = ComputrabajoApplicationsSync(APPLICATIONS_STORE)


class SyncDashboardHandler(EnhancedDashboardHandler):
    applications_store = APPLICATIONS_STORE
    applications_sync = APPLICATIONS_SYNC

    def _browser_operation_busy(self) -> bool:
        return (
            self.batch_runner.status()["state"] in {"searching", "applying"}
            or self.collector.status()["state"] == "running"
            or self.preparer.status()["state"] == "running"
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/computrabajo/applications":
            items = self.applications_store.list_combined()
            verified = sum(1 for item in items if item.get("verified_in_computrabajo"))
            self._send_json(
                {
                    "items": items,
                    "count": len(items),
                    "verified_in_computrabajo": verified,
                    "sync": self.applications_sync.status(),
                }
            )
            return
        if parsed.path == "/api/computrabajo/applications/sync/status":
            self._send_json(self.applications_sync.status())
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        sync_running = self.applications_sync.status().get("state") == "running"

        if parsed.path == "/api/computrabajo/applications/sync":
            if self._browser_operation_busy():
                self._send_json(
                    {"error": "Hay otra operación de navegador en ejecución. Espera a que termine antes de sincronizar."},
                    HTTPStatus.CONFLICT,
                )
                return
            if not self.applications_sync.start():
                self._send_json(
                    {"error": "La sincronización de postulaciones ya está en ejecución.", "status": self.applications_sync.status()},
                    HTTPStatus.CONFLICT,
                )
                return
            self._send_json(self.applications_sync.status(), HTTPStatus.ACCEPTED)
            return

        # Actual dashboard entry point: enforce the complete hard-eligibility policy
        # before EnhancedDashboard starts either deterministic or AI browser work.
        prepare_match = PREPARE_RE.match(parsed.path)
        if prepare_match:
            job_id = int(prepare_match.group("job_id"))
            job = self.store.get_job(job_id)
            if job:
                assessment = assess_hard_eligibility(job, self.profile_store.get())
                if assessment.blocked:
                    self._send_json(
                        {
                            "error": assessment.reason,
                            "code": assessment.code,
                            "hard_rule": True,
                        },
                        HTTPStatus.CONFLICT,
                    )
                    return

        # The persistent Chrome profile must not be driven concurrently by a
        # synchronization and another search/application operation.
        if sync_running and (
            parsed.path in {"/api/search", "/api/batch"}
            or (parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/prepare"))
        ):
            self._send_json(
                {"error": "Mis postulaciones se están sincronizando con Computrabajo. Espera a que termine."},
                HTTPStatus.CONFLICT,
            )
            return
        super().do_POST()


def run_dashboard(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), SyncDashboardHandler)
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
