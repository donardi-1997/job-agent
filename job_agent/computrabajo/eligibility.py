from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from job_agent.profile import UserProfile
from job_agent.salary_policy import assess_job_salary


_CEFR_ORDER = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6}
_REQUIRED_MARKERS = (
    "obligatorio",
    "obligatoria",
    "excluyente",
    "indispensable",
    "requerido",
    "requerida",
    "requisito",
    "minimo",
    "minimum",
    "required",
    "must have",
    "must",
    "al menos",
)


@dataclass(frozen=True)
class EligibilityAssessment:
    blocked: bool
    code: str = ""
    reason: str = ""


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip()


def _job_text(job: dict[str, object]) -> str:
    return _normalize(f"{job.get('title', '')} {job.get('description', '')}")


def _recognized_profile_english(profile: UserProfile) -> str:
    match = re.search(r"\b(a1|a2|b1|b2|c1|c2)\b", _normalize(profile.english_level))
    return match.group(1) if match else ""


def _required_english_level(text: str) -> str:
    candidates: list[tuple[int, str]] = []
    patterns = (
        r"(?:ingles|english).{0,90}?\b(a1|a2|b1|b2|c1|c2)\b",
        r"\b(a1|a2|b1|b2|c1|c2)\b.{0,70}?(?:ingles|english)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 90)
            window = text[start:end]
            if not any(marker in window for marker in _REQUIRED_MARKERS):
                continue
            level = match.group(1)
            candidates.append((_CEFR_ORDER[level], level))
    return max(candidates, default=(0, ""))[1]


def _required_years(text: str) -> float | None:
    candidates: list[float] = []
    patterns = (
        r"(?P<n>\d+(?:[.,]\d+)?)\s*\+?\s*(?:anos|years)\s+(?:de\s+)?(?:experiencia|experience)",
        r"(?:experiencia|experience).{0,45}?(?P<n>\d+(?:[.,]\d+)?)\s*\+?\s*(?:anos|years)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 90)
            window = text[start:end]
            explicitly_minimum = any(marker in window for marker in _REQUIRED_MARKERS) or "+" in match.group(0)
            if not explicitly_minimum:
                continue
            try:
                candidates.append(float(match.group("n").replace(",", ".")))
            except ValueError:
                continue
    return max(candidates) if candidates else None


def assess_hard_eligibility(job: dict[str, object], profile: UserProfile) -> EligibilityAssessment:
    """Apply only high-confidence hard filters before browser/LLM work.

    Unknown salary, unrecognized English levels, and ambiguous experience prose are
    deliberately allowed. The goal is to prevent clearly ineligible applications
    without creating false negatives from loose text heuristics.
    """

    salary = assess_job_salary(job, profile.min_monthly_salary_cop)
    if salary.blocked:
        return EligibilityAssessment(True, "salary_below_minimum", salary.reason)

    text = _job_text(job)
    profile_level = _recognized_profile_english(profile)
    required_level = _required_english_level(text)
    if profile_level and required_level and _CEFR_ORDER[required_level] > _CEFR_ORDER[profile_level]:
        return EligibilityAssessment(
            True,
            "english_requirement_above_profile",
            f"La vacante exige inglés {required_level.upper()} como requisito obligatorio/excluyente y el perfil está en {profile_level.upper()}.",
        )

    required_years = _required_years(text)
    if required_years is not None and profile.years_experience > 0 and required_years > profile.years_experience:
        display = int(required_years) if required_years.is_integer() else required_years
        return EligibilityAssessment(
            True,
            "experience_requirement_above_profile",
            f"La vacante exige al menos {display} años de experiencia y el perfil registra {profile.years_experience:g}.",
        )

    return EligibilityAssessment(False)
