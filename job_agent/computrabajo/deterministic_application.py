from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from browser_use import Browser

from job_agent.answer_memory import AnswerMemory, normalize_question
from job_agent.computrabajo.browser_config import allowed_domains
from job_agent.profile import UserProfile
from job_agent.storage import DEFAULT_DB_PATH


ALLOWED_APPLICATION_HOSTS = {
    "co.computrabajo.com",
    "secure.computrabajo.com",
    "candidato.co.computrabajo.com",
}


@dataclass(frozen=True)
class ObservedField:
    question: str
    field_type: str
    selector: str
    options: tuple[str, ...] = ()
    required: bool = False
    current_value: str = ""


@dataclass(frozen=True)
class DeterministicApplicationQuestion:
    question: str
    field_type: str
    options: tuple[str, ...]
    answer: str
    confidence: int
    requires_user_input: bool
    note: str = ""


@dataclass(frozen=True)
class DeterministicApplicationResult:
    questions: tuple[DeterministicApplicationQuestion, ...] = ()
    observed_fields: tuple[ObservedField, ...] = ()
    application_url: str = ""
    login_required: bool = False
    blocked_reason: str = ""
    fallback_reason: str = ""
    submitted: bool = False
    submission_status: str = "not_submitted"
    confirmation_text: str = ""
    confirmation_url: str = ""
    steps: int = 0
    mode: str = "test"
    test_mode: bool = True
    ready_to_submit: bool = False

    @property
    def terminal_without_ai(self) -> bool:
        return self.submitted or bool(self.blocked_reason)


def is_safe_application_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_APPLICATION_HOSTS


def _runtime_value(result: Any) -> Any:
    if isinstance(result, dict):
        payload = result.get("result")
        if isinstance(payload, dict):
            return payload.get("value")
    return None


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class ApplicationExecutionStore:
    """Measure how often applications can run without an LLM."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS application_execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    mode TEXT NOT NULL CHECK(mode IN ('deterministic', 'ai_fallback')),
                    submitted INTEGER NOT NULL DEFAULT 0,
                    unresolved_fields INTEGER NOT NULL DEFAULT 0,
                    fallback_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def record(
        self,
        *,
        job_id: int | None,
        mode: str,
        submitted: bool,
        unresolved_fields: int = 0,
        fallback_reason: str = "",
    ) -> None:
        if mode not in {"deterministic", "ai_fallback"}:
            raise ValueError(f"Unsupported application mode: {mode}")
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO application_execution_log(job_id, mode, submitted, unresolved_fields, fallback_reason)
                VALUES(?, ?, ?, ?, ?)
                """,
                (job_id, mode, 1 if submitted else 0, int(unresolved_fields), fallback_reason[:1000]),
            )

    def summary(self) -> dict[str, object]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN mode='deterministic' THEN 1 ELSE 0 END), 0) AS deterministic,
                    COALESCE(SUM(CASE WHEN mode='ai_fallback' THEN 1 ELSE 0 END), 0) AS ai_fallback,
                    COALESCE(SUM(submitted), 0) AS submitted
                FROM application_execution_log
                """
            ).fetchone()
        total = int(row[0]) if row else 0
        deterministic = int(row[1]) if row else 0
        fallback = int(row[2]) if row else 0
        submitted = int(row[3]) if row else 0
        return {
            "total": total,
            "deterministic": deterministic,
            "ai_fallback": fallback,
            "submitted": submitted,
            "deterministic_rate": round(deterministic / total * 100, 1) if total else 0.0,
        }


class ApplicationPatternStore:
    """Learn field labels/selectors seen on successful Computrabajo forms."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS application_field_patterns (
                    question_normalized TEXT NOT NULL,
                    field_type TEXT NOT NULL,
                    question TEXT NOT NULL,
                    selector_hint TEXT NOT NULL DEFAULT '',
                    options_json TEXT NOT NULL DEFAULT '[]',
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    successful_uses INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(question_normalized, field_type)
                )
                """
            )

    def observe(self, fields: tuple[ObservedField, ...]) -> None:
        with sqlite3.connect(self.path) as connection:
            for field in fields:
                normalized = normalize_question(field.question)
                if not normalized or field.field_type == "password":
                    continue
                connection.execute(
                    """
                    INSERT INTO application_field_patterns(
                        question_normalized, field_type, question, selector_hint, options_json,
                        seen_count, successful_uses, last_seen_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(question_normalized, field_type) DO UPDATE SET
                        question=excluded.question,
                        selector_hint=CASE WHEN excluded.selector_hint <> '' THEN excluded.selector_hint ELSE application_field_patterns.selector_hint END,
                        options_json=excluded.options_json,
                        seen_count=application_field_patterns.seen_count + 1,
                        last_seen_at=CURRENT_TIMESTAMP,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        normalized,
                        field.field_type,
                        field.question,
                        field.selector,
                        json.dumps(field.options, ensure_ascii=False),
                    ),
                )

    def confirm_success(self, fields: tuple[ObservedField, ...], answered_questions: list[str] | None = None) -> None:
        allowed = {normalize_question(item) for item in (answered_questions or []) if normalize_question(item)}
        with sqlite3.connect(self.path) as connection:
            for field in fields:
                normalized = normalize_question(field.question)
                if not normalized or field.field_type == "password":
                    continue
                if allowed and not any(
                    candidate == normalized or SequenceMatcher(None, candidate, normalized).ratio() >= 0.90
                    for candidate in allowed
                ):
                    continue
                connection.execute(
                    """
                    UPDATE application_field_patterns
                    SET successful_uses = successful_uses + 1, updated_at=CURRENT_TIMESTAMP
                    WHERE question_normalized = ? AND field_type = ?
                    """,
                    (normalized, field.field_type),
                )

    def stats(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS patterns,
                       COALESCE(SUM(CASE WHEN successful_uses > 0 THEN 1 ELSE 0 END), 0) AS proven_patterns,
                       COALESCE(SUM(seen_count), 0) AS observations,
                       COALESCE(SUM(successful_uses), 0) AS successful_uses
                FROM application_field_patterns
                """
            ).fetchone()
        return {
            "patterns": int(row[0]) if row else 0,
            "proven_patterns": int(row[1]) if row else 0,
            "observations": int(row[2]) if row else 0,
            "successful_uses": int(row[3]) if row else 0,
        }


class DeterministicApplicationRunner:
    """Try to complete known Computrabajo application flows without an LLM.

    It intentionally does not type stored passwords. Native login or Google OAuth is
    handed to the existing Browser Use fallback, which uses sensitive_data placeholders.
    """

    def __init__(
        self,
        profile_dir: Path | str,
        answer_memory: AnswerMemory,
        pattern_store: ApplicationPatternStore,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.answer_memory = answer_memory
        self.pattern_store = pattern_store
        self._mode = "test"

    async def apply(
        self,
        *,
        job: dict[str, object],
        profile: UserProfile,
        saved_draft: dict[str, object],
        max_steps: int = 12,
        mode: str = "test",
    ) -> DeterministicApplicationResult:
        if mode not in {"test", "real"}:
            raise ValueError("mode must be 'test' or 'real'")
        self._mode = mode
        job_url = str(job.get("url") or "")
        if not is_safe_application_url(job_url):
            return DeterministicApplicationResult(fallback_reason="URL de vacante fuera de la allowlist de Computrabajo.")

        browser = Browser(
            user_data_dir=str(self.profile_dir.resolve()),
            headless=False,
            allowed_domains=allowed_domains(),
        )
        observed: dict[tuple[str, str], ObservedField] = {}
        questions: dict[tuple[str, str], DeterministicApplicationQuestion] = {}
        try:
            await browser.start()
            cdp = await browser.get_or_create_cdp_session(browser.agent_focus_target_id, focus=True)
            await cdp.cdp_client.send.Page.enable(session_id=cdp.session_id)
            await self._navigate(cdp, job_url)

            previous_fingerprint = ""
            stagnant_steps = 0
            for step in range(1, max_steps + 1):
                state = await self._evaluate(cdp, self._snapshot_script())
                if not isinstance(state, dict):
                    return self._result(
                        observed, questions, step, fallback_reason="No se pudo leer el formulario de Computrabajo."
                    )

                current_url = _clean(state.get("url"))
                body = _clean(state.get("body"))
                if not is_safe_application_url(current_url):
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        login_required="accounts.google.com" in current_url,
                        fallback_reason=f"Redirección fuera del flujo determinístico: {current_url or 'sin URL'}",
                    )

                challenge = self._challenge_reason(body)
                if challenge:
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        blocked_reason=challenge,
                    )

                confirmation = self._submission_confirmation(body)
                if confirmation:
                    self.pattern_store.confirm_success(tuple(observed.values()))
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        submitted=True,
                        submission_status="submitted" if confirmation != "already_applied" else "already_applied",
                        confirmation_text=(
                            "Computrabajo indica que la postulación ya había sido realizada."
                            if confirmation == "already_applied"
                            else "Postulación confirmada por Computrabajo."
                        ),
                        confirmation_url=current_url,
                    )

                raw_fields = state.get("fields") or []
                fields = self._parse_fields(raw_fields)
                for field in fields:
                    key = (normalize_question(field.question), field.field_type)
                    if key[0]:
                        observed[key] = field
                if fields:
                    self.pattern_store.observe(tuple(fields))

                if any(field.field_type == "password" for field in fields):
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        login_required=True,
                        fallback_reason="Computrabajo solicita autenticación nativa; las credenciales se reservan para el fallback seguro.",
                    )

                unresolved_required: list[ObservedField] = []
                answers_to_fill: list[tuple[ObservedField, str]] = []
                for field in fields:
                    if field.field_type in {"hidden", "submit", "button", "file", "password"}:
                        if field.field_type == "file" and field.required:
                            unresolved_required.append(field)
                        continue
                    if field.current_value and field.field_type not in {"checkbox", "radio"}:
                        question = DeterministicApplicationQuestion(
                            question=field.question,
                            field_type=field.field_type,
                            options=field.options,
                            answer=field.current_value,
                            confidence=100,
                            requires_user_input=False,
                            note="Valor ya presente en el perfil/formulario de Computrabajo.",
                        )
                        questions[(normalize_question(field.question), field.field_type)] = question
                        continue

                    answer = self._resolve_answer(field, profile, saved_draft)
                    if answer is not None:
                        answers_to_fill.append((field, answer))
                        questions[(normalize_question(field.question), field.field_type)] = DeterministicApplicationQuestion(
                            question=field.question,
                            field_type=field.field_type,
                            options=field.options,
                            answer=answer,
                            confidence=100,
                            requires_user_input=False,
                            note="Resuelto localmente desde Mi perfil, borrador o memoria aprendida.",
                        )
                    elif field.required:
                        unresolved_required.append(field)
                        questions[(normalize_question(field.question), field.field_type)] = DeterministicApplicationQuestion(
                            question=field.question,
                            field_type=field.field_type,
                            options=field.options,
                            answer="",
                            confidence=0,
                            requires_user_input=True,
                            note="Sin respuesta determinística segura.",
                        )

                if answers_to_fill:
                    fill_result = await self._fill_fields(cdp, answers_to_fill)
                    if not fill_result:
                        return self._result(
                            observed,
                            questions,
                            step,
                            application_url=current_url,
                            fallback_reason="No se pudieron aplicar de forma determinística todos los valores conocidos.",
                        )
                    await asyncio.sleep(0.35)

                if unresolved_required:
                    labels = ", ".join(field.question[:80] for field in unresolved_required[:4])
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        fallback_reason=f"{len(unresolved_required)} campo(s) obligatorio(s) sin respuesta local: {labels}",
                    )

                action = self._choose_action(state.get("actions") or [])
                if not action:
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        fallback_reason="No se encontró un siguiente paso seguro y conocido en el formulario.",
                    )
                if mode == "test" and self._is_final_submission_action(action):
                    return self._result(observed, questions, step, application_url=current_url,
                        submission_status="test_ready", mode="test", test_mode=True, ready_to_submit=True,
                        fallback_reason="Formulario completado en modo prueba. Listo para enviar.")

                fingerprint = f"{current_url}|{action.get('text', '')}|{len(fields)}|{body[:300]}"
                if fingerprint == previous_fingerprint:
                    stagnant_steps += 1
                else:
                    stagnant_steps = 0
                previous_fingerprint = fingerprint
                if stagnant_steps >= 2:
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        fallback_reason="El flujo determinístico se estancó en el mismo paso.",
                    )

                if not await self._click_action(cdp, str(action.get("selector") or "")):
                    return self._result(
                        observed,
                        questions,
                        step,
                        application_url=current_url,
                        fallback_reason=f"No se pudo ejecutar el paso conocido: {_clean(action.get('text'))}",
                    )
                await asyncio.sleep(0.8)

            return self._result(
                observed,
                questions,
                max_steps,
                fallback_reason="El formulario excedió el máximo de pasos determinísticos.",
            )
        finally:
            await browser.stop()

    def _result(
        self,
        observed: dict[tuple[str, str], ObservedField],
        questions: dict[tuple[str, str], DeterministicApplicationQuestion],
        steps: int,
        **kwargs: object,
    ) -> DeterministicApplicationResult:
        return DeterministicApplicationResult(
            questions=tuple(questions.values()),
            observed_fields=tuple(observed.values()),
            steps=steps,
            mode=str(kwargs.pop("mode", self._mode)),
            test_mode=bool(kwargs.pop("test_mode", self._mode == "test")),
            **kwargs,
        )

    @staticmethod
    def _is_final_submission_action(action: dict[str, object]) -> bool:
        text = normalize_question(_clean(action.get("text")))
        return any(marker in text for marker in ("postular", "enviar", "confirmar postulacion", "finalizar postulacion", "aplicar"))

    def _resolve_answer(self, field: ObservedField, profile: UserProfile, saved_draft: dict[str, object]) -> str | None:
        saved = self._saved_answer(field.question, saved_draft)
        answer = saved or self.answer_memory.resolve(field.question, profile)
        if answer is None:
            return None
        answer = _clean(answer)
        if not answer:
            return None
        if field.field_type in {"select", "radio"} and field.options:
            normalized_answer = normalize_question(answer)
            best: tuple[float, str] | None = None
            for option in field.options:
                normalized_option = normalize_question(option)
                if not normalized_option:
                    continue
                if normalized_option == normalized_answer:
                    return option
                ratio = SequenceMatcher(None, normalized_option, normalized_answer).ratio()
                if normalized_answer in normalized_option or normalized_option in normalized_answer:
                    ratio = max(ratio, 0.95)
                if best is None or ratio > best[0]:
                    best = (ratio, option)
            return best[1] if best and best[0] >= 0.88 else None
        if field.field_type == "checkbox":
            normalized = normalize_question(answer)
            if normalized in {"si", "sí", "yes", "true", "acepto", "de acuerdo"}:
                return "true"
            if normalized in {"no", "false"}:
                return "false"
            return None
        return answer

    @staticmethod
    def _saved_answer(question: str, saved_draft: dict[str, object]) -> str | None:
        target = normalize_question(question)
        items = saved_draft.get("questions") or []
        if not isinstance(items, list):
            return None
        candidates: list[tuple[float, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            answer = _clean(item.get("suggested_answer"))
            candidate = normalize_question(_clean(item.get("question")))
            if not candidate or not answer:
                continue
            ratio = SequenceMatcher(None, candidate, target).ratio()
            if candidate == target:
                return answer
            candidates.append((ratio, answer))
        candidates.sort(reverse=True)
        return candidates[0][1] if candidates and candidates[0][0] >= 0.90 else None

    @staticmethod
    def _parse_fields(raw_fields: object) -> list[ObservedField]:
        if not isinstance(raw_fields, list):
            return []
        fields: list[ObservedField] = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_fields:
            if not isinstance(raw, dict):
                continue
            question = _clean(raw.get("question"))
            field_type = _clean(raw.get("type")).casefold() or "text"
            selector = _clean(raw.get("selector"))
            if not question or not selector:
                continue
            key = (normalize_question(question), field_type)
            if key in seen:
                continue
            seen.add(key)
            options = raw.get("options") or []
            if not isinstance(options, list):
                options = []
            fields.append(
                ObservedField(
                    question=question,
                    field_type=field_type,
                    selector=selector,
                    options=tuple(_clean(item) for item in options if _clean(item)),
                    required=bool(raw.get("required")),
                    current_value=_clean(raw.get("value")),
                )
            )
        return fields

    @staticmethod
    def _challenge_reason(body: str) -> str:
        text = body.casefold()
        markers = {
            "captcha": "CAPTCHA detectado; se detuvo la postulación.",
            "verifica que eres humano": "Verificación humana detectada; se detuvo la postulación.",
            "verify you are human": "Verificación humana detectada; se detuvo la postulación.",
            "access denied": "Acceso bloqueado por Computrabajo.",
            "acceso denegado": "Acceso bloqueado por Computrabajo.",
        }
        for marker, message in markers.items():
            if marker in text:
                return message
        return ""

    @staticmethod
    def _submission_confirmation(body: str) -> str:
        text = normalize_question(body)
        already = (
            "ya te postulaste",
            "ya has aplicado",
            "ya aplicaste",
            "ya estas postulado",
            "ya estás postulado",
        )
        success = (
            "postulacion enviada",
            "postulacion realizada",
            "candidatura enviada",
            "aplicacion enviada",
            "te has postulado correctamente",
            "te aplicaste correctamente",
            "postulacion exitosa",
        )
        if any(normalize_question(marker) in text for marker in already):
            return "already_applied"
        if any(normalize_question(marker) in text for marker in success):
            return "submitted"
        return ""

    @staticmethod
    def _choose_action(raw_actions: object) -> dict[str, object] | None:
        if not isinstance(raw_actions, list):
            return None
        priorities = {
            "continuar": 100,
            "siguiente": 98,
            "guardar y continuar": 97,
            "postularme": 95,
            "postular": 94,
            "aplicar": 93,
            "enviar postulacion": 92,
            "enviar candidatura": 91,
            "finalizar postulacion": 90,
            "confirmar postulacion": 89,
            "finalizar": 80,
        }
        ranked: list[tuple[int, int, dict[str, object]]] = []
        for index, raw in enumerate(raw_actions):
            if not isinstance(raw, dict):
                continue
            selector = _clean(raw.get("selector"))
            text = normalize_question(_clean(raw.get("text")))
            if not selector or not text or bool(raw.get("disabled")):
                continue
            score = priorities.get(text)
            if score is None:
                continue
            ranked.append((score, -index, raw))
        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        return ranked[0][2] if ranked else None

    async def _navigate(self, cdp: Any, url: str) -> None:
        if not is_safe_application_url(url):
            raise ValueError(f"Deterministic navigation refused URL: {url}")
        await cdp.cdp_client.send.Page.navigate(params={"url": url}, session_id=cdp.session_id)
        await self._wait_ready(cdp)

    async def _wait_ready(self, cdp: Any) -> None:
        for _ in range(40):
            await asyncio.sleep(0.25)
            state = await self._evaluate(cdp, "(() => ({ready: document.readyState, url: location.href}))()")
            if isinstance(state, dict) and state.get("ready") in {"interactive", "complete"}:
                await asyncio.sleep(0.35)
                return
        raise TimeoutError("Computrabajo no terminó de cargar el paso de postulación.")

    @staticmethod
    async def _evaluate(cdp: Any, expression: str) -> Any:
        result = await cdp.cdp_client.send.Runtime.evaluate(
            params={"expression": expression, "returnByValue": True, "awaitPromise": True},
            session_id=cdp.session_id,
        )
        return _runtime_value(result)

    async def _fill_fields(self, cdp: Any, values: list[tuple[ObservedField, str]]) -> bool:
        payload = [
            {"selector": field.selector, "type": field.field_type, "answer": answer}
            for field, answer in values
            if field.field_type != "password"
        ]
        script = f"""
(() => {{
  const items = {json.dumps(payload, ensure_ascii=False)};
  const norm = (v) => String(v || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  let ok = true;
  for (const item of items) {{
    const nodes = Array.from(document.querySelectorAll(item.selector));
    if (!nodes.length) {{ ok = false; continue; }}
    if (item.type === 'radio') {{
      const wanted = norm(item.answer);
      const target = nodes.find((el) => {{
        const label = el.id ? document.querySelector(`label[for="${{CSS.escape(el.id)}}"]`) : null;
        return norm(label?.innerText || el.value) === wanted || norm(label?.innerText || el.value).includes(wanted);
      }});
      if (!target) {{ ok = false; continue; }}
      target.click();
      target.dispatchEvent(new Event('change', {{ bubbles: true }}));
      continue;
    }}
    const el = nodes[0];
    if (item.type === 'checkbox') {{
      const checked = item.answer === 'true';
      if (el.checked !== checked) el.click();
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      continue;
    }}
    if (item.type === 'select') {{
      const wanted = norm(item.answer);
      const option = Array.from(el.options || []).find((opt) => norm(opt.textContent) === wanted || norm(opt.value) === wanted || norm(opt.textContent).includes(wanted));
      if (!option) {{ ok = false; continue; }}
      el.value = option.value;
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      continue;
    }}
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    if (descriptor?.set) descriptor.set.call(el, item.answer); else el.value = item.answer;
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
  }}
  return ok;
}})()
"""
        result = await self._evaluate(cdp, script)
        return result is True

    async def _click_action(self, cdp: Any, selector: str) -> bool:
        if not selector:
            return False
        script = f"""
(() => {{
  const el = document.querySelector({json.dumps(selector)});
  if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
  el.click();
  return true;
}})()
"""
        result = await self._evaluate(cdp, script)
        return result is True

    @staticmethod
    def _snapshot_script() -> str:
        return r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const selectorFor = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.getAttribute('data-testid')) return `${el.tagName.toLowerCase()}[data-testid="${CSS.escape(el.getAttribute('data-testid'))}"]`;
    if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]${el.type === 'radio' ? '[type="radio"]' : ''}`;
    const aria = el.getAttribute('aria-label');
    if (aria) return `${el.tagName.toLowerCase()}[aria-label="${CSS.escape(aria)}"]`;
    const parent = el.parentElement;
    if (!parent) return el.tagName.toLowerCase();
    const siblings = Array.from(parent.querySelectorAll(`:scope > ${el.tagName.toLowerCase()}`));
    return `${el.tagName.toLowerCase()}:nth-of-type(${Math.max(1, siblings.indexOf(el) + 1)})`;
  };
  const explicitLabel = (el) => {
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label) return clean(label.innerText);
    }
    const wrapping = el.closest('label');
    if (wrapping) return clean(wrapping.innerText);
    return '';
  };
  const groupQuestion = (el) => {
    const fieldset = el.closest('fieldset');
    const legend = fieldset?.querySelector('legend');
    if (legend) return clean(legend.innerText);
    const group = el.closest('[role="radiogroup"], [role="group"], .form-group, [class*="question"], [class*="field"]');
    const heading = group?.querySelector('label:not([for]), legend, h1, h2, h3, h4, [class*="label"], [class*="question"]');
    return clean(heading?.innerText || '');
  };
  const fields = [];
  const seenRadio = new Set();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    if (!visible(el) || el.disabled) continue;
    const rawType = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : (el.type || 'text').toLowerCase();
    if (rawType === 'radio') {
      const group = el.name || selectorFor(el);
      if (seenRadio.has(group)) continue;
      seenRadio.add(group);
      const nodes = el.name ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)) : [el];
      const options = nodes.map((node) => clean(explicitLabel(node) || node.value)).filter(Boolean);
      fields.push({
        question: clean(groupQuestion(el) || el.getAttribute('aria-label') || explicitLabel(el) || el.name || 'Opción'),
        type: 'radio', selector: selectorFor(el), options,
        required: nodes.some((node) => node.required),
        value: clean(nodes.find((node) => node.checked)?.value || '')
      });
      continue;
    }
    const question = clean(explicitLabel(el) || el.getAttribute('aria-label') || el.placeholder || groupQuestion(el) || el.name || el.id);
    if (!question) continue;
    const options = rawType === 'select' ? Array.from(el.options || []).map((opt) => clean(opt.textContent)).filter(Boolean) : [];
    const value = rawType === 'checkbox' ? (el.checked ? 'true' : '') : clean(el.value);
    fields.push({ question, type: rawType, selector: selectorFor(el), options, required: !!el.required || el.getAttribute('aria-required') === 'true', value });
  }
  const actions = [];
  for (const el of document.querySelectorAll('button, input[type="submit"], a')) {
    if (!visible(el)) continue;
    const text = clean(el.innerText || el.value || el.getAttribute('aria-label'));
    if (!text) continue;
    actions.push({
      text,
      selector: selectorFor(el),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      href: el.href || '',
      in_form: !!el.closest('form')
    });
  }
  return {
    url: location.href,
    title: document.title,
    body: clean(document.body?.innerText || '').slice(0, 14000),
    fields,
    actions: actions.slice(0, 80)
  };
})()
"""
