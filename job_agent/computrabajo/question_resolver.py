from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from browser_use.llm.messages import SystemMessage, UserMessage

from job_agent.ai_usage import AIUsageBudget, AIUsageStore, MeteredChatBrowserUse, UsageSnapshot
from job_agent.profile import UserProfile
from job_agent.storage import DEFAULT_DB_PATH


DEFAULT_QUESTION_MODEL = "bu-2-0"


class QuestionResolution(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=4000)
    confidence: int = Field(default=0, ge=0, le=100)
    supported: bool = False
    reason: str = Field(default="", max_length=600)


class QuestionResolutionBatch(BaseModel):
    resolutions: list[QuestionResolution] = Field(default_factory=list, max_length=20)


class CompactQuestionResolver:
    """Resolve only unknown application questions with a compact text-only LLM call.

    Browser navigation stays deterministic. The resolver receives only the exact
    unanswered questions and a small set of candidate facts, so it is dramatically
    cheaper than launching a full Browser Use agent with DOM/screenshots/history.
    """

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.usage_store = AIUsageStore(self.path)

    @staticmethod
    def candidate_facts(profile: UserProfile) -> dict[str, object]:
        return {
            "target_roles": profile.target_roles[:20],
            "verified_skills": profile.skills[:60],
            "years_experience_total": profile.years_experience,
            "city": profile.city,
            "english_level": profile.english_level,
            "salary_expectation": profile.salary_expectation,
            "availability": profile.availability,
            "preferred_locations": profile.preferred_locations[:12],
            "preferred_work_modes": profile.preferred_work_modes[:8],
            "preferred_contract_types": profile.preferred_contract_types[:8],
            "professional_context": profile.professional_summary[:2200],
        }

    async def resolve(
        self,
        *,
        job: dict[str, object],
        profile: UserProfile,
        questions: list[dict[str, object]],
        ai_budget: AIUsageBudget | None = None,
    ) -> QuestionResolutionBatch:
        if not questions:
            return QuestionResolutionBatch()
        if not os.getenv("BROWSER_USE_API_KEY"):
            return QuestionResolutionBatch(
                resolutions=[
                    QuestionResolution(
                        question=str(item.get("question") or "Pregunta"),
                        supported=False,
                        reason="No hay BROWSER_USE_API_KEY para resolver esta pregunta nueva.",
                    )
                    for item in questions
                    if str(item.get("question") or "").strip()
                ]
            )

        requested_model = os.getenv("JOB_AGENT_QUESTION_MODEL", DEFAULT_QUESTION_MODEL)
        job_id_raw = job.get("id")
        job_id = int(job_id_raw) if isinstance(job_id_raw, (int, str)) and str(job_id_raw).isdigit() else None

        def persist_usage(snapshot: UsageSnapshot) -> None:
            self.usage_store.record_safely(
                "question_resolution",
                snapshot,
                job_id=job_id,
                metadata={
                    "title": str(job.get("title") or ""),
                    "granularity": "compact_question_batch",
                    "requested_model": requested_model,
                    "question_count": len(questions),
                },
            )

        llm = MeteredChatBrowserUse(
            model=requested_model,
            on_usage=persist_usage,
            usage_budget=ai_budget,
        )
        system = SystemMessage(
            content=(
                "You resolve job-application questions from supplied candidate facts only. "
                "Never invent or extrapolate personal facts. If a question asks for a fact, quantity, date, legal declaration, "
                "specific years with a technology, salary fact, language level, work authorization, or experience that is not "
                "explicitly supported, set supported=false and leave answer empty. Rephrase supplied facts only when the answer "
                "remains semantically identical. For select/radio questions, use an offered option exactly when supported. "
                "Return one resolution for every input question and nothing unrelated."
            )
        )
        compact_questions = [
            {
                "question": str(item.get("question") or "")[:1000],
                "field_type": str(item.get("field_type") or "text")[:80],
                "options": [str(option)[:300] for option in (item.get("options") or [])][:30],
            }
            for item in questions
            if str(item.get("question") or "").strip()
        ]
        user = UserMessage(
            content=json.dumps(
                {
                    "candidate_facts": self.candidate_facts(profile),
                    "vacancy": {
                        "title": str(job.get("title") or "")[:300],
                        "company": str(job.get("company") or "")[:300],
                        "location": str(job.get("location") or "")[:300],
                    },
                    "questions": compact_questions,
                },
                ensure_ascii=False,
            )
        )
        completion = await llm.ainvoke(
            [system, user],
            output_format=QuestionResolutionBatch,
            request_type="judge",
        )
        result = completion.completion
        if not isinstance(result, QuestionResolutionBatch):
            result = QuestionResolutionBatch.model_validate(result)

        # A low-confidence answer is treated as unknown. The deterministic form
        # runner should never type a speculative personal answer just to save a call.
        safe: list[QuestionResolution] = []
        input_questions = {str(item["question"]).strip() for item in compact_questions}
        for item in result.resolutions:
            if item.question not in input_questions:
                continue
            supported = bool(item.supported and item.answer.strip() and item.confidence >= 90)
            safe.append(
                item.model_copy(
                    update={
                        "supported": supported,
                        "answer": item.answer.strip() if supported else "",
                    }
                )
            )
        return QuestionResolutionBatch(resolutions=safe)
