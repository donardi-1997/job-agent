from __future__ import annotations

from dataclasses import replace
from typing import Any

from job_agent.answer_memory import normalize_question
from job_agent.computrabajo.cost_aware_application import CostAwareApplicationPreparer
from job_agent.computrabajo.deterministic_application import (
    DeterministicApplicationResult,
    DeterministicApplicationRunner,
    ObservedField,
)
from job_agent.semantic_answers import (
    LocalSemanticAnswer,
    classify_question,
    semantic_similarity,
)
from job_agent.profile import UserProfile


class SmartDeterministicApplicationRunner(DeterministicApplicationRunner):
    """Semantic zero-cost layer on top of the conservative CDP form runner."""

    _NEGATIVE_ACTION_MARKERS = (
        "cancelar",
        "volver",
        "atras",
        "cerrar",
        "salir",
        "compartir",
        "guardar empleo",
        "guardar vacante",
        "ver empresa",
        "enviar mensaje",
        "reportar",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._current_job: dict[str, object] = {}
        self._resolution_meta: dict[str, LocalSemanticAnswer] = {}

    async def apply(self, *, job: dict[str, object], **kwargs: Any) -> DeterministicApplicationResult:
        previous_job = self._current_job
        previous_meta = self._resolution_meta
        self._current_job = job
        self._resolution_meta = {}
        try:
            result = await super().apply(job=job, **kwargs)
            questions = []
            for question in result.questions:
                meta = self._resolution_meta.get(normalize_question(question.question))
                if meta is None or not question.answer:
                    questions.append(question)
                    continue
                questions.append(
                    replace(
                        question,
                        confidence=meta.confidence,
                        note=f"{meta.reason} Fuente: {meta.source}; intención: {meta.intent}.",
                    )
                )
            return replace(result, questions=tuple(questions))
        finally:
            self._current_job = previous_job
            self._resolution_meta = previous_meta

    def _resolve_answer(
        self,
        field: ObservedField,
        profile: UserProfile,
        saved_draft: dict[str, object],
    ) -> str | None:
        saved = self._saved_answer_semantic(field.question, saved_draft)
        if saved:
            match = classify_question(
                field.question,
                known_locations=[profile.city, *profile.preferred_locations],
            )
            adapted = self.answer_memory.semantic_engine.adapt_to_options(
                saved,
                options=field.options,
                intent=match.intent,
                match=match,
            )
            if adapted is not None:
                resolution = LocalSemanticAnswer(
                    answer=adapted,
                    confidence=100,
                    source="saved_draft",
                    intent=match.intent,
                    reason="Respuesta reutilizada del borrador de esta misma vacante.",
                )
                self._resolution_meta[normalize_question(field.question)] = resolution
                return adapted

        resolution = self.answer_memory.resolve_context(
            field.question,
            profile,
            field_type=field.field_type,
            options=field.options,
            job=self._current_job,
        )
        if resolution:
            self._resolution_meta[normalize_question(field.question)] = resolution
            return resolution.answer
        return None

    def _saved_answer_semantic(
        self,
        question: str,
        saved_draft: dict[str, object],
    ) -> str | None:
        items = saved_draft.get("questions") or []
        if not isinstance(items, list):
            return None

        normalized = normalize_question(question)
        best: tuple[float, str] | None = None
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate_question = str(item.get("question") or "").strip()
            answer = str(item.get("suggested_answer") or "").strip()
            if not candidate_question or not answer:
                continue
            if normalize_question(candidate_question) == normalized:
                return answer
            score = semantic_similarity(question, candidate_question)
            if best is None or score > best[0]:
                best = (score, answer)

        threshold = self.answer_memory._similarity_threshold(question)
        return best[1] if best and best[0] >= threshold else None

    @classmethod
    def _choose_action(cls, raw_actions: object) -> dict[str, object] | None:
        if not isinstance(raw_actions, list):
            return None

        ranked: list[tuple[int, int, dict[str, object]]] = []
        for index, raw in enumerate(raw_actions):
            if not isinstance(raw, dict):
                continue
            selector = str(raw.get("selector") or "").strip()
            text = normalize_question(str(raw.get("text") or ""))
            if not selector or not text or bool(raw.get("disabled")):
                continue
            if any(marker in text for marker in cls._NEGATIVE_ACTION_MARKERS):
                continue

            score = cls._action_score(text, in_form=bool(raw.get("in_form")))
            if score <= 0:
                continue
            ranked.append((score, -index, raw))

        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        return ranked[0][2] if ranked else None

    @staticmethod
    def _action_score(text: str, *, in_form: bool) -> int:
        exact = {
            "continuar": 120,
            "siguiente": 118,
            "seguir": 116,
            "guardar y continuar": 115,
            "aceptar y continuar": 114,
            "continuar postulacion": 112,
            "continuar con la postulacion": 112,
            "postularme": 105,
            "postular": 104,
            "enviar postulacion": 103,
            "enviar candidatura": 102,
            "finalizar postulacion": 101,
            "confirmar postulacion": 100,
            "aplicar": 98,
            "finalizar": 94,
        }
        if text in exact:
            return exact[text] + (3 if in_form else 0)

        score = 0
        if any(marker in text for marker in ("continuar", "siguiente", "seguir")):
            score = max(score, 110)
        if "guardar" in text and any(marker in text for marker in ("continuar", "seguir", "siguiente")):
            score = max(score, 112)
        if "aceptar" in text and "continuar" in text:
            score = max(score, 111)
        if "postul" in text or "candidatura" in text:
            if any(marker in text for marker in ("enviar", "confirmar", "finalizar", "postular", "continuar")):
                score = max(score, 100)
        if in_form and text in {"enviar", "aplicar", "confirmar"}:
            score = max(score, 92)
        return score + (3 if score and in_form else 0)


class SmartApplicationPreparer(CostAwareApplicationPreparer):
    """Default Job Agent preparer with semantic deterministic parity enabled."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.deterministic_application = SmartDeterministicApplicationRunner(
            self.profile_dir,
            self.answer_memory,
            self.pattern_store,
        )

    def application_efficiency(self) -> dict[str, object]:
        metrics = super().application_efficiency()
        memory = self.answer_memory.stats()
        return {
            **metrics,
            "semantic_zero_cost": True,
            "semantic_answer_coverage_pct": memory["answer_coverage_pct"],
            "semantic_answers": memory["answers"],
        }
