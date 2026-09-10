from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from job_agent.config import CandidateProfile, SearchPreferences
from job_agent.salary_policy import assess_salary_text


PROFESSIONAL_CONTEXT_WEIGHT = 15
PROFESSIONAL_CONTEXT_SIGNAL_CAP = 32
PROFESSIONAL_CONTEXT_MATCH_TARGET = 8

# Remove filler/common CV vocabulary so the professional-description score is
# driven by meaningful domain, stack and responsibility terms rather than prose.
_CONTEXT_STOPWORDS = {
	"about", "also", "and", "are", "como", "con", "del", "desde", "developer", "development",
	"desarrollador", "desarrollo", "donde", "experience", "experiencia", "for", "from", "he", "have",
	"job", "las", "los", "más", "para", "por", "project", "projects", "proyecto", "proyectos", "que",
	"role", "roles", "software", "soy", "the", "trabajo", "una", "uno", "with", "years", "años",
}


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


def _ascii_text(value: str) -> str:
	decomposed = unicodedata.normalize("NFKD", value.casefold())
	return "".join(char for char in decomposed if not unicodedata.combining(char))


def _meaningful_terms(value: str, *, limit: int | None = None) -> tuple[str, ...]:
	"""Extract deterministic bilingual profile/job signals without an LLM."""
	words = re.findall(r"[a-z0-9][a-z0-9.+#/-]*", _ascii_text(value))
	filtered = [
		word
		for word in words
		if len(word) >= 3 and word not in _CONTEXT_STOPWORDS and not word.isdigit()
	]
	counts = Counter(filtered)
	# Repeated terms are usually deliberate emphasis in a user-authored summary;
	# longer terms break ties and tend to be more informative than generic words.
	ranked = sorted(counts, key=lambda word: (-counts[word], -len(word), word))
	if limit is not None:
		ranked = ranked[:limit]
	return tuple(ranked)


def _professional_context_score(summary: str, job_text: str) -> tuple[int, tuple[str, ...], int]:
	profile_terms = _meaningful_terms(summary, limit=PROFESSIONAL_CONTEXT_SIGNAL_CAP)
	if not profile_terms:
		return 0, (), 0
	job_terms = set(_meaningful_terms(job_text))
	matched = tuple(term for term in profile_terms if term in job_terms)
	# Eight meaningful shared signals are enough for the full context component.
	denominator = min(PROFESSIONAL_CONTEXT_MATCH_TARGET, len(profile_terms))
	points = round(min(1.0, len(matched) / denominator) * PROFESSIONAL_CONTEXT_WEIGHT)
	return points, matched, denominator


def score_job(
	job: JobPosting,
	profile: CandidateProfile,
	preferences: SearchPreferences,
) -> MatchResult:
	"""Deterministic first-pass matcher; no LLM is used for scoring."""

	text = _normalize(f"{job.title} {job.description}")
	reasons: list[str] = []

	# Salary is a hard eligibility rule rather than a soft scoring factor. We only
	# reject when the vacancy explicitly advertises a fixed/range maximum below
	# the user's minimum. Missing salary information is not treated as a rejection.
	salary = assess_salary_text(
		f"{job.title} {job.description}",
		preferences.min_monthly_salary_cop,
	)
	if salary.blocked:
		return MatchResult(0, "ignore", (salary.reason, "Regla salarial dura: no postular por debajo del mínimo mensual configurado.",))

	for excluded in preferences.excluded_terms:
		if _normalize(excluded) in text:
			return MatchResult(0, "ignore", (f"Excluded term found: {excluded}",))

	base_score = 0

	target_hits = sum(1 for role in profile.target_roles if _normalize(role) in text)
	if target_hits:
		base_score += min(35, 20 + (target_hits - 1) * 5)
		reasons.append(f"Target role matches: {target_hits}")

	skill_hits = sum(1 for skill in profile.skills if _normalize(skill) in text)
	if profile.skills:
		skill_ratio = skill_hits / len(profile.skills)
		base_score += round(skill_ratio * 45)
		reasons.append(f"Skill matches: {skill_hits}/{len(profile.skills)}")

	location = _normalize(job.location)
	preferred_location = any(_normalize(item) in location for item in profile.preferred_locations)
	remote = any(term in text or term in location for term in ("remote", "remoto", "teletrabajo"))
	if preferred_location or (profile.remote_ok and remote):
		base_score += 20
		reasons.append("Location/remote preference matches")

	base_score = max(0, min(base_score, 100))
	if profile.professional_summary.strip():
		context_points, matched_terms, target = _professional_context_score(profile.professional_summary, text)
		# Once the user provides a professional description, it owns 15% of the
		# total score. The legacy role/skill/location score retains the other 85%.
		score = round(base_score * ((100 - PROFESSIONAL_CONTEXT_WEIGHT) / 100)) + context_points
		reasons.append(
			f"Professional context matches: {len(matched_terms)}/{target} signals (+{context_points}/{PROFESSIONAL_CONTEXT_WEIGHT})"
		)
		if matched_terms:
			reasons.append(f"Context overlap: {', '.join(matched_terms[:6])}")
	else:
		score = base_score

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
