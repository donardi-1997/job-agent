from __future__ import annotations

import io
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from job_agent.profile import ProfileStore
from job_agent.storage import DEFAULT_DB_PATH


MAX_CV_BYTES = 8 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.txt'}

# Deliberately conservative: only promote skills explicitly present in the CV.
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    'Python': ('python',),
    'FastAPI': ('fastapi', 'fast api'),
    'Django': ('django',),
    'Flask': ('flask',),
    'AWS': ('aws', 'amazon web services'),
    'Azure': ('azure',),
    'GCP': ('gcp', 'google cloud'),
    'SQL': ('sql',),
    'PostgreSQL': ('postgresql', 'postgres'),
    'MySQL': ('mysql',),
    'SQLite': ('sqlite',),
    'Docker': ('docker',),
    'Kubernetes': ('kubernetes', 'k8s'),
    'Git': ('git', 'github'),
    'Linux': ('linux',),
    'REST APIs': ('rest api', 'restful', 'apis rest', 'api rest'),
    'React': ('react', 'reactjs', 'react.js'),
    'TypeScript': ('typescript',),
    'JavaScript': ('javascript',),
    'Node.js': ('node.js', 'nodejs'),
    'HTML': ('html',),
    'CSS': ('css',),
    'Terraform': ('terraform',),
    'CI/CD': ('ci/cd', 'continuous integration', 'continuous deployment'),
    'GitHub Actions': ('github actions',),
    'Lambda': ('aws lambda', 'lambda'),
    'DynamoDB': ('dynamodb',),
    'S3': ('amazon s3', 'aws s3', ' s3 '),
    'API Gateway': ('api gateway',),
    'Bedrock': ('amazon bedrock', 'aws bedrock', 'bedrock'),
    'LLM': ('llm', 'large language model'),
    'RAG': ('rag', 'retrieval augmented generation'),
    'AI': ('artificial intelligence', 'inteligencia artificial', ' ai '),
}

ROLE_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('Backend Developer', ('backend developer', 'backend engineer', 'desarrollador backend', 'fastapi', 'django', 'flask')),
    ('Python Developer', ('python developer', 'desarrollador python', 'python')),
    ('AWS Developer', ('aws developer', 'cloud developer', 'cloud engineer', 'amazon web services', 'aws')),
    ('AI Engineer', ('ai engineer', 'ingeniero de ia', 'artificial intelligence', 'inteligencia artificial', 'llm', 'rag', 'bedrock')),
    ('Full Stack Developer', ('full stack developer', 'fullstack developer', 'desarrollador full stack', 'full-stack')),
    ('DevOps Engineer', ('devops engineer', 'ingeniero devops', 'terraform', 'kubernetes')),
)


@dataclass(frozen=True)
class CVImportResult:
    filename: str
    text_chars: int
    detected_roles: tuple[str, ...]
    detected_skills: tuple[str, ...]


class CVProfileService:
    """Imports one personal CV locally and derives search/profile signals from it."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH, storage_dir: Path | str = Path('data/cv')) -> None:
        self.path = Path(path)
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.profile_store = ProfileStore(self.path)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cv_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    filename TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    detected_roles TEXT NOT NULL DEFAULT '[]',
                    detected_skills TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def status(self) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                'SELECT filename, text_content, detected_roles, detected_skills, updated_at FROM cv_profile WHERE id = 1'
            ).fetchone()
        if not row:
            return {'configured': False, 'filename': '', 'text_chars': 0, 'detected_roles': [], 'detected_skills': []}
        return {
            'configured': True,
            'filename': row['filename'],
            'text_chars': len(row['text_content']),
            'detected_roles': json.loads(row['detected_roles']),
            'detected_skills': json.loads(row['detected_skills']),
            'updated_at': row['updated_at'],
        }

    def import_bytes(self, filename: str, content: bytes) -> CVImportResult:
        safe_name = Path(filename).name
        extension = Path(safe_name).suffix.casefold()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError('Formato no soportado. Usa PDF, DOCX o TXT.')
        if not content:
            raise ValueError('El CV está vacío.')
        if len(content) > MAX_CV_BYTES:
            raise ValueError('El CV supera el límite de 8 MB.')

        text = self._extract_text(extension, content)
        text = self._normalize_text(text)
        if len(text) < 100:
            raise ValueError('No se pudo extraer suficiente texto del CV. Si es un PDF escaneado, usa un PDF con texto seleccionable o DOCX.')

        skills = self._detect_skills(text)
        roles = self._detect_roles(text, skills)
        if not roles:
            roles = tuple(self.profile_store.get().target_roles)

        # CV evidence becomes the default search/scoring profile, while personal
        # application facts (salary, availability, English, etc.) stay untouched.
        profile = self.profile_store.get().model_copy(
            update={
                'target_roles': list(roles),
                'skills': list(skills) if skills else self.profile_store.get().skills,
            }
        )
        self.profile_store.save(profile)

        destination = self.storage_dir / f'current{extension}'
        for existing in self.storage_dir.glob('current.*'):
            if existing != destination:
                existing.unlink(missing_ok=True)
        destination.write_bytes(content)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cv_profile(id, filename, text_content, detected_roles, detected_skills, updated_at)
                VALUES(1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    filename = excluded.filename,
                    text_content = excluded.text_content,
                    detected_roles = excluded.detected_roles,
                    detected_skills = excluded.detected_skills,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (safe_name, text, json.dumps(roles, ensure_ascii=False), json.dumps(skills, ensure_ascii=False)),
            )
        return CVImportResult(safe_name, len(text), roles, skills)

    @staticmethod
    def _extract_text(extension: str, content: bytes) -> str:
        if extension == '.pdf':
            reader = PdfReader(io.BytesIO(content))
            return '\n'.join(page.extract_text() or '' for page in reader.pages)
        if extension == '.docx':
            document = Document(io.BytesIO(content))
            return '\n'.join(paragraph.text for paragraph in document.paragraphs)
        return content.decode('utf-8-sig', errors='replace')

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r'[ \t]+', ' ', text.replace('\x00', ' ')).strip()

    @staticmethod
    def _contains(text: str, alias: str) -> bool:
        # Word-like boundaries avoid SQL matching inside unrelated words.
        normalized = text.casefold()
        needle = alias.casefold().strip()
        if not needle:
            return False
        return re.search(rf'(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])', normalized) is not None

    @classmethod
    def _detect_skills(cls, text: str) -> tuple[str, ...]:
        return tuple(
            canonical
            for canonical, aliases in SKILL_ALIASES.items()
            if any(cls._contains(text, alias) for alias in aliases)
        )

    @classmethod
    def _detect_roles(cls, text: str, skills: tuple[str, ...]) -> tuple[str, ...]:
        matches: list[tuple[int, int, str]] = []
        normalized = text.casefold()
        for order, (role, signals) in enumerate(ROLE_SIGNALS):
            score = sum(2 if signal.casefold() in normalized else 0 for signal in signals[:3])
            score += sum(1 if signal.casefold() in normalized else 0 for signal in signals[3:])
            if score:
                matches.append((score, -order, role))

        skill_set = set(skills)
        boosts = {
            'Backend Developer': {'Python', 'FastAPI', 'Django', 'Flask', 'REST APIs'},
            'Python Developer': {'Python'},
            'AWS Developer': {'AWS', 'Lambda', 'DynamoDB', 'S3', 'API Gateway'},
            'AI Engineer': {'AI', 'LLM', 'RAG', 'Bedrock'},
            'Full Stack Developer': {'React', 'TypeScript', 'JavaScript', 'Node.js'},
            'DevOps Engineer': {'Docker', 'Kubernetes', 'Terraform', 'CI/CD'},
        }
        ranked: dict[str, int] = {role: score for score, _, role in matches}
        for role, role_skills in boosts.items():
            overlap = len(skill_set & role_skills)
            if overlap:
                ranked[role] = ranked.get(role, 0) + overlap

        return tuple(role for role, _ in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))[:6])
