from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from job_agent.cv_profile import SKILL_ALIASES
from job_agent.profile import UserProfile
from job_agent.storage import DEFAULT_DB_PATH

_STOPWORDS = {
	'a',
	'al',
	'como',
	'con',
	'cual',
	'cuando',
	'de',
	'del',
	'donde',
	'el',
	'en',
	'es',
	'esta',
	'has',
	'la',
	'las',
	'los',
	'para',
	'por',
	'que',
	'si',
	'sin',
	'su',
	'te',
	'tienes',
	'tu',
	'un',
	'una',
	'y',
	'ya',
}
_YES = {'si', 'sí', 'yes', 'true', 'acepto', 'de acuerdo', 'claro', 'correcto'}
_NO = {'no', 'false'}

_INTENT_PHRASES = {
	'city': (
		('ciudad de residencia', 12),
		('lugar de residencia', 12),
		('ciudad actual', 11),
		('donde resides', 11),
		('donde vives', 11),
		('residencia', 5),
		('ciudad', 5),
	),
	'residence_yes_no': (
		('resides en', 12),
		('vives en', 12),
		('domiciliado en', 12),
		('radicado en', 11),
	),
	'english_level': (
		('nivel de ingles', 12),
		('english level', 12),
		('dominio de ingles', 10),
		('manejo de ingles', 9),
		('ingles', 5),
	),
	'salary': (
		('aspiracion salarial', 12),
		('pretension salarial', 12),
		('salario esperado', 12),
		('expectativa salarial', 12),
		('salario', 5),
	),
	'availability': (
		('disponibilidad para iniciar', 12),
		('cuando puedes empezar', 12),
		('fecha de inicio', 11),
		('disponibilidad inmediata', 10),
		('disponibilidad', 5),
	),
	'total_experience_years': (
		('anos de experiencia laboral', 12),
		('anos de experiencia profesional', 12),
		('cuantos anos de experiencia tienes', 10),
		('experiencia total', 10),
		('anos de experiencia', 7),
	),
	'skill_experience_years': (
		('anos de experiencia con', 12),
		('anos de experiencia en', 11),
		('cuanto tiempo de experiencia', 10),
		('cuantos anos manejando', 10),
	),
	'skill_yes_no': (
		('tienes experiencia con', 12),
		('tienes experiencia en', 12),
		('has trabajado con', 12),
		('cuentas con experiencia', 10),
		('manejas', 8),
		('conoces', 7),
		('conocimiento en', 8),
		('experiencia con', 7),
	),
	'work_mode': (
		('modalidad de trabajo', 12),
		('modalidad preferida', 11),
		('trabajo remoto', 8),
		('trabajo hibrido', 8),
		('trabajo presencial', 8),
		('remoto', 5),
		('hibrido', 5),
		('presencial', 5),
	),
	'contract_type': (
		('tipo de contrato', 12),
		('modalidad contractual', 10),
		('contrato preferido', 11),
	),
	'professional_summary': (
		('hablanos de tu experiencia', 12),
		('cuentanos sobre tu experiencia', 12),
		('resume tu experiencia', 12),
		('perfil profesional', 9),
		('describe tu experiencia', 11),
	),
	'motivation': (
		('por que quieres trabajar', 12),
		('por que te interesa', 12),
		('motivacion para', 10),
		('por que quieres postularte', 12),
		('por que aplicar', 10),
	),
	'strengths': (
		('por que deberiamos contratarte', 12),
		('principales fortalezas', 11),
		('que puedes aportar', 10),
		('fortalezas profesionales', 11),
	),
}
_MODE_ALIASES = {
	'remote': ('remoto', 'remote', 'teletrabajo', 'desde casa', 'home office'),
	'hybrid': ('hibrido', 'hybrid', 'mixto'),
	'onsite': ('presencial', 'onsite', 'en oficina', 'oficina'),
}
_ENGLISH_BUCKETS = {
	'a1': 'basic',
	'a2': 'basic',
	'b1': 'intermediate',
	'b2': 'intermediate',
	'c1': 'advanced',
	'c2': 'advanced',
	'basico': 'basic',
	'basic': 'basic',
	'elemental': 'basic',
	'intermedio': 'intermediate',
	'intermediate': 'intermediate',
	'avanzado': 'advanced',
	'advanced': 'advanced',
	'fluido': 'advanced',
	'fluent': 'advanced',
	'nativo': 'native',
	'native': 'native',
}
_CEFR_RANK = {'a1': 1, 'a2': 2, 'b1': 3, 'b2': 4, 'c1': 5, 'c2': 6}
_LOCATION_SUFFIXES = {
	'dc',
	'd.c',
	'd.c.',
	'distrito',
	'capital',
	'municipio',
	'departamento',
}


@dataclass(frozen=True)
class SemanticMatch:
	intent: str
	confidence: int
	skill: str = ''
	mode: str = ''
	location: str = ''
	required_years: float | None = None
	year_comparison: str = ''
	required_cefr: str = ''


@dataclass(frozen=True)
class LocalSemanticAnswer:
	answer: str
	confidence: int
	source: str
	intent: str
	reason: str


def normalize_semantic(value: str) -> str:
	text = unicodedata.normalize('NFKD', str(value or '').casefold())
	text = ''.join(char for char in text if not unicodedata.combining(char))
	text = re.sub(r'[^a-z0-9+#./-]+', ' ', text)
	return ' '.join(text.split())


def _plain(value: str) -> str:
	return normalize_semantic(value).replace('/', ' ').replace('-', ' ')


def _tokens(value: str) -> set[str]:
	return {token for token in re.findall(r'[a-z0-9+#.]+', _plain(value)) if len(token) > 1 and token not in _STOPWORDS}


def _skill_in_text(text: str) -> str:
	normalized = f' {_plain(text)} '
	ranked: list[tuple[int, str]] = []
	for canonical, aliases in SKILL_ALIASES.items():
		for alias in (canonical, *aliases):
			needle = _plain(alias).strip()
			if needle and f' {needle} ' in normalized:
				ranked.append((len(needle), canonical))
	ranked.sort(reverse=True)
	return ranked[0][1] if ranked else ''


def _mode_in_text(text: str) -> str:
	normalized = _plain(text)
	for mode, aliases in _MODE_ALIASES.items():
		if any(_plain(alias) in normalized for alias in aliases):
			return mode
	return ''


def _extract_cefr(value: str) -> str:
	match = re.search(r'\b(a1|a2|b1|b2|c1|c2)\b', _plain(value))
	return match.group(1) if match else ''


def _extract_year_requirement(value: str) -> tuple[float | None, str]:
	normalized = _plain(value)
	if 'ano' not in normalized:
		return None, ''

	number_match = re.search(r'\b(\d+(?:[.,]\d+)?)\s+anos?\b', normalized)
	if not number_match:
		return None, ''
	try:
		years = float(number_match.group(1).replace(',', '.'))
	except ValueError:
		return None, ''

	before = normalized[max(0, number_match.start() - 40) : number_match.start()]
	after = normalized[number_match.end() : number_match.end() + 20]
	context = f'{before} {after}'

	if any(term in context for term in ('al menos', 'minimo', 'como minimo', 'o mas', 'desde')):
		return years, 'ge'
	if any(term in context for term in ('mas de', 'mayor a', 'superior a')):
		return years, 'gt'
	if any(term in context for term in ('maximo', 'como maximo', 'hasta', 'no mas de')):
		return years, 'le'
	if any(term in context for term in ('menos de', 'menor a', 'inferior a')):
		return years, 'lt'
	return None, ''


def _extract_location(question: str, known_locations: Iterable[str]) -> str:
	normalized = _plain(question)
	for candidate in known_locations:
		clean = _plain(candidate)
		if clean and clean in normalized:
			return str(candidate)

	location_match = re.search(
		r'\b(?:resides|vives|domiciliado|domiciliada|radicado|radicada)\s+en\s+(.+)$',
		normalized,
	)
	if not location_match:
		return ''
	tail = re.split(
		r'\b(?:actualmente|hoy|para|o|y|con|desde)\b',
		location_match.group(1),
		maxsplit=1,
	)[0]
	return ' '.join(tail.split()[:5]).strip(' ,.;?')


def classify_question(question: str, *, known_locations: Iterable[str] = ()) -> SemanticMatch:
	normalized = _plain(question)
	if not normalized:
		return SemanticMatch('unknown', 0)

	skill = _skill_in_text(normalized)
	mode = _mode_in_text(normalized)
	location = _extract_location(question, known_locations)
	required_years, year_comparison = _extract_year_requirement(normalized)
	required_cefr = _extract_cefr(normalized)

	scores: dict[str, int] = {}
	for intent, phrases in _INTENT_PHRASES.items():
		score = sum(weight for phrase, weight in phrases if _plain(phrase) in normalized)
		if score:
			scores[intent] = score

	has_years_experience = 'ano' in normalized and 'experiencia' in normalized
	if skill and has_years_experience:
		scores['skill_experience_years'] = max(scores.get('skill_experience_years', 0), 20)
		scores['skill_yes_no'] = min(scores.get('skill_yes_no', 0), 6)
		scores['total_experience_years'] = min(scores.get('total_experience_years', 0), 5)
	elif has_years_experience:
		scores['total_experience_years'] = max(scores.get('total_experience_years', 0), 14)

	if location and any(
		term in normalized for term in ('resides', 'vives', 'domiciliado', 'domiciliada', 'radicado', 'radicada')
	):
		scores['residence_yes_no'] = max(scores.get('residence_yes_no', 0), 20)
		scores['city'] = min(scores.get('city', 0), 4)

	if required_cefr and 'ingles' in normalized:
		scores['english_level'] = max(scores.get('english_level', 0), 18)

	if not scores:
		return SemanticMatch(
			'unknown',
			0,
			skill=skill,
			mode=mode,
			location=location,
			required_years=required_years,
			year_comparison=year_comparison,
			required_cefr=required_cefr,
		)

	intent, score = max(scores.items(), key=lambda item: item[1])
	return SemanticMatch(
		intent,
		max(70, min(99, 72 + score)),
		skill=skill,
		mode=mode,
		location=location,
		required_years=required_years,
		year_comparison=year_comparison,
		required_cefr=required_cefr,
	)


def semantic_similarity(left: str, right: str) -> float:
	a, b = normalize_semantic(left), normalize_semantic(right)
	if not a or not b:
		return 0.0
	if a == b:
		return 1.0

	left_match, right_match = classify_question(a), classify_question(b)
	if left_match.intent != 'unknown' and right_match.intent != 'unknown':
		if left_match.intent != right_match.intent:
			return 0.0
		if left_match.skill and right_match.skill and left_match.skill != right_match.skill:
			return 0.0
		if left_match.mode and right_match.mode and left_match.mode != right_match.mode:
			return 0.0
		if (
			left_match.intent == 'residence_yes_no'
			and left_match.location
			and right_match.location
			and not _locations_equivalent(left_match.location, right_match.location)
		):
			return 0.0
		if left_match.required_cefr and right_match.required_cefr and left_match.required_cefr != right_match.required_cefr:
			return 0.0
		if left_match.required_years is not None and right_match.required_years is not None:
			if (
				left_match.required_years != right_match.required_years
				or left_match.year_comparison != right_match.year_comparison
			):
				return 0.0

	seq = SequenceMatcher(None, a, b).ratio()
	left_tokens, right_tokens = _tokens(a), _tokens(b)
	union = left_tokens | right_tokens
	jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
	containment = min(
		len(left_tokens & right_tokens) / max(1, len(left_tokens)),
		len(left_tokens & right_tokens) / max(1, len(right_tokens)),
	)
	score = max(seq, 0.55 * jaccard + 0.45 * containment)
	if left_match.intent != 'unknown' and left_match.intent == right_match.intent:
		score = max(score, 0.88 + min(jaccard, 0.10))
	return min(score, 1.0)


def _parse_number(value: str) -> float | None:
	match = re.search(r'\b(\d+(?:[.,]\d+)?)\b', normalize_semantic(value))
	if not match:
		return None
	try:
		return float(match.group(1).replace(',', '.'))
	except ValueError:
		return None


def _parse_money(value: str) -> int | None:
	digits = re.findall(r'\d+', str(value or ''))
	if not digits:
		return None
	number = int(''.join(digits))
	normalized = _plain(value)
	if 'millon' in normalized and number < 1000:
		number *= 1_000_000
	elif 'mil' in normalized and number < 100_000:
		number *= 1000
	return number


def _matches_comparison(value: float, requirement: float, comparison: str) -> bool:
	if comparison == 'ge':
		return value >= requirement
	if comparison == 'gt':
		return value > requirement
	if comparison == 'le':
		return value <= requirement
	if comparison == 'lt':
		return value < requirement
	return False


def _range_contains(option: str, value: float) -> bool:
	text = _plain(option)
	numbers = [float(item.replace(',', '.')) for item in re.findall(r'\d+(?:[.,]\d+)?', text)]
	if not numbers:
		return False
	if any(marker in text for marker in ('mas de', 'mayor a', 'superior a')):
		return value > numbers[0]
	if 'o mas' in text or 'al menos' in text or 'minimo' in text:
		return value >= numbers[0]
	if any(marker in text for marker in ('menos de', 'menor a', 'inferior a')) and len(numbers) == 1:
		return value < numbers[0]
	if any(marker in text for marker in ('hasta', 'maximo')) and len(numbers) == 1:
		return value <= numbers[0]
	if len(numbers) >= 2:
		low, high = min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
		return low <= value <= high
	return abs(value - numbers[0]) < 1e-9


def _money_range_contains(option: str, value: int) -> bool:
	normalized = _plain(option)
	numbers = [_parse_money(item) for item in re.findall(r'\d[\d.,]*', str(option or ''))]
	numbers = [number for number in numbers if number is not None]
	if 'millon' in normalized:
		numbers = [number * 1_000_000 if number < 1000 else number for number in numbers]
	if not numbers:
		return False
	if any(marker in normalized for marker in ('mas de', 'mayor a', 'superior a')):
		return value > numbers[0]
	if 'o mas' in normalized or 'al menos' in normalized or 'minimo' in normalized:
		return value >= numbers[0]
	if any(marker in normalized for marker in ('menos de', 'menor a', 'inferior a')) and len(numbers) == 1:
		return value < numbers[0]
	if any(marker in normalized for marker in ('hasta', 'maximo')) and len(numbers) == 1:
		return value <= numbers[0]
	if len(numbers) >= 2:
		low, high = min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
		return low <= value <= high
	return value == numbers[0]


def _canonical_yes_no(answer: str) -> str:
	normalized = normalize_semantic(answer)
	yes = {normalize_semantic(value) for value in _YES}
	no = {normalize_semantic(value) for value in _NO}
	if normalized in yes:
		return 'yes'
	if normalized in no:
		return 'no'
	return ''


def _yes_no_option_kind(option: str) -> str:
	normalized = normalize_semantic(option)
	if not normalized:
		return ''
	first = normalized.split()[0]
	if first in {normalize_semantic(value) for value in _YES}:
		return 'yes'
	if first in {normalize_semantic(value) for value in _NO}:
		return 'no'
	return ''


def _english_bucket(value: str) -> str:
	normalized = _plain(value)
	for token, bucket in _ENGLISH_BUCKETS.items():
		if re.search(rf'(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])', normalized):
			return bucket
	return ''


def _cefr_meets_requirement(value: str, required: str) -> bool | None:
	current = _extract_cefr(value)
	if not current or required not in _CEFR_RANK:
		return None
	return _CEFR_RANK[current] >= _CEFR_RANK[required]


def _location_tokens(value: str) -> list[str]:
	tokens = [token.strip('.,') for token in _plain(value).split() if token.strip('.,')]
	while tokens and tokens[-1] in _LOCATION_SUFFIXES:
		tokens.pop()
	return tokens


def _locations_equivalent(left: str, right: str) -> bool:
	left_tokens = _location_tokens(left)
	right_tokens = _location_tokens(right)
	if not left_tokens or not right_tokens:
		return False
	return left_tokens == right_tokens


class LocalSemanticAnswerEngine:
	"""Zero-API semantic resolver bound to explicit profile/CV evidence."""

	def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
		self.path = Path(path)

	def _cv_text(self) -> str:
		if not self.path.exists():
			return ''
		try:
			with sqlite3.connect(self.path) as connection:
				exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cv_profile'").fetchone()
				if not exists:
					return ''
				row = connection.execute('SELECT text_content FROM cv_profile WHERE id=1').fetchone()
		except sqlite3.Error:
			return ''
		return str(row[0] or '') if row else ''

	def _skill_is_verified(self, skill: str, profile: UserProfile) -> bool:
		if not skill:
			return False
		if normalize_semantic(skill) in {normalize_semantic(item) for item in profile.skills}:
			return True
		cv_text = normalize_semantic(self._cv_text())
		for alias in (skill, *SKILL_ALIASES.get(skill, ())):
			needle = normalize_semantic(alias)
			if needle and re.search(rf'(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])', cv_text):
				return True
		return False

	@staticmethod
	def _format_years(years: float) -> str:
		return str(int(years)) if float(years).is_integer() else f'{years:.1f}'.rstrip('0').rstrip('.')

	def resolve_profile(
		self,
		question: str,
		profile: UserProfile,
		*,
		field_type: str = 'text',
		options: Iterable[str] = (),
		job: dict[str, object] | None = None,
	) -> LocalSemanticAnswer | None:
		options_tuple = tuple(options)
		locations = [profile.city, *profile.preferred_locations]
		match = classify_question(question, known_locations=(item for item in locations if item))
		raw: str | None = None
		source = 'profile'
		reason = ''

		if match.intent == 'city' and profile.city:
			raw = profile.city
			reason = 'Intención de ciudad/residencia resuelta desde Mi perfil.'
		elif match.intent == 'residence_yes_no' and profile.city and match.location:
			raw = 'Sí' if _locations_equivalent(profile.city, match.location) else 'No'
			reason = 'Ciudad del perfil comparada con la ubicación consultada.'
		elif match.intent == 'english_level' and profile.english_level:
			if match.required_cefr and self._looks_yes_no(options_tuple):
				meets = _cefr_meets_requirement(profile.english_level, match.required_cefr)
				if meets is not None:
					raw = 'Sí' if meets else 'No'
					reason = 'Nivel CEFR explícito del perfil comparado con el requisito de la pregunta.'
			if raw is None:
				raw = profile.english_level
				reason = 'Nivel de inglés explícito de Mi perfil.'
		elif match.intent == 'salary' and profile.salary_expectation:
			raw = profile.salary_expectation
			reason = 'Aspiración salarial explícita de Mi perfil.'
		elif match.intent == 'availability' and profile.availability:
			raw = profile.availability
			reason = 'Disponibilidad explícita de Mi perfil.'
		elif match.intent == 'total_experience_years' and not match.skill and profile.years_experience > 0:
			if match.required_years is not None and match.year_comparison and self._looks_yes_no(options_tuple):
				raw = (
					'Sí'
					if _matches_comparison(
						profile.years_experience,
						match.required_years,
						match.year_comparison,
					)
					else 'No'
				)
				reason = 'Experiencia total explícita comparada con el mínimo/máximo solicitado.'
			else:
				raw = self._format_years(profile.years_experience)
				reason = 'Años de experiencia total explícitos del perfil.'
		elif match.intent == 'skill_yes_no' and match.skill and self._skill_is_verified(match.skill, profile):
			raw = 'Sí'
			source = 'verified_skill'
			reason = f'{match.skill} está verificada en el perfil/CV.'
		elif match.intent == 'work_mode' and match.mode:
			preferred = {normalize_semantic(item) for item in profile.preferred_work_modes}
			allowed = (
				(match.mode == 'remote' and (profile.remote_ok or any('remot' in item for item in preferred)))
				or (match.mode == 'hybrid' and any('hibrid' in item or 'hybrid' in item for item in preferred))
				or (match.mode == 'onsite' and any('presencial' in item or 'onsite' in item for item in preferred))
			)
			if allowed:
				raw = (
					'Sí'
					if field_type in {'checkbox', 'radio'} or self._looks_yes_no(options_tuple)
					else {'remote': 'Remoto', 'hybrid': 'Híbrido', 'onsite': 'Presencial'}[match.mode]
				)
				reason = 'Modalidad explícitamente permitida en las preferencias.'
		elif match.intent == 'work_mode' and not match.mode and profile.preferred_work_modes:
			raw = profile.preferred_work_modes[0]
			reason = 'Primera modalidad preferida configurada.'
		elif match.intent == 'contract_type' and profile.preferred_contract_types:
			raw = profile.preferred_contract_types[0]
			reason = 'Tipo de contrato preferido configurado.'
		elif match.intent == 'professional_summary' and profile.professional_summary:
			raw = profile.professional_summary[:1800].strip()
			source = 'professional_summary'
			reason = 'Resumen profesional escrito por el usuario.'
		elif match.intent in {'motivation', 'strengths'}:
			raw = self._compose_safe_text(match.intent, profile, job or {})
			if raw:
				source = 'local_template'
				reason = 'Texto compuesto solo con cargo, empresa y skills verificadas.'

		if not raw:
			return None
		adapted = self.adapt_to_options(
			raw,
			options=options_tuple,
			intent=match.intent,
			match=match,
		)
		if adapted is None:
			return None
		return LocalSemanticAnswer(
			adapted,
			max(match.confidence, 90 if source == 'local_template' else 94),
			source,
			match.intent,
			reason,
		)

	@staticmethod
	def _looks_yes_no(options: Iterable[str]) -> bool:
		kinds = {_yes_no_option_kind(option) for option in options}
		return 'yes' in kinds and 'no' in kinds

	def adapt_to_options(
		self,
		answer: str,
		*,
		options: tuple[str, ...],
		intent: str = 'unknown',
		match: SemanticMatch | None = None,
	) -> str | None:
		clean = ' '.join(str(answer or '').strip().split())
		if not clean:
			return None
		if not options:
			return clean

		normalized_answer = normalize_semantic(clean)
		normalized_options = [(normalize_semantic(option), option) for option in options if normalize_semantic(option)]
		for normalized, option in normalized_options:
			if normalized == normalized_answer:
				return option

		yes_no = _canonical_yes_no(clean)
		if yes_no:
			for _, option in normalized_options:
				if _yes_no_option_kind(option) == yes_no:
					return option

		if intent == 'english_level':
			bucket = _english_bucket(clean)
			cefr = _extract_cefr(clean)
			if cefr:
				for normalized, option in normalized_options:
					if re.search(rf'\b{re.escape(cefr)}\b', normalized):
						return option
			if bucket:
				for normalized, option in normalized_options:
					if _english_bucket(normalized) == bucket:
						return option

		if intent in {'total_experience_years', 'skill_experience_years'}:
			years = _parse_number(clean)
			if years is not None:
				if (
					match is not None
					and match.required_years is not None
					and match.year_comparison
					and self._looks_yes_no(options)
				):
					expected = 'yes' if _matches_comparison(years, match.required_years, match.year_comparison) else 'no'
					for _, option in normalized_options:
						if _yes_no_option_kind(option) == expected:
							return option
				for _, option in normalized_options:
					if _range_contains(option, years):
						return option

		if intent == 'salary':
			money = _parse_money(clean)
			if money is not None:
				for _, option in normalized_options:
					if _money_range_contains(option, money):
						return option

		if intent == 'work_mode':
			mode = match.mode if match else _mode_in_text(clean)
			if not mode:
				mode = _mode_in_text(clean)
			if mode:
				aliases = {normalize_semantic(value) for value in _MODE_ALIASES[mode]}
				for normalized, option in normalized_options:
					if normalized in aliases or any(alias in normalized for alias in aliases):
						return option

		best: tuple[float, str] | None = None
		for normalized, option in normalized_options:
			ratio = SequenceMatcher(None, normalized, normalized_answer).ratio()
			if normalized_answer in normalized or normalized in normalized_answer:
				ratio = max(ratio, 0.95)
			if best is None or ratio > best[0]:
				best = (ratio, option)
		return best[1] if best and best[0] >= 0.88 else None

	@staticmethod
	def _compose_safe_text(intent: str, profile: UserProfile, job: dict[str, object]) -> str:
		title = ' '.join(str(job.get('title') or '').split())
		company = ' '.join(str(job.get('company') or '').split())
		description = normalize_semantic(str(job.get('description') or ''))
		verified = [
			skill for skill in profile.skills if normalize_semantic(skill) and normalize_semantic(skill) in description
		] or profile.skills[:5]
		skills = ', '.join(verified[:5])
		role = title or (profile.target_roles[0] if profile.target_roles else 'esta posición')
		company_fragment = f' en {company}' if company else ''
		if intent == 'motivation':
			parts = [f'Me interesa la oportunidad de {role}{company_fragment} porque está alineada con mi perfil profesional.']
			if skills:
				parts.append(f'Puedo aportar experiencia y conocimientos en {skills}.')
			return ' '.join(parts)[:1200]
		if intent == 'strengths':
			if skills:
				return (
					f'Mis principales fortalezas para {role} son mis conocimientos verificados en {skills}, '
					'junto con mi enfoque en construir soluciones claras, mantenibles y orientadas a resultados.'
				)[:1200]
			if profile.professional_summary:
				return profile.professional_summary[:1200].strip()
		return ''
