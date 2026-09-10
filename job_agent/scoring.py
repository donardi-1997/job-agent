from __future__ import annotations

from dataclasses import dataclass

from job_agent.config import CandidateProfile, SearchPreferences


@dataclass(frozen=True)
class JobPosting:
	title: str
	company: str
	location: str
	description: str
	url: str


@dataclass(frozen=True)
class MatchResult:
	score: int
	decision: str
	reasons: tuple[str, ...]


def _normalize(value: str) -> str:
	return " ".join(value.casefold().split())


def score_job(
	job: JobPosting,
	profile: CandidateProfile,
	preferences: SearchPreferences,
) -> MatchResult:
	"""Deterministic first-pass matcher before any LLM-based evaluation."""

	text = _normalize(f"{job.title} {job.description}")
	reasons: list[str] = []

	for excluded in preferences.excluded_terms:
		if _normalize(excluded) in text:
			return MatchResult(0, "ignore", (f"Excluded term found: {excluded}",))

	score = 0

	target_hits = sum(1 for role in profile.target_roles if _normalize(role) in text)
	if target_hits:
		score += min(35, 20 + (target_hits - 1) * 5)
		reasons.append(f"Target role matches: {target_hits}")

	skill_hits = sum(1 for skill in profile.skills if _normalize(skill) in text)
	if profile.skills:
		skill_ratio = skill_hits / len(profile.skills)
		score += round(skill_ratio * 45)
		reasons.append(f"Skill matches: {skill_hits}/{len(profile.skills)}")

	location = _normalize(job.location)
	preferred_location = any(_normalize(item) in location for item in profile.preferred_locations)
	remote = any(term in text or term in location for term in ("remote", "remoto", "teletrabajo"))
	if preferred_location or (profile.remote_ok and remote):
		score += 20
		reasons.append("Location/remote preference matches")

	score = max(0, min(score, 100))

	if score < preferences.min_score:
		decision = "ignore"
	elif score < 75:
		decision = "save"
	elif score < preferences.prepare_application_score:
		decision = "recommend"
	else:
		decision = "prepare"

	return MatchResult(score, decision, tuple(reasons))
