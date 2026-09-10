from __future__ import annotations

import browser_use.browser.profile as browser_use_profile


COMPUTRABAJO_ALLOWED_DOMAINS: tuple[str, ...] = (
	"co.computrabajo.com",
	"secure.computrabajo.com",
	"candidato.co.computrabajo.com",
	"accounts.google.com",
)

# Browser Use 0.13.10 still ships this Chrome switch in CHROME_DEFAULT_ARGS,
# but current stable Chrome on Windows rejects it and shows a persistent
# unsupported-command-line banner. Job Agent does not need extensions to run on
# chrome:// pages, so remove only this incompatible switch at integration startup.
UNSUPPORTED_BROWSER_USE_CHROME_ARGS: tuple[str, ...] = (
	"--extensions-on-chrome-urls",
)


def sanitize_browser_use_chrome_args() -> None:
	"""Remove Chrome switches rejected by the user's current stable browser."""
	for arg in UNSUPPORTED_BROWSER_USE_CHROME_ARGS:
		while arg in browser_use_profile.CHROME_DEFAULT_ARGS:
			browser_use_profile.CHROME_DEFAULT_ARGS.remove(arg)


# Apply before any Browser profile is instantiated by search/application runners.
sanitize_browser_use_chrome_args()


def allowed_domains() -> list[str]:
	"""Return the narrow allowlist needed for Computrabajo application flows and Google OAuth."""
	return list(COMPUTRABAJO_ALLOWED_DOMAINS)
