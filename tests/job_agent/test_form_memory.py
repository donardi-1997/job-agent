from pathlib import Path

from job_agent.computrabajo.deterministic_application import ObservedField
from job_agent.computrabajo.form_memory import ApplicationFormMemory, form_fingerprint


def _fields() -> tuple[ObservedField, ...]:
    return (
        ObservedField(
            question="¿Cuál es tu disponibilidad?",
            field_type="text",
            selector="#availability",
            required=True,
        ),
        ObservedField(
            question="¿Aceptas trabajo híbrido?",
            field_type="radio",
            selector='input[name="hybrid"]',
            options=("Sí", "No"),
            required=True,
        ),
    )


def test_form_fingerprint_ignores_brittle_selectors() -> None:
    first = _fields()
    second = (
        first[0].__class__(**{**first[0].__dict__, "selector": "#different-id"}),
        first[1].__class__(**{**first[1].__dict__, "selector": 'input[name="other"]'}),
    )

    assert form_fingerprint(first) == form_fingerprint(second)


def test_form_memory_observes_then_confirms_success(tmp_path: Path) -> None:
    memory = ApplicationFormMemory(tmp_path / "jobs.db")
    fields = _fields()

    fingerprint = memory.observe(fields)
    before = memory.stats()
    memory.confirm_success(fields)
    after = memory.stats()

    assert fingerprint
    assert before["forms"] == 1
    assert before["proven_forms"] == 0
    assert memory.is_proven(fields) is True
    assert after["forms"] == 1
    assert after["proven_forms"] == 1
    assert after["form_successful_uses"] == 1
