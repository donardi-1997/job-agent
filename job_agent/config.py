from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchPreferences:
	"""User-controlled filters for Computrabajo job discovery."""

	keywords: tuple[str, ...] = (
		"backend developer",
		"python developer",
		"aws developer",
		"ai engineer",
		"software engineer",
	)
	locations: tuple[str, ...] = ("Colombia",)
	remote_ok: bool = True
	min_score: int = 60
	prepare_application_score: int = 85
	min_monthly_salary_cop: int = 4_000_000
	max_required_experience_years: int = 5
	excluded_terms: tuple[str, ...] = ("english c1", "inglés c1")
	auto_fill: bool = True
	auto_submit: bool = True

	def __post_init__(self) -> None:
		if not 0 <= self.min_score <= 100:
			raise ValueError("min_score must be between 0 and 100")
		if not self.min_score <= self.prepare_application_score <= 100:
			raise ValueError("prepare_application_score must be between min_score and 100")
		if self.min_monthly_salary_cop < 0:
			raise ValueError("min_monthly_salary_cop must be non-negative")


@dataclass(frozen=True)
class CandidateProfile:
	"""Candidate data used by the deterministic first-pass matcher."""

	target_roles: tuple[str, ...] = ()
	skills: tuple[str, ...] = ()
	years_experience: float = 0.0
	languages: dict[str, str] = field(default_factory=dict)
	preferred_locations: tuple[str, ...] = ("Colombia",)
	remote_ok: bool = True
	# User-authored context. This influences relevance scoring but is not treated
	# as independently verified proof of a skill or employment fact.
	professional_summary: str = ""
