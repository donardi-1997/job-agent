from job_agent.computrabajo.browser_config import COMPUTRABAJO_ALLOWED_DOMAINS, allowed_domains


def test_computrabajo_browser_allowlist_is_narrow_and_supports_google_oauth() -> None:
	assert COMPUTRABAJO_ALLOWED_DOMAINS == (
		"co.computrabajo.com",
		"secure.computrabajo.com",
		"candidato.co.computrabajo.com",
		"accounts.google.com",
	)
	assert allowed_domains() == list(COMPUTRABAJO_ALLOWED_DOMAINS)
	assert "google.com" not in COMPUTRABAJO_ALLOWED_DOMAINS
	assert "*.google.com" not in COMPUTRABAJO_ALLOWED_DOMAINS
	assert "*.computrabajo.com" not in COMPUTRABAJO_ALLOWED_DOMAINS
