from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from job_agent.config import CandidateProfile, SearchPreferences
from job_agent.salary_policy import assess_salary_text


WEIGHTS = {
	"role": 20,
	"skills": 25,
	"experience": 15,
	"cloud_certifications": 15,
	"location": 10,
	"context": 10,
	"freshness": 5,
}

PROFESSIONAL_CONTEXT_SIGNAL_CAP = 32
PROFESSIONAL_CONTEXT_MATCH_TARGET = 8

_CONTEXT_STOPWORDS = {
	"about", "also", "and", "are", "como", "con", "del", "desde", "developer", "development",
	"desarrollador", "desarrollo", "donde", "experience", "experiencia", "for", "from", "he", "have",
	"job", "las", "los", "más", "para", "por", "project", "projects", "proyecto", "proyectos", "que",
	"role", "roles", "software", "soy", "the", "trabajo", "una", "uno", "with", "years", "años",
}

_STRATEGIC_SIGNALS = (
	"aws", "lambda", "api gateway", "dynamodb", "s3", "cognito", "bedrock",
	"rag", "llm", "docker", "github actions", "ci/cd", "serverless",
)
_CERTIFICATION_SIGNALS = (
	"aws certified", "solutions architect", "developer associate", "cloud practitioner",
	"certificacion aws", "certificación aws", "certified",
)


@dataclass(frozen=True)
class JobPosting:
	title: str
	company: str
	location: str
	description: str
	url: str
	first_seen_at: str = ""


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
	words = re.findall(r"[a-z0-9][a-z0-9.+#/-]*", _ascii_text(value))
	filtered = [
		word
		for word in words
		if len(word) >= 3 and word not in _CONTEXT_STOPWORDS and not word.isdigit()
	]
	counts = Counter(filtered)
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
	denominator = min(PROFESSIONAL_CONTEXT_MATCH_TARGET, len(profile_terms))
	points = round(min(1.0, len(matched) / max(1, denominator)) * WEIGHTS["context"])
	return points, matched, denominator


def _role_score(job: JobPosting, profile: CandidateProfile) -> tuple[int, int]:
	title = _normalize(job.title)
	text = _normalize(f"{job.title} {job.description}")
	best = 0
	hits = 0
	for role in profile.target_roles:
		normalized = _normalize(role)
		if not normalized:
			continue
		if normalized in title:
			best = max(best, WEIGHTS["role"])
			hits += 1
			continue
		if normalized in text:
			best = max(best, 16)
			hits += 1
			continue
		role_tokens = {token for token in re.findall(r"[a-z0-9+#.]+", normalized) if len(token) > 2}
		title_tokens = set(re.findall(r"[a-z0-9+#.]+", title))
		if role_tokens and len(role_tokens & title_tokens) / len(role_tokens) >= 0.5:
			best = max(best, 13)
			hits += 1
	return best, hits


def _skill_score(job_text: str, skills: tuple[str, ...]) -> tuple[int, tuple[str, ...]]:
	matched = tuple(skill for skill in skills if _normalize(skill) and _normalize(skill) in job_text)
	# A long CV should not be punished for having many verified skills. Five
	# relevant matches are enough to receive the full skill component.
	target = max(1, min(5, len(skills)))
	points = round(min(1.0, len(matched) / target) * WEIGHTS["skills"])
	return points, matched


def _required_experience_years(text: str) -> float | None:
	normalized = _ascii_text(text)
	patterns = (
		r"(?:minimo|minimum|al menos|required|requisito).{0,60}?(\d+(?:[.,]\d+)?)\s*\+?\s*(?:anos|years)",
		r"(\d+(?:[.,]\d+)?)\s*\+?\s*(?:anos|years).{0,60}?(?:experiencia|experience)",
	)
	values: list[float] = []
	for pattern in patterns:
		for match in re.finditer(pattern, normalized):
			try:
				group = match.group(1)
				values.append(float(group.replace(",", ".")))
			except (ValueError, IndexError):
				continue
	return max(values) if values else None


def _experience_score(job_text: str, profile: CandidateProfile) -> tuple[int, float | None]:
	required = _required_experience_years(job_text)
	if required is None:
		# No explicit experience barrier: do not penalize an otherwise strong match.
		return WEIGHTS["experience"], None
	if profile.years_experience <= 0:
		return 3, required
	if profile.years_experience < required:
		return 0, required
	margin = profile.years_experience - required
	return min(WEIGHTS["experience"], 12 + int(min(3, margin))), required


def _cloud_certification_score(job_text: str, profile: CandidateProfile) -> tuple[int, tuple[str, ...]]:
	profile_text = _normalize(" ".join((*profile.skills, profile.professional_summary)))
	matched = tuple(
		signal
		for signal in _STRATEGIC_SIGNALS
		if signal in job_text and signal in profile_text
	)
	points = min(12, (10 + max(0, len(matched) - 1)) if matched else 0)
	job_requests_cert = any(signal in job_text for signal in _CERTIFICATION_SIGNALS)
	profile_has_cert = any(signal in profile_text for signal in _CERTIFICATION_SIGNALS)
	if job_requests_cert and profile_has_cert:
		points += 3
	return min(WEIGHTS["cloud_certifications"], points), matched


def _location_score(job: JobPosting, profile: CandidateProfile) -> int:
	location = _normalize(job.location)
	text = _normalize(f"{job.title} {job.description} {job.location}")
	preferred = any(_normalize(item) in location for item in profile.preferred_locations if _normalize(item))
	remote = any(term in text for term in ("remote", "remoto", "teletrabajo", "home office"))
	return WEIGHTS["location"] if preferred or (profile.remote_ok and remote) else 0


def _freshness_score(first_seen_at: str) -> tuple[int, int | None]:
	if not first_seen_at:
		return WEIGHTS["freshness"], 0
	try:
		seen = datetime.fromisoformat(first_seen_at.replace("Z", "+00:00"))
		now = datetime.now(seen.tzinfo) if seen.tzinfo else datetime.now()
		days = max(0, (now - seen).days)
	except ValueError:
		return 3, None
	if days <= 1:
		return 5, days
	if days <= 3:
		return 4, days
	if days <= 7:
		return 3, days
	if days <= 14:
		return 1, days
	return 0, days


def score_job(
	job: JobPosting,
	profile: CandidateProfile,
	preferences: SearchPreferences,
) -> MatchResult:
	"""Weighted deterministic matcher designed to minimize unnecessary browser work."""

	text = _normalize(f"{job.title} {job.description}")
	reasons: list[str] = []

	salary = assess_salary_text(
		f"{job.title} {job.description}",
		preferences.min_monthly_salary_cop,
	)
	if salary.blocked:
		return MatchResult(
			0,
			"ignore",
			(salary.reason, "Regla salarial dura: no postular por debajo del mínimo mensual configurado."),
		)

	for excluded in preferences.excluded_terms:
		if _normalize(excluded) in text:
			return MatchResult(0, "ignore", (f"Término excluido detectado: {excluded}",))

	role_points, role_hits = _role_score(job, profile)
	skill_points, matched_skills = _skill_score(text, profile.skills)
	experience_points, required_years = _experience_score(text, profile)
	cloud_points, strategic_matches = _cloud_certification_score(text, profile)
	location_points = _location_score(job, profile)
	context_points, context_matches, context_target = _professional_context_score(profile.professional_summary, text)
	context_adjustment = context_points
	if profile.professional_summary.strip() and context_points == 0:
		# When the user supplied a rich professional summary, zero meaningful
		# overlap is evidence that keyword matches alone may be misleading.
		context_adjustment = -(WEIGHTS["context"] // 2)
	freshness_points, age_days = _freshness_score(job.first_seen_at)

	score = max(
		0,
		min(
			100,
			role_points
			+ skill_points
			+ experience_points
			+ cloud_points
			+ location_points
			+ context_adjustment
			+ freshness_points,
		),
	)

	reasons.append(f"Cargo objetivo: +{role_points}/{WEIGHTS['role']} ({role_hits} coincidencia(s))")
	reasons.append(
		f"Skills verificadas: +{skill_points}/{WEIGHTS['skills']} ({len(matched_skills)} relevantes)"
	)
	if required_years is None:
		reasons.append(f"Experiencia: +{experience_points}/{WEIGHTS['experience']} (sin mínimo explícito)")
	else:
		reasons.append(
			f"Experiencia: +{experience_points}/{WEIGHTS['experience']} "
			f"(requiere {required_years:g}, perfil {profile.years_experience:g} años)"
		)
	reasons.append(
		f"Cloud/certificaciones: +{cloud_points}/{WEIGHTS['cloud_certifications']} "
		f"({len(strategic_matches)} señales estratégicas)"
	)
	reasons.append(f"Ubicación/modalidad: +{location_points}/{WEIGHTS['location']}")
	if profile.professional_summary.strip():
		if context_adjustment < 0:
			reasons.append(
				f"Contexto profesional: {context_adjustment}/{WEIGHTS['context']} "
				f"(sin señales relevantes compartidas)"
			)
		else:
			reasons.append(
				f"Contexto profesional: +{context_points}/{WEIGHTS['context']} "
				f"({len(context_matches)}/{context_target} señales)"
			)
	if age_days is None:
		reasons.append(f"Recencia: +{freshness_points}/{WEIGHTS['freshness']}")
	else:
		reasons.append(f"Recencia: +{freshness_points}/{WEIGHTS['freshness']} ({age_days} día(s) desde primer hallazgo)")

	if score < preferences.min_score:
		decision = "ignore"
	elif score < 75:
		decision = "save"
	elif score < preferences.prepare_application_score:
		decision = "recommend"
	else:
		decision = "prepare"

	return MatchResult(int(score), decision, tuple(reasons))
