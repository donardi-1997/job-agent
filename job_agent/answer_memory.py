from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from job_agent.computrabajo.semantic_answers import (
    LocalSemanticAnswer,
    LocalSemanticAnswerEngine,
    classify_question,
    semantic_similarity,
)
from job_agent.profile import UserProfile
from job_agent.storage import DEFAULT_DB_PATH


def normalize_question(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


class AnswerMemory:
    """Single-user local semantic memory for successfully used answers."""

    _LOW_RISK_INTENTS = {
        "city",
        "english_level",
        "salary",
        "availability",
        "total_experience_years",
        "work_mode",
        "contract_type",
        "professional_summary",
        "motivation",
        "strengths",
    }

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.semantic_engine = LocalSemanticAnswerEngine(self.path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS answer_memory (
                    question_normalized TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'application',
                    confidence INTEGER NOT NULL DEFAULT 100,
                    use_count INTEGER NOT NULL DEFAULT 1,
                    last_used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_answer_memory_last_used
                    ON answer_memory(last_used_at DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def remember(
        self,
        question: str,
        answer: str,
        *,
        source: str = "application",
        confidence: int = 100,
    ) -> None:
        normalized = normalize_question(question)
        clean_answer = " ".join(answer.strip().split())
        if not normalized or not clean_answer:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO answer_memory(
                    question_normalized, question, answer, source, confidence, use_count,
                    last_used_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(question_normalized) DO UPDATE SET
                    question=excluded.question,
                    answer=excluded.answer,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    use_count=answer_memory.use_count + 1,
                    last_used_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (normalized, question.strip(), clean_answer, source, max(0, min(100, confidence))),
            )

    def forget(self, question: str) -> bool:
        normalized = normalize_question(question)
        if not normalized:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM answer_memory WHERE question_normalized = ?",
                (normalized,),
            )
            return cursor.rowcount > 0

    def remember_questions(self, questions: list[dict[str, object]], *, submitted: bool) -> int:
        if not submitted:
            return 0
        count = 0
        for item in questions:
            answer = str(item.get("suggested_answer") or "").strip()
            question = str(item.get("question") or "").strip()
            requires_input = bool(item.get("requires_user_input"))
            confidence = int(item.get("confidence") or 0)
            if question and answer and not requires_input and confidence >= 90:
                self.remember(question, answer, confidence=confidence)
                count += 1
        return count

    def _rows(self, limit: int = 300, *, source: str | None = None) -> list[dict[str, object]]:
        query = """
            SELECT question_normalized, question, answer, source, confidence, use_count, last_used_at
            FROM answer_memory
        """
        params: list[object] = []
        if source is not None:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY use_count DESC, confidence DESC, last_used_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    @classmethod
    def _similarity_threshold(cls, question: str) -> float:
        intent = classify_question(question).intent
        return 0.86 if intent in cls._LOW_RISK_INTENTS else 0.91

    @classmethod
    def _best_candidate(
        cls,
        question: str,
        candidates: list[dict[str, object]],
    ) -> tuple[dict[str, object], float] | None:
        normalized = normalize_question(question)
        for row in candidates:
            if str(row.get("question_normalized") or "") == normalized:
                return row, 1.0

        best: tuple[dict[str, object], float] | None = None
        for row in candidates:
            candidate_question = str(row.get("question") or "")
            if not candidate_question:
                continue
            score = semantic_similarity(question, candidate_question)
            if best is None or score > best[1]:
                best = (row, score)

        threshold = cls._similarity_threshold(question)
        return best if best is not None and best[1] >= threshold else None

    def _memory_resolution(
        self,
        question: str,
        profile: UserProfile,
        candidates: list[dict[str, object]],
        *,
        source: str,
        field_type: str,
        options: tuple[str, ...],
    ) -> LocalSemanticAnswer | None:
        matched = self._best_candidate(question, candidates)
        if matched is None:
            return None
        row, similarity = matched
        raw = str(row.get("answer") or "").strip()
        if not raw:
            return None
        semantic_match = classify_question(
            question,
            known_locations=[profile.city, *profile.preferred_locations],
        )
        answer = self.semantic_engine.adapt_to_options(
            raw,
            options=options,
            intent=semantic_match.intent,
            match=semantic_match,
        )
        if answer is None:
            return None
        stored_confidence = int(row.get("confidence") or 100)
        confidence = min(stored_confidence, max(90, round(similarity * 100)))
        return LocalSemanticAnswer(
            answer=answer,
            confidence=confidence,
            source=source,
            intent=semantic_match.intent,
            reason=(
                "Coincidencia exacta en memoria local."
                if similarity == 1.0
                else f"Pregunta equivalente reconocida localmente ({similarity:.2f})."
            ),
        )

    def resolve_context(
        self,
        question: str,
        profile: UserProfile,
        *,
        field_type: str = "text",
        options: tuple[str, ...] = (),
        job: dict[str, object] | None = None,
    ) -> LocalSemanticAnswer | None:
        """Resolve with semantic intent, option mapping and evidence provenance."""
        if not normalize_question(question):
            return None

        manual = self._memory_resolution(
            question,
            profile,
            self._rows(source="manual"),
            source="manual",
            field_type=field_type,
            options=options,
        )
        if manual:
            return manual

        direct = self.semantic_engine.resolve_profile(
            question,
            profile,
            field_type=field_type,
            options=options,
            job=job,
        )
        if direct:
            return direct

        profile_candidates = [
            {
                "question_normalized": normalize_question(item.question),
                "question": item.question,
                "answer": item.answer,
                "source": "profile",
                "confidence": 100,
            }
            for item in profile.frequent_answers
        ]
        frequent = self._memory_resolution(
            question,
            profile,
            profile_candidates,
            source="profile",
            field_type=field_type,
            options=options,
        )
        if frequent:
            return frequent

        learned = [
            row
            for row in self._rows()
            if str(row.get("source") or "") != "manual"
        ]
        return self._memory_resolution(
            question,
            profile,
            learned,
            source="learned",
            field_type=field_type,
            options=options,
        )

    def resolve(self, question: str, profile: UserProfile) -> str | None:
        result = self.resolve_context(question, profile)
        return result.answer if result else None

    def context_for_agent(self, profile: UserProfile, limit: int = 80) -> list[dict[str, str]]:
        context: list[dict[str, str]] = []
        seen: set[str] = set()

        for row in self._rows(limit=limit, source="manual"):
            normalized = str(row["question_normalized"])
            if normalized and normalized not in seen:
                seen.add(normalized)
                context.append(
                    {
                        "question": str(row["question"]),
                        "answer": str(row["answer"]),
                        "source": "manual",
                    }
                )

        for item in profile.frequent_answers:
            normalized = normalize_question(item.question)
            if normalized and normalized not in seen:
                seen.add(normalized)
                context.append({"question": item.question, "answer": item.answer, "source": "profile"})

        for row in self._rows(limit=limit):
            normalized = str(row["question_normalized"])
            if normalized not in seen:
                seen.add(normalized)
                context.append(
                    {
                        "question": str(row["question"]),
                        "answer": str(row["answer"]),
                        "source": str(row.get("source") or "learned"),
                    }
                )
        return context[:limit]

    def stats(self) -> dict[str, int | float]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS answers, COALESCE(SUM(use_count), 0) AS uses FROM answer_memory"
            ).fetchone()
            memory_rows = connection.execute(
                "SELECT question_normalized, question FROM answer_memory"
            ).fetchall()
            attempts_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='application_attempts'"
            ).fetchone()
            attempt_rows = (
                connection.execute("SELECT payload, submitted FROM application_attempts").fetchall()
                if attempts_table
                else []
            )

        encountered: dict[str, str] = {}
        submitted_applications = 0
        for attempt in attempt_rows:
            if bool(attempt["submitted"]):
                submitted_applications += 1
            try:
                payload = json.loads(str(attempt["payload"] or "{}"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            questions = payload.get("questions") or []
            if not isinstance(questions, list):
                continue
            for item in questions:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question") or "").strip()
                normalized = normalize_question(question)
                if normalized:
                    encountered[normalized] = question

        memory_questions = [
            (str(item["question_normalized"]), str(item["question"]))
            for item in memory_rows
        ]
        learned_encountered = 0
        for normalized, original in encountered.items():
            if any(key == normalized for key, _ in memory_questions):
                learned_encountered += 1
                continue
            threshold = self._similarity_threshold(original)
            if any(semantic_similarity(original, candidate) >= threshold for _, candidate in memory_questions):
                learned_encountered += 1

        coverage = round((learned_encountered / len(encountered) * 100), 1) if encountered else 0.0
        return {
            "answers": int(row["answers"]),
            "uses": int(row["uses"]),
            "encountered_questions": len(encountered),
            "learned_questions": learned_encountered,
            "answer_coverage_pct": coverage,
            "submitted_applications": submitted_applications,
        } if row else {
            "answers": 0,
            "uses": 0,
            "encountered_questions": len(encountered),
            "learned_questions": learned_encountered,
            "answer_coverage_pct": coverage,
            "submitted_applications": submitted_applications,
        }
