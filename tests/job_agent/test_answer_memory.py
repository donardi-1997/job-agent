from pathlib import Path

from job_agent.answer_memory import AnswerMemory, normalize_question
from job_agent.profile import FrequentAnswer, UserProfile


def test_normalize_question_removes_accents_and_punctuation() -> None:
    assert normalize_question("¿Cuál es tu aspiración salarial?") == "cual es tu aspiracion salarial"


def test_profile_fact_resolves_without_ai(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(city="Bogotá", english_level="A2", salary_expectation="4.000.000 COP")

    assert memory.resolve("¿Cuál es tu ciudad de residencia?", profile) == "Bogotá"
    assert memory.resolve("Indica tu nivel de inglés", profile) == "A2"
    assert memory.resolve("¿Cuál es tu aspiración salarial?", profile) == "4.000.000 COP"


def test_frequent_and_learned_answers_are_reused(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(
        frequent_answers=[FrequentAnswer(question="¿Puedes trabajar los sábados?", answer="Sí")]
    )

    assert memory.resolve("Puedes trabajar los sabados?", profile) == "Sí"

    memory.remember("¿Tienes disponibilidad para viajar?", "Sí", confidence=100)
    assert memory.resolve("Tienes disponibilidad para viajar", profile) == "Sí"


def test_manual_adjustment_has_priority_for_future_equivalent_questions(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(
        salary_expectation="4.000.000 COP",
        frequent_answers=[FrequentAnswer(question="¿Cuál es tu aspiración salarial?", answer="4.200.000 COP")],
    )

    memory.remember(
        "¿Cuál es tu aspiración salarial?",
        "5.000.000 COP",
        source="manual",
        confidence=100,
    )

    assert memory.resolve("Indica tu aspiración salarial", profile) == "5.000.000 COP"
    context = memory.context_for_agent(profile)
    assert context[0]["answer"] == "5.000.000 COP"
    assert context[0]["source"] == "manual"


def test_manual_adjustment_can_be_removed(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    profile = UserProfile(city="Bogotá")
    memory.remember("¿Cuál es tu ciudad de residencia?", "Medellín", source="manual")

    assert memory.resolve("Cuál es tu ciudad de residencia", profile) == "Medellín"
    assert memory.forget("¿Cuál es tu ciudad de residencia?") is True
    assert memory.resolve("Cuál es tu ciudad de residencia", profile) == "Bogotá"


def test_only_successful_high_confidence_answers_are_learned(tmp_path: Path) -> None:
    memory = AnswerMemory(tmp_path / "jobs.db")
    questions = [
        {"question": "Pregunta segura", "suggested_answer": "Respuesta", "confidence": 95, "requires_user_input": False},
        {"question": "Pregunta dudosa", "suggested_answer": "Tal vez", "confidence": 70, "requires_user_input": False},
        {"question": "Pregunta incompleta", "suggested_answer": "", "confidence": 100, "requires_user_input": True},
    ]

    assert memory.remember_questions(questions, submitted=False) == 0
    assert memory.stats()["answers"] == 0

    assert memory.remember_questions(questions, submitted=True) == 1
    assert memory.stats()["answers"] == 1
