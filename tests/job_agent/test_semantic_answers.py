from pathlib import Path

from job_agent.answer_memory import AnswerMemory
from job_agent.computrabajo.deterministic_application import ApplicationPatternStore, ObservedField
from job_agent.semantic_answers import (
    LocalSemanticAnswerEngine,
    classify_question,
    semantic_similarity,
)
from job_agent.computrabajo.smart_application import SmartDeterministicApplicationRunner
from job_agent.profile import UserProfile


def test_semantic_intent_recognizes_equivalent_city_questions() -> None:
    assert classify_question("¿Dónde resides?").intent == "city"
    assert classify_question("Ciudad actual").intent == "city"
    assert classify_question("Lugar de residencia").intent == "city"


def test_profile_city_resolves_rephrased_question_without_ai(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(city="Bogotá")

    result = memory.resolve_context("¿Dónde vives actualmente?", profile)

    assert result is not None
    assert result.answer == "Bogotá"
    assert result.intent == "city"
    assert result.confidence >= 94


def test_english_cefr_maps_to_human_option_without_ai(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(english_level="A2")

    result = memory.resolve_context(
        "Selecciona tu nivel de inglés",
        profile,
        field_type="select",
        options=("Básico", "Intermedio", "Avanzado"),
    )

    assert result is not None
    assert result.answer == "Básico"


def test_total_experience_maps_to_range_but_skill_years_are_not_invented(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(years_experience=4, skills=["Python", "FastAPI"])

    total = memory.resolve_context(
        "¿Cuántos años de experiencia laboral tienes?",
        profile,
        field_type="select",
        options=("0-1 años", "2-3 años", "4-5 años", "Más de 5 años"),
    )
    technology = memory.resolve_context(
        "¿Cuántos años de experiencia tienes en FastAPI?",
        profile,
        field_type="text",
    )

    assert total is not None
    assert total.answer == "4-5 años"
    assert technology is None


def test_verified_skill_can_answer_yes_but_missing_skill_stays_unknown(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(skills=["Python", "FastAPI"])

    known = memory.resolve_context(
        "¿Tienes experiencia con FastAPI?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )
    unknown = memory.resolve_context(
        "¿Tienes experiencia con Kubernetes?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )

    assert known is not None
    assert known.answer == "Sí"
    assert known.source == "verified_skill"
    assert unknown is None


def test_residence_questions_do_not_cross_contaminate_locations(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(city="Bogotá")

    medellin = memory.resolve_context(
        "¿Resides en Medellín?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )

    assert medellin is not None
    assert medellin.answer == "No"
    assert semantic_similarity("¿Resides en Bogotá?", "¿Resides en Medellín?") == 0.0


def test_semantic_memory_reuses_equivalent_manual_answer(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    memory.remember("¿Dónde resides?", "Bogotá", source="manual")
    profile = UserProfile()

    result = memory.resolve_context("Ciudad actual", profile)

    assert result is not None
    assert result.answer == "Bogotá"
    assert result.source == "manual"


def test_semantic_memory_does_not_reuse_answer_for_different_skill(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    memory.remember("¿Tienes experiencia con FastAPI?", "Sí", source="manual")
    profile = UserProfile(skills=["Python"])

    result = memory.resolve_context(
        "¿Tienes experiencia con Kubernetes?",
        profile,
        field_type="radio",
        options=("Sí", "No"),
    )

    assert result is None


def test_local_motivation_is_composed_only_from_job_and_verified_profile_facts(tmp_path: Path) -> None:
    engine = LocalSemanticAnswerEngine(tmp_path / "jobs.db")
    profile = UserProfile(skills=["Python", "FastAPI", "AWS"])

    result = engine.resolve_profile(
        "¿Por qué te interesa esta oportunidad?",
        profile,
        field_type="textarea",
        job={
            "title": "Backend Developer",
            "company": "Example SAS",
            "description": "Buscamos Python y FastAPI.",
        },
    )

    assert result is not None
    assert "Backend Developer" in result.answer
    assert "Example SAS" in result.answer
    assert "Python" in result.answer
    assert "FastAPI" in result.answer
    assert "Kubernetes" not in result.answer
    assert result.source == "local_template"


def test_smart_runner_maps_profile_answer_to_select_option(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    patterns = ApplicationPatternStore(tmp_path / "jobs.db")
    runner = SmartDeterministicApplicationRunner(tmp_path / "browser", memory, patterns)
    profile = UserProfile(english_level="A2")
    field = ObservedField(
        question="Nivel de inglés",
        field_type="select",
        selector="#english",
        options=("Básico", "Intermedio", "Avanzado"),
        required=True,
    )

    answer = runner._resolve_answer(field, profile, {})

    assert answer == "Básico"


def test_smart_action_selection_understands_variants_and_rejects_navigation_noise() -> None:
    action = SmartDeterministicApplicationRunner._choose_action(
        [
            {"text": "Cancelar", "selector": "#cancel", "disabled": False, "in_form": True},
            {"text": "Guardar vacante", "selector": "#save", "disabled": False, "in_form": False},
            {"text": "Aceptar y continuar", "selector": "#next", "disabled": False, "in_form": True},
        ]
    )

    assert action is not None
    assert action["selector"] == "#next"
