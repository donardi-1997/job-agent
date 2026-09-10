import browser_use.browser.profile as browser_use_profile

from job_agent.computrabajo.browser_config import (
	COMPUTRABAJO_ALLOWED_DOMAINS,
	UNSUPPORTED_BROWSER_USE_CHROME_ARGS,
	allowed_domains,
	sanitize_browser_use_chrome_args,
)


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


def test_unsupported_chrome_flag_is_removed_from_browser_use_defaults() -> None:
	# The sanitizer is intentionally idempotent so repeated imports/startups remain safe.
	sanitize_browser_use_chrome_args()
	sanitize_browser_use_chrome_args()

	for arg in UNSUPPORTED_BROWSER_USE_CHROME_ARGS:
		assert arg not in browser_use_profile.CHROME_DEFAULT_ARGS
