from pathlib import Path

from job_agent.answer_memory import AnswerMemory
from job_agent.profile import UserProfile
from job_agent.semantic_answers import semantic_similarity


def test_residence_accepts_administrative_city_suffix_without_false_negative(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(city="Bogotá D.C.")

    result = memory.resolve_context(
        "¿Resides en Bogotá?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )

    assert result is not None
    assert result.answer == "Sí"


def test_english_requirement_answers_yes_no_from_explicit_cefr(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(english_level="B2")

    meets = memory.resolve_context(
        "¿Cuentas con nivel de inglés B2 o superior?",
        profile,
        field_type="radio",
        options=("Sí, cuento con el nivel", "No"),
    )
    does_not_meet = memory.resolve_context(
        "¿Cuentas con nivel de inglés C1 o superior?",
        profile,
        field_type="radio",
        options=("Sí", "No, aún no"),
    )

    assert meets is not None
    assert meets.answer == "Sí, cuento con el nivel"
    assert does_not_meet is not None
    assert does_not_meet.answer == "No, aún no"


def test_semantic_memory_does_not_cross_contaminate_cefr_requirements(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    memory.remember("¿Tienes nivel de inglés B2?", "Sí", source="manual")
    profile = UserProfile()

    result = memory.resolve_context(
        "¿Tienes nivel de inglés C1?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )

    assert semantic_similarity("¿Tienes nivel de inglés B2?", "¿Tienes nivel de inglés C1?") == 0.0
    assert result is None


def test_total_experience_requirement_answers_yes_no_without_ai(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(years_experience=4)

    enough = memory.resolve_context(
        "¿Cuentas con mínimo 3 años de experiencia profesional?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )
    not_enough = memory.resolve_context(
        "¿Tienes más de 4 años de experiencia laboral?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )

    assert enough is not None
    assert enough.answer == "Sí"
    assert not_enough is not None
    assert not_enough.answer == "No"


def test_experience_ranges_keep_strict_more_than_semantics(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(years_experience=5)

    result = memory.resolve_context(
        "¿Cuántos años de experiencia laboral tienes?",
        profile,
        field_type="select",
        options=("4-5 años", "Más de 5 años"),
    )

    assert result is not None
    assert result.answer == "4-5 años"


def test_skill_year_memory_can_answer_equivalent_threshold_question(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    memory.remember(
        "¿Cuántos años de experiencia tienes en FastAPI?",
        "2.5",
        source="manual",
    )
    profile = UserProfile(skills=["FastAPI"])

    result = memory.resolve_context(
        "¿Cuentas con mínimo 2 años de experiencia en FastAPI?",
        profile,
        field_type="radio",
        options=("Sí, cuento con experiencia", "No"),
    )

    assert result is not None
    assert result.answer == "Sí, cuento con experiencia"
    assert result.source == "manual"


def test_semantic_memory_does_not_reuse_different_year_requirement(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    memory.remember(
        "¿Cuentas con mínimo 2 años de experiencia en Python?",
        "Sí",
        source="manual",
    )
    profile = UserProfile(skills=["Python"])

    result = memory.resolve_context(
        "¿Cuentas con mínimo 5 años de experiencia en Python?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )

    assert semantic_similarity(
        "¿Cuentas con mínimo 2 años de experiencia en Python?",
        "¿Cuentas con mínimo 5 años de experiencia en Python?",
    ) == 0.0
    assert result is None


def test_salary_at_boundary_does_not_match_more_than_bucket(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(salary_expectation="5.000.000 COP")

    result = memory.resolve_context(
        "Selecciona tu aspiración salarial",
        profile,
        field_type="select",
        options=("Hasta 5.000.000 COP", "Más de 5.000.000 COP"),
    )

    assert result is not None
    assert result.answer == "Hasta 5.000.000 COP"


def test_verified_skill_maps_verbose_yes_no_options(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(skills=["Python"])

    result = memory.resolve_context(
        "¿Cuentas con experiencia en Python?",
        profile,
        field_type="radio",
        options=("Sí, cuento con experiencia", "No, no cuento con experiencia"),
    )

    assert result is not None
    assert result.answer == "Sí, cuento con experiencia"
