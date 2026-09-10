from job_agent.computrabajo.eligibility import assess_hard_eligibility
from job_agent.profile import UserProfile


def _profile(**updates: object) -> UserProfile:
    base = UserProfile(
        years_experience=5,
        english_level="A2",
        min_monthly_salary_cop=4_000_000,
        skills=["Python", "AWS"],
    )
    return base.model_copy(update=updates)


def test_blocks_salary_below_floor() -> None:
    result = assess_hard_eligibility(
        {"title": "Backend Developer", "description": "Salario: COP 3.500.000 MONTH"},
        _profile(),
    )

    assert result.blocked is True
    assert result.code == "salary_below_minimum"


def test_blocks_explicit_english_requirement_above_profile() -> None:
    result = assess_hard_eligibility(
        {"title": "Backend Developer", "description": "Inglés B1 mínimo y excluyente para el cargo."},
        _profile(),
    )

    assert result.blocked is True
    assert result.code == "english_requirement_above_profile"


def test_does_not_block_ambiguous_english_mention() -> None:
    result = assess_hard_eligibility(
        {"title": "Backend Developer", "description": "Equipo internacional. Inglés B1 es valorado."},
        _profile(),
    )

    assert result.blocked is False


def test_blocks_explicit_minimum_experience_above_profile() -> None:
    result = assess_hard_eligibility(
        {"title": "Senior Backend", "description": "Requisito obligatorio: mínimo 7 años de experiencia profesional."},
        _profile(),
    )

    assert result.blocked is True
    assert result.code == "experience_requirement_above_profile"


def test_allows_requirement_within_profile() -> None:
    result = assess_hard_eligibility(
        {"title": "Backend Developer", "description": "Mínimo 3 años de experiencia. Inglés A2 requerido."},
        _profile(),
    )

    assert result.blocked is False


def test_unknown_salary_and_unrecognized_english_are_not_hard_blocked() -> None:
    result = assess_hard_eligibility(
        {"title": "Python Developer", "description": "Excelente oportunidad profesional."},
        _profile(english_level=""),
    )

    assert result.blocked is False
