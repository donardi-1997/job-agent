from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_MIN_MONTHLY_SALARY_COP = 4_000_000


@dataclass(frozen=True)
class SalaryAssessment:
	published: bool
	minimum_cop: int | None = None
	maximum_cop: int | None = None
	blocked: bool = False
	reason: str = ""
	evidence: str = ""


def _parse_amount(raw: str, *, millions: bool = False) -> int | None:
	value = raw.strip().lower().replace("cop", "").replace("$", "").replace(" ", "")
	if not value:
		return None
	if millions:
		try:
			return int(round(float(value.replace(",", ".")) * 1_000_000))
		except ValueError:
			return None

	# Colombian salary formatting is commonly 3.500.000 or 3,500,000. Optional
	# decimal cents (for example 3.500.000,00) are intentionally discarded.
	match = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3}){1,2})(?:[.,]\d{2})?", value)
	if match:
		return int(re.sub(r"[.,]", "", match.group(1)))
	if re.fullmatch(r"\d{6,8}", value):
		return int(value)
	return None


def _amounts_from_window(window: str) -> list[int]:
	amounts: list[int] = []
	for match in re.finditer(r"(?<!\d)(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:millones?|mill[oó]n)\b", window, re.IGNORECASE):
		amount = _parse_amount(match.group(1), millions=True)
		if amount is not None:
			amounts.append(amount)
	for match in re.finditer(r"(?<!\d)(?:\$\s*|COP\s*)?(\d{1,3}(?:[.,]\d{3}){1,2}(?:[.,]\d{2})?|\d{6,8})(?!\d)", window, re.IGNORECASE):
		amount = _parse_amount(match.group(1))
		if amount is not None and 500_000 <= amount <= 100_000_000:
			amounts.append(amount)
	return amounts


def assess_salary_text(text: str, minimum_monthly_salary_cop: int = DEFAULT_MIN_MONTHLY_SALARY_COP) -> SalaryAssessment:
	"""Conservatively detect an explicitly published monthly salary.

	The policy only blocks when the highest salary found in the advertised fixed
	value/range is still below the configured minimum. Unknown salaries and ranges
	that reach the minimum are not rejected automatically.
	"""
	if minimum_monthly_salary_cop <= 0:
		return SalaryAssessment(False)

	compact = re.sub(r"\s+", " ", str(text or "")).strip()
	if not compact:
		return SalaryAssessment(False)

	markers = list(
		re.finditer(
			r"\b(?:salario|sueldo|remuneraci[oó]n|compensaci[oó]n|rango\s+salarial|salario\s+mensual)\b",
			compact,
			re.IGNORECASE,
		)
	)
	windows: list[str] = []
	for marker in markers:
		start = max(0, marker.start() - 35)
		end = min(len(compact), marker.end() + 150)
		window = compact[start:end]
		# Do not interpret an explicitly annual amount as a monthly salary.
		if re.search(r"\b(?:anual|al\s+a[nñ]o|por\s+a[nñ]o)\b", window, re.IGNORECASE):
			continue
		windows.append(window)

	# Computrabajo often renders the amount with a currency sign adjacent to the
	# salary metadata but without the word "salario" in the extracted text.
	for match in re.finditer(r"(?:\$\s*|COP\s*)(\d{1,3}(?:[.,]\d{3}){1,2}(?:[.,]\d{2})?|\d{6,8})", compact, re.IGNORECASE):
		start = max(0, match.start() - 45)
		end = min(len(compact), match.end() + 70)
		window = compact[start:end]
		if re.search(r"\b(?:mensual|mes|salario|sueldo)\b", window, re.IGNORECASE):
			windows.append(window)

	candidates: list[tuple[list[int], str]] = []
	for window in windows:
		amounts = _amounts_from_window(window)
		if amounts:
			candidates.append((amounts, window))
	if not candidates:
		return SalaryAssessment(False)

	# Prefer the first salary-labelled window. Values inside the same window are
	# treated as a possible range; duplicate formatted values are harmless.
	amounts, evidence = candidates[0]
	minimum = min(amounts)
	maximum = max(amounts)
	blocked = maximum < minimum_monthly_salary_cop
	formatted_minimum = f"${minimum_monthly_salary_cop:,.0f}".replace(",", ".")
	formatted_maximum = f"${maximum:,.0f}".replace(",", ".")
	return SalaryAssessment(
		published=True,
		minimum_cop=minimum,
		maximum_cop=maximum,
		blocked=blocked,
		reason=(
			f"Salario publicado ({formatted_maximum} COP) inferior al mínimo configurado ({formatted_minimum} COP)."
			if blocked
			else ""
		),
		evidence=evidence[:240],
	)


def assess_job_salary(job: dict[str, object], minimum_monthly_salary_cop: int = DEFAULT_MIN_MONTHLY_SALARY_COP) -> SalaryAssessment:
	text = " ".join(
		str(job.get(key) or "")
		for key in ("title", "description", "location")
	)
	return assess_salary_text(text, minimum_monthly_salary_cop)
