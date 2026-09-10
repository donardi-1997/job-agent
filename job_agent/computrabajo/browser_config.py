from __future__ import annotations


COMPUTRABAJO_ALLOWED_DOMAINS: tuple[str, ...] = (
	"co.computrabajo.com",
	"secure.computrabajo.com",
	"candidato.co.computrabajo.com",
	"accounts.google.com",
)


def allowed_domains() -> list[str]:
	"""Return the narrow allowlist needed for Computrabajo application flows and Google OAuth."""
	return list(COMPUTRABAJO_ALLOWED_DOMAINS)
