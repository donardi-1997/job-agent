from __future__ import annotations

import io
import json
import re
import shutil
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
    'Angular': ('angular',),
    'TypeScript': ('typescript',),
    'JavaScript': ('javascript',),
    'Node.js': ('node.js', 'nodejs'),
    '.NET': ('.net', 'dotnet'),
    'HTML': ('html',),
    'CSS': ('css',),
    'Terraform': ('terraform',),
    'CI/CD': ('ci/cd', 'continuous integration', 'continuous deployment'),
    'GitHub Actions': ('github actions',),
    'Lambda': ('aws lambda', 'lambda'),
    'DynamoDB': ('dynamodb',),
    'S3': ('amazon s3', 'aws s3', ' s3 '),
    'API Gateway': ('api gateway',),
    'Cognito': ('cognito',),
    'Bedrock': ('amazon bedrock', 'aws bedrock', 'bedrock'),
    'LLM': ('llm', 'large language model'),
    'RAG': ('rag', 'retrieval augmented generation'),
    'AI': ('artificial intelligence', 'inteligencia artificial', ' ai '),
    'Odoo': ('odoo',),
}

ROLE_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('Backend Developer', ('backend developer', 'backend engineer', 'desarrollador backend', 'fastapi', 'django', 'flask')),
    ('Python Developer', ('python developer', 'desarrollador python', 'python')),
    ('AWS Developer', ('aws developer', 'cloud developer', 'cloud engineer', 'amazon web services', 'aws')),
    ('AI Engineer', ('ai engineer', 'ingeniero de ia', 'artificial intelligence', 'inteligencia artificial', 'llm', 'rag', 'bedrock')),
    ('Full Stack Developer', ('full stack developer', 'fullstack developer', 'desarrollador full stack', 'full-stack')),
    ('DevOps Engineer', ('devops engineer', 'ingeniero devops', 'terraform', 'kubernetes', 'ci/cd')),
)


@dataclass(frozen=True)
class CVImportResult:
    filename: str
    text_chars: int
    detected_roles: tuple[str, ...]
    detected_skills: tuple[str, ...]
    variant_key: str = 'principal'
    stored_path: str = ''


class CVProfileService:
    """Manage local CV variants and choose the best one for each vacancy."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH, storage_dir: Path | str = Path('data/cv')) -> None:
        self.path = Path(path)
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.profile_store = ProfileStore(self.path)
        with self._connect() as connection:
            # Legacy single-CV table is kept for backwards compatibility with
            # previous local databases and dashboard clients.
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cv_variants (
                    variant_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    detected_roles TEXT NOT NULL DEFAULT '[]',
                    detected_skills TEXT NOT NULL DEFAULT '[]',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _variant_key(value: str) -> str:
        normalized = re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')
        return normalized[:80] or 'principal'

    def list_variants(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT variant_key, label, filename, stored_path, detected_roles,
                       detected_skills, is_default, updated_at
                FROM cv_variants
                ORDER BY is_default DESC, label COLLATE NOCASE ASC
                """
            ).fetchall()
        return [
            {
                'variant_key': row['variant_key'],
                'label': row['label'],
                'filename': row['filename'],
                'stored_path': row['stored_path'],
                'detected_roles': json.loads(row['detected_roles']),
                'detected_skills': json.loads(row['detected_skills']),
                'is_default': bool(row['is_default']),
                'updated_at': row['updated_at'],
            }
            for row in rows
        ]

    def get_variant(self, variant_key: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT variant_key, label, filename, stored_path, text_content,
                       detected_roles, detected_skills, is_default, updated_at
                FROM cv_variants WHERE variant_key = ?
                """,
                (variant_key,),
            ).fetchone()
        if not row:
            return None
        return {
            'variant_key': row['variant_key'],
            'label': row['label'],
            'filename': row['filename'],
            'stored_path': row['stored_path'],
            'text_content': row['text_content'],
            'detected_roles': json.loads(row['detected_roles']),
            'detected_skills': json.loads(row['detected_skills']),
            'is_default': bool(row['is_default']),
            'updated_at': row['updated_at'],
        }

    def status(self) -> dict[str, object]:
        variants = self.list_variants()
        default = next((item for item in variants if item['is_default']), None)
        with self._connect() as connection:
            row = connection.execute(
                'SELECT filename, text_content, detected_roles, detected_skills, updated_at FROM cv_profile WHERE id = 1'
            ).fetchone()
        if not row:
            return {
                'configured': bool(variants),
                'filename': str(default['filename']) if default else '',
                'text_chars': 0,
                'detected_roles': list(default['detected_roles']) if default else [],
                'detected_skills': list(default['detected_skills']) if default else [],
                'default_variant': str(default['variant_key']) if default else '',
                'variants': variants,
            }
        return {
            'configured': True,
            'filename': row['filename'],
            'text_chars': len(row['text_content']),
            'detected_roles': json.loads(row['detected_roles']),
            'detected_skills': json.loads(row['detected_skills']),
            'updated_at': row['updated_at'],
            'default_variant': str(default['variant_key']) if default else '',
            'variants': variants,
        }

    def import_bytes(
        self,
        filename: str,
        content: bytes,
        *,
        variant_name: str = 'Principal',
        activate: bool = True,
    ) -> CVImportResult:
        safe_name = Path(filename).name
        extension = Path(safe_name).suffix.casefold()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError('Formato no soportado. Usa PDF, DOCX o TXT.')
        if not content:
            raise ValueError('El CV está vacío.')
        if len(content) > MAX_CV_BYTES:
            raise ValueError('El CV supera el límite de 8 MB.')

        text = self._normalize_text(self._extract_text(extension, content))
        if len(text) < 100:
            raise ValueError('No se pudo extraer suficiente texto del CV. Si es un PDF escaneado, usa un PDF con texto seleccionable o DOCX.')

        skills = self._detect_skills(text)
        roles = self._detect_roles(text, skills)
        current_profile = self.profile_store.get()
        if not roles:
            roles = tuple(current_profile.target_roles)

        label = ' '.join(variant_name.strip().split()) or 'Principal'
        variant_key = self._variant_key(label)
        destination = self.storage_dir / f'{variant_key}{extension}'
        # A variant may be replaced by another file extension. Keep only the
        # current artifact for that variant key.
        for existing in self.storage_dir.glob(f'{variant_key}.*'):
            if existing != destination and existing.name != f'current{existing.suffix}':
                existing.unlink(missing_ok=True)
        destination.write_bytes(content)

        with self._connect() as connection:
            if activate:
                connection.execute('UPDATE cv_variants SET is_default = 0')
            connection.execute(
                """
                INSERT INTO cv_variants(
                    variant_key, label, filename, stored_path, text_content,
                    detected_roles, detected_skills, is_default, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(variant_key) DO UPDATE SET
                    label = excluded.label,
                    filename = excluded.filename,
                    stored_path = excluded.stored_path,
                    text_content = excluded.text_content,
                    detected_roles = excluded.detected_roles,
                    detected_skills = excluded.detected_skills,
                    is_default = CASE WHEN excluded.is_default = 1 THEN 1 ELSE cv_variants.is_default END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    variant_key,
                    label,
                    safe_name,
                    str(destination),
                    text,
                    json.dumps(roles, ensure_ascii=False),
                    json.dumps(skills, ensure_ascii=False),
                    1 if activate else 0,
                ),
            )

            if activate:
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

        if activate:
            profile = current_profile.model_copy(
                update={
                    'target_roles': list(roles),
                    'skills': list(skills) if skills else current_profile.skills,
                }
            )
            self.profile_store.save(profile)
            current_path = self.storage_dir / f'current{extension}'
            for existing in self.storage_dir.glob('current.*'):
                if existing != current_path:
                    existing.unlink(missing_ok=True)
            shutil.copyfile(destination, current_path)

        return CVImportResult(
            safe_name,
            len(text),
            roles,
            skills,
            variant_key=variant_key,
            stored_path=str(destination),
        )

    def activate_variant(self, variant_key: str) -> dict[str, object]:
        variant = self.get_variant(variant_key)
        if not variant:
            raise ValueError('Variante de CV no encontrada.')

        with self._connect() as connection:
            connection.execute('UPDATE cv_variants SET is_default = 0')
            connection.execute(
                'UPDATE cv_variants SET is_default = 1, updated_at = CURRENT_TIMESTAMP WHERE variant_key = ?',
                (variant_key,),
            )
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
                (
                    variant['filename'],
                    variant['text_content'],
                    json.dumps(variant['detected_roles'], ensure_ascii=False),
                    json.dumps(variant['detected_skills'], ensure_ascii=False),
                ),
            )

        profile = self.profile_store.get().model_copy(
            update={
                'target_roles': list(variant['detected_roles']),
                'skills': list(variant['detected_skills']) or self.profile_store.get().skills,
            }
        )
        self.profile_store.save(profile)

        source = Path(str(variant['stored_path']))
        if source.exists():
            current_path = self.storage_dir / f'current{source.suffix.casefold()}'
            for existing in self.storage_dir.glob('current.*'):
                if existing != current_path:
                    existing.unlink(missing_ok=True)
            shutil.copyfile(source, current_path)
        return variant

    @staticmethod
    def _match_variant(variant: dict[str, object], job_text: str) -> int:
        normalized = job_text.casefold()
        score = 0
        for role in variant.get('detected_roles', []):
            value = str(role).casefold()
            if value and value in normalized:
                score += 12
            else:
                for token in re.findall(r'[a-z0-9.+#/-]{3,}', value):
                    if token in normalized:
                        score += 3
        for skill in variant.get('detected_skills', []):
            value = str(skill).casefold()
            if value and value in normalized:
                score += 4
        label = str(variant.get('label') or '').casefold()
        for token in re.findall(r'[a-z0-9.+#/-]{3,}', label):
            if token in normalized:
                score += 2
        if variant.get('is_default'):
            score += 1
        return score

    def select_for_job(self, job: dict[str, object]) -> dict[str, object] | None:
        variants = self.list_variants()
        if not variants:
            return None
        text = ' '.join(
            str(job.get(key) or '')
            for key in ('title', 'description', 'company', 'location')
        )
        ranked = sorted(
            variants,
            key=lambda item: (self._match_variant(item, text), 1 if item.get('is_default') else 0, str(item.get('label'))),
            reverse=True,
        )
        return self.get_variant(str(ranked[0]['variant_key']))

    def path_for_job(self, job: dict[str, object]) -> Path | None:
        variant = self.select_for_job(job)
        if not variant:
            return None
        path = Path(str(variant['stored_path']))
        return path if path.exists() else None

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
            'AWS Developer': {'AWS', 'Lambda', 'DynamoDB', 'S3', 'API Gateway', 'Cognito'},
            'AI Engineer': {'AI', 'LLM', 'RAG', 'Bedrock'},
            'Full Stack Developer': {'React', 'Angular', 'TypeScript', 'JavaScript', 'Node.js', '.NET'},
            'DevOps Engineer': {'Docker', 'Kubernetes', 'Terraform', 'CI/CD', 'GitHub Actions'},
        }
        ranked: dict[str, int] = {role: score for score, _, role in matches}
        for role, role_skills in boosts.items():
            overlap = len(skill_set & role_skills)
            if overlap:
                ranked[role] = ranked.get(role, 0) + overlap

        return tuple(role for role, _ in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))[:6])
