from __future__ import annotations

import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from job_agent.profile import UserProfile
from job_agent.storage import DEFAULT_DB_PATH


def normalize_question(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


class AnswerMemory:
    """Single-user local memory for answers that have already been used successfully."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def _rows(self, limit: int = 200) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT question_normalized, question, answer, source, confidence, use_count, last_used_at
                FROM answer_memory
                ORDER BY use_count DESC, last_used_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve(self, question: str, profile: UserProfile) -> str | None:
        """Resolve a known answer without an LLM. Conservative matching avoids fabricated facts."""
        normalized = normalize_question(question)
        if not normalized:
            return None

        direct_profile = self._profile_answer(normalized, profile)
        if direct_profile:
            return direct_profile

        candidates: list[tuple[str, str]] = []
        for item in profile.frequent_answers:
            candidates.append((normalize_question(item.question), item.answer))
        for row in self._rows():
            candidates.append((str(row["question_normalized"]), str(row["answer"])))

        for candidate, answer in candidates:
            if candidate == normalized:
                return answer
        for candidate, answer in candidates:
            if candidate and SequenceMatcher(None, candidate, normalized).ratio() >= 0.90:
                return answer
        return None

    @staticmethod
    def _profile_answer(normalized: str, profile: UserProfile) -> str | None:
        rules: tuple[tuple[tuple[str, ...], str], ...] = (
            (("ciudad", "residencia"), profile.city),
            (("nivel de ingles", "ingles"), profile.english_level),
            (("aspiracion salarial", "pretension salarial", "salario esperado"), profile.salary_expectation),
            (("disponibilidad", "cuando puedes empezar"), profile.availability),
        )
        for needles, answer in rules:
            if answer and any(needle in normalized for needle in needles):
                return answer
        return None

    def context_for_agent(self, profile: UserProfile, limit: int = 80) -> list[dict[str, str]]:
        """Return compact, deterministic answers the browser agent should reuse verbatim."""
        context: list[dict[str, str]] = []
        seen: set[str] = set()
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
                        "source": "learned",
                    }
                )
        return context[:limit]

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS answers, COALESCE(SUM(use_count), 0) AS uses FROM answer_memory"
            ).fetchone()
        return {"answers": int(row["answers"]), "uses": int(row["uses"])} if row else {"answers": 0, "uses": 0}
