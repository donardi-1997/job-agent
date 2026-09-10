from __future__ import annotations


COMPUTRABAJO_ALLOWED_DOMAINS: tuple[str, ...] = (
	"co.computrabajo.com",
	"secure.computrabajo.com",
	"accounts.google.com",
)


def allowed_domains() -> list[str]:
	"""Return the narrow allowlist needed for Computrabajo and its Google OAuth flow."""
	return list(COMPUTRABAJO_ALLOWED_DOMAINS)
