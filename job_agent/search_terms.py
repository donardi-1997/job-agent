from __future__ import annotations

from dataclasses import dataclass

from job_agent.profile import UserProfile


@dataclass(frozen=True)
class SearchTermRule:
	term: str
	signals: tuple[str, ...]
	min_matches: int = 1
	base_priority: int = 0


# These rules intentionally map concrete skills to job-title style queries instead
# of searching every skill literally. Generic tooling such as Jira/Confluence is
# useful for scoring, but is not a useful standalone vacancy search term.
SEARCH_TERM_RULES: tuple[SearchTermRule, ...] = (
	SearchTermRule("Python Backend Developer", ("python", "fastapi", "backend development", "rest apis", "api development"), 1, 100),
	SearchTermRule("AWS Developer", ("aws", "aws lambda", "lambda", "api gateway", "dynamodb", "amazon s3", "s3"), 1, 96),
	SearchTermRule("Cloud Developer", ("aws", "azure", "cloud architecture"), 1, 90),
	SearchTermRule("Serverless Developer", ("aws lambda", "lambda", "api gateway", "dynamodb", "serverless architecture"), 2, 92),
	SearchTermRule("Full Stack Developer", ("full stack development", "react", "angular", "node.js", ".net"), 2, 88),
	SearchTermRule("React Developer", ("react", "javascript", "frontend development"), 1, 82),
	SearchTermRule("Angular Developer", ("angular", "javascript", "frontend development"), 1, 81),
	SearchTermRule("Node.js Developer", ("node.js", "javascript", "backend development", "rest apis"), 1, 84),
	SearchTermRule(".NET Developer", (".net", "c#", "backend development"), 1, 80),
	SearchTermRule("DevOps Engineer", ("devops", "ci/cd", "deployment", "aws", "azure"), 1, 76),
	SearchTermRule("API Developer", ("api development", "rest apis", "backend development", "python", "node.js"), 2, 78),
	SearchTermRule("Frontend Developer", ("frontend development", "react", "angular", "javascript"), 2, 75),
)


def _normalize(value: str) -> str:
	return " ".join(value.casefold().strip().split())


def derive_skill_search_terms(profile: UserProfile, limit: int = 12) -> list[str]:
	"""Return deterministic vacancy-search terms derived from the user's skills.

	The function does not call an LLM. It prefers job-title queries supported by
	multiple related skills and ignores generic productivity/project-management
	tools that would create noisy searches.
	"""
	if limit <= 0:
		return []

	skills = {_normalize(skill) for skill in profile.skills if skill.strip()}
	if not skills:
		return []

	ranked: list[tuple[int, int, str]] = []
	for order, rule in enumerate(SEARCH_TERM_RULES):
		matched = sum(1 for signal in rule.signals if _normalize(signal) in skills)
		if matched < rule.min_matches:
			continue
		# Multiple supporting skills should outrank a rule triggered by only one.
		score = rule.base_priority + matched * 8
		ranked.append((score, -order, rule.term))

	ranked.sort(reverse=True)
	return [term for _, _, term in ranked[:limit]]


def build_personal_search_terms(profile: UserProfile, *, custom_term: str = "", limit: int = 8) -> list[str]:
	"""Build the personal automatic search plan from skills plus explicit roles.

	Skill-derived terms come first because they adapt automatically when the CV or
	profile skills change. Explicit target roles are then retained as durable user
	preferences, followed by one optional manual term.
	"""
	if limit <= 0:
		return []

	values = [*derive_skill_search_terms(profile, limit=limit), *profile.target_roles]
	if custom_term.strip():
		values.append(custom_term)

	result: list[str] = []
	seen: set[str] = set()
	for raw in values:
		value = " ".join(str(raw).strip().split())
		key = value.casefold()
		if value and key not in seen:
			seen.add(key)
			result.append(value)
		if len(result) >= limit:
			break
	return result
