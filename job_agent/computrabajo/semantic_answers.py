from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from job_agent.cv_profile import SKILL_ALIASES
from job_agent.profile import UserProfile
from job_agent.storage import DEFAULT_DB_PATH

_STOPWORDS = {"a","al","como","con","cual","cuando","de","del","donde","el","en","es","esta","has","la","las","los","para","por","que","si","sin","su","te","tienes","tu","un","una","y","ya"}
_YES = {"si", "sí", "yes", "true", "acepto", "de acuerdo", "claro", "correcto"}
_NO = {"no", "false"}

_INTENT_PHRASES = {
    "city": (("ciudad de residencia",12),("lugar de residencia",12),("ciudad actual",11),("donde resides",11),("donde vives",11),("residencia",5),("ciudad",5)),
    "residence_yes_no": (("resides en",12),("vives en",12),("domiciliado en",12),("radicado en",11)),
    "english_level": (("nivel de ingles",12),("english level",12),("dominio de ingles",10),("manejo de ingles",9),("ingles",5)),
    "salary": (("aspiracion salarial",12),("pretension salarial",12),("salario esperado",12),("expectativa salarial",12),("salario",5)),
    "availability": (("disponibilidad para iniciar",12),("cuando puedes empezar",12),("fecha de inicio",11),("disponibilidad inmediata",10),("disponibilidad",5)),
    "total_experience_years": (("anos de experiencia laboral",12),("anos de experiencia profesional",12),("cuantos anos de experiencia tienes",10),("experiencia total",10),("anos de experiencia",7)),
    "skill_experience_years": (("anos de experiencia con",12),("anos de experiencia en",11),("cuanto tiempo de experiencia",10),("cuantos anos manejando",10)),
    "skill_yes_no": (("tienes experiencia con",12),("tienes experiencia en",12),("has trabajado con",12),("manejas",8),("conoces",7),("conocimiento en",8),("experiencia con",7)),
    "work_mode": (("modalidad de trabajo",12),("modalidad preferida",11),("trabajo remoto",8),("trabajo hibrido",8),("trabajo presencial",8),("remoto",5),("hibrido",5),("presencial",5)),
    "contract_type": (("tipo de contrato",12),("modalidad contractual",10),("contrato preferido",11)),
    "professional_summary": (("hablanos de tu experiencia",12),("cuentanos sobre tu experiencia",12),("resume tu experiencia",12),("perfil profesional",9),("describe tu experiencia",11)),
    "motivation": (("por que quieres trabajar",12),("por que te interesa",12),("motivacion para",10),("por que quieres postularte",12),("por que aplicar",10)),
    "strengths": (("por que deberiamos contratarte",12),("principales fortalezas",11),("que puedes aportar",10),("fortalezas profesionales",11)),
}
_MODE_ALIASES = {
    "remote": ("remoto","remote","teletrabajo","desde casa","home office"),
    "hybrid": ("hibrido","hybrid","mixto"),
    "onsite": ("presencial","onsite","en oficina","oficina"),
}
_ENGLISH_BUCKETS = {
    "a1":"basic","a2":"basic","b1":"intermediate","b2":"intermediate","c1":"advanced","c2":"advanced",
    "basico":"basic","basic":"basic","elemental":"basic","intermedio":"intermediate","intermediate":"intermediate",
    "avanzado":"advanced","advanced":"advanced","fluido":"advanced","fluent":"advanced","nativo":"native","native":"native",
}

@dataclass(frozen=True)
class SemanticMatch:
    intent: str
    confidence: int
    skill: str = ""
    mode: str = ""
    location: str = ""

@dataclass(frozen=True)
class LocalSemanticAnswer:
    answer: str
    confidence: int
    source: str
    intent: str
    reason: str

def normalize_semantic(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9+#./-]+", " ", text)
    return " ".join(text.split())

def _plain(value: str) -> str:
    return normalize_semantic(value).replace("/", " ").replace("-", " ")

def _tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#.]+", _plain(value)) if len(t) > 1 and t not in _STOPWORDS}

def _skill_in_text(text: str) -> str:
    normalized = f" {_plain(text)} "
    ranked = []
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in (canonical, *aliases):
            needle = _plain(alias).strip()
            if needle and f" {needle} " in normalized:
                ranked.append((len(needle), canonical))
    ranked.sort(reverse=True)
    return ranked[0][1] if ranked else ""

def _mode_in_text(text: str) -> str:
    normalized = _plain(text)
    for mode, aliases in _MODE_ALIASES.items():
        if any(_plain(alias) in normalized for alias in aliases):
            return mode
    return ""

def classify_question(question: str, *, known_locations: Iterable[str] = ()) -> SemanticMatch:
    normalized = _plain(question)
    if not normalized:
        return SemanticMatch("unknown", 0)
    skill = _skill_in_text(normalized)
    mode = _mode_in_text(normalized)
    location = ""
    for candidate in known_locations:
        clean = _plain(candidate)
        if clean and clean in normalized:
            location = str(candidate)
            break
    scores = {}
    for intent, phrases in _INTENT_PHRASES.items():
        score = sum(weight for phrase, weight in phrases if _plain(phrase) in normalized)
        if score:
            scores[intent] = score
    if skill and "anos" in normalized and "experiencia" in normalized:
        scores["skill_experience_years"] = max(scores.get("skill_experience_years",0),20)
        scores["total_experience_years"] = min(scores.get("total_experience_years",0),5)
    elif "anos" in normalized and "experiencia" in normalized:
        scores["total_experience_years"] = max(scores.get("total_experience_years",0),14)
    if location and any(term in normalized for term in ("resides","vives","domiciliado","radicado")):
        scores["residence_yes_no"] = max(scores.get("residence_yes_no",0),20)
        scores["city"] = min(scores.get("city",0),4)
    if not scores:
        return SemanticMatch("unknown",0,skill=skill,mode=mode,location=location)
    intent, score = max(scores.items(), key=lambda x:x[1])
    return SemanticMatch(intent,max(70,min(99,72+score)),skill=skill,mode=mode,location=location)

def semantic_similarity(left: str, right: str) -> float:
    a,b = normalize_semantic(left), normalize_semantic(right)
    if not a or not b: return 0.0
    if a == b: return 1.0
    ma,mb = classify_question(a), classify_question(b)
    if ma.intent != "unknown" and mb.intent != "unknown":
        if ma.intent != mb.intent: return 0.0
        if ma.skill and mb.skill and ma.skill != mb.skill: return 0.0
        if ma.mode and mb.mode and ma.mode != mb.mode: return 0.0
    seq = SequenceMatcher(None,a,b).ratio()
    ta,tb = _tokens(a),_tokens(b)
    union = ta|tb
    j = len(ta&tb)/len(union) if union else 0.0
    cont = min(len(ta&tb)/max(1,len(ta)), len(ta&tb)/max(1,len(tb)))
    score = max(seq,0.55*j+0.45*cont)
    if ma.intent != "unknown" and ma.intent == mb.intent:
        score = max(score,0.88+min(j,0.10))
    return min(score,1.0)

def _parse_number(value: str) -> float | None:
    m = re.search(r"\b(\d+(?:[.,]\d+)?)\b", normalize_semantic(value))
    if not m: return None
    try: return float(m.group(1).replace(",","."))
    except ValueError: return None

def _parse_money(value: str) -> int | None:
    digits = re.findall(r"\d+", str(value or ""))
    if not digits: return None
    number = int("".join(digits))
    normalized = _plain(value)
    if "millon" in normalized and number < 1000: number *= 1_000_000
    elif "mil" in normalized and number < 100_000: number *= 1000
    return number

def _range_contains(option: str, value: float) -> bool:
    text = _plain(option)
    nums = [float(x.replace(",",".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)]
    if not nums: return False
    if any(m in text for m in ("mas de","mayor a","superior a","o mas")): return value >= nums[0]
    if any(m in text for m in ("menos de","menor a","inferior a","hasta")) and len(nums)==1: return value <= nums[0]
    if len(nums)>=2:
        low,high=min(nums[0],nums[1]),max(nums[0],nums[1]); return low <= value <= high
    return abs(value-nums[0]) < 1e-9

def _money_range_contains(option: str, value: int) -> bool:
    normalized = _plain(option)
    nums = [_parse_money(x) for x in re.findall(r"\d[\d.,]*", str(option or ""))]
    nums = [x for x in nums if x is not None]
    if "millon" in normalized: nums = [x*1_000_000 if x < 1000 else x for x in nums]
    if not nums: return False
    if any(m in normalized for m in ("mas de","mayor a","superior a","o mas")): return value >= nums[0]
    if any(m in normalized for m in ("menos de","menor a","inferior a","hasta")) and len(nums)==1: return value <= nums[0]
    if len(nums)>=2:
        low,high=min(nums[0],nums[1]),max(nums[0],nums[1]); return low <= value <= high
    return value == nums[0]

def _canonical_yes_no(answer: str) -> str:
    normalized = normalize_semantic(answer)
    yes = {normalize_semantic(x) for x in _YES}; no={normalize_semantic(x) for x in _NO}
    if normalized in yes: return "yes"
    if normalized in no: return "no"
    return ""

def _english_bucket(value: str) -> str:
    normalized = _plain(value)
    for token,bucket in _ENGLISH_BUCKETS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", normalized):
            return bucket
    return ""

class LocalSemanticAnswerEngine:
    """Zero-API semantic resolver bound to explicit profile/CV evidence."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)

    def _cv_text(self) -> str:
        if not self.path.exists(): return ""
        try:
            with sqlite3.connect(self.path) as c:
                exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cv_profile'").fetchone()
                if not exists: return ""
                row=c.execute("SELECT text_content FROM cv_profile WHERE id=1").fetchone()
        except sqlite3.Error:
            return ""
        return str(row[0] or "") if row else ""

    def _skill_is_verified(self, skill: str, profile: UserProfile) -> bool:
        if not skill: return False
        if normalize_semantic(skill) in {normalize_semantic(s) for s in profile.skills}: return True
        cv=normalize_semantic(self._cv_text())
        for alias in (skill,*SKILL_ALIASES.get(skill,())):
            needle=normalize_semantic(alias)
            if needle and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",cv):
                return True
        return False

    @staticmethod
    def _format_years(years: float) -> str:
        return str(int(years)) if float(years).is_integer() else f"{years:.1f}".rstrip("0").rstrip(".")

    def resolve_profile(self, question: str, profile: UserProfile, *, field_type: str="text", options: Iterable[str]=(), job: dict[str, object] | None=None) -> LocalSemanticAnswer | None:
        locations=[profile.city,*profile.preferred_locations]
        match=classify_question(question,known_locations=(x for x in locations if x))
        raw=None; source="profile"; reason=""
        if match.intent=="city" and profile.city:
            raw=profile.city; reason="Intención de ciudad/residencia resuelta desde Mi perfil."
        elif match.intent=="residence_yes_no" and profile.city and match.location:
            raw="Sí" if normalize_semantic(profile.city)==normalize_semantic(match.location) else "No"; reason="Ciudad del perfil comparada con la ubicación consultada."
        elif match.intent=="english_level" and profile.english_level:
            raw=profile.english_level; reason="Nivel de inglés explícito de Mi perfil."
        elif match.intent=="salary" and profile.salary_expectation:
            raw=profile.salary_expectation; reason="Aspiración salarial explícita de Mi perfil."
        elif match.intent=="availability" and profile.availability:
            raw=profile.availability; reason="Disponibilidad explícita de Mi perfil."
        elif match.intent=="total_experience_years" and not match.skill and profile.years_experience>0:
            raw=self._format_years(profile.years_experience); reason="Años de experiencia total explícitos del perfil."
        elif match.intent=="skill_yes_no" and match.skill and self._skill_is_verified(match.skill,profile):
            raw="Sí"; source="verified_skill"; reason=f"{match.skill} está verificada en el perfil/CV."
        elif match.intent=="work_mode" and match.mode:
            pref={normalize_semantic(x) for x in profile.preferred_work_modes}
            allowed=(match.mode=="remote" and (profile.remote_ok or any("remot" in x for x in pref))) or (match.mode=="hybrid" and any("hibrid" in x or "hybrid" in x for x in pref)) or (match.mode=="onsite" and any("presencial" in x or "onsite" in x for x in pref))
            if allowed:
                raw="Sí" if field_type in {"checkbox","radio"} or self._looks_yes_no(options) else {"remote":"Remoto","hybrid":"Híbrido","onsite":"Presencial"}[match.mode]
                reason="Modalidad explícitamente permitida en las preferencias."
        elif match.intent=="work_mode" and not match.mode and profile.preferred_work_modes:
            raw=profile.preferred_work_modes[0]; reason="Primera modalidad preferida configurada."
        elif match.intent=="contract_type" and profile.preferred_contract_types:
            raw=profile.preferred_contract_types[0]; reason="Tipo de contrato preferido configurado."
        elif match.intent=="professional_summary" and profile.professional_summary:
            raw=profile.professional_summary[:1800].strip(); source="professional_summary"; reason="Resumen profesional escrito por el usuario."
        elif match.intent in {"motivation","strengths"}:
            raw=self._compose_safe_text(match.intent,profile,job or {})
            if raw: source="local_template"; reason="Texto compuesto solo con cargo, empresa y skills verificadas."
        if not raw: return None
        adapted=self.adapt_to_options(raw,options=tuple(options),intent=match.intent,match=match)
        if adapted is None: return None
        return LocalSemanticAnswer(adapted,max(match.confidence,90 if source=="local_template" else 94),source,match.intent,reason)

    @staticmethod
    def _looks_yes_no(options: Iterable[str]) -> bool:
        norm={normalize_semantic(x) for x in options if normalize_semantic(x)}
        return bool(norm & {normalize_semantic(x) for x in _YES}) and bool(norm & {normalize_semantic(x) for x in _NO})

    def adapt_to_options(self, answer: str, *, options: tuple[str,...], intent: str="unknown", match: SemanticMatch|None=None) -> str|None:
        clean=" ".join(str(answer or "").strip().split())
        if not clean: return None
        if not options: return clean
        na=normalize_semantic(clean); opts=[(normalize_semantic(o),o) for o in options if normalize_semantic(o)]
        for n,o in opts:
            if n==na: return o
        yn=_canonical_yes_no(clean)
        if yn:
            aliases=_YES if yn=="yes" else _NO; aset={normalize_semantic(x) for x in aliases}
            for n,o in opts:
                if n in aset: return o
        if intent=="english_level":
            bucket=_english_bucket(clean)
            cefr=re.search(r"\b(a1|a2|b1|b2|c1|c2)\b",na)
            if cefr:
                for n,o in opts:
                    if re.search(rf"\b{re.escape(cefr.group(1))}\b",n): return o
            if bucket:
                for n,o in opts:
                    if _english_bucket(n)==bucket: return o
        if intent in {"total_experience_years","skill_experience_years"}:
            years=_parse_number(clean)
            if years is not None:
                for _,o in opts:
                    if _range_contains(o,years): return o
        if intent=="salary":
            money=_parse_money(clean)
            if money is not None:
                for _,o in opts:
                    if _money_range_contains(o,money): return o
        if intent=="work_mode":
            mode=match.mode if match else _mode_in_text(clean)
            if not mode: mode=_mode_in_text(clean)
            if mode:
                aliases={normalize_semantic(x) for x in _MODE_ALIASES[mode]}
                for n,o in opts:
                    if n in aliases or any(a in n for a in aliases): return o
        best=None
        for n,o in opts:
            ratio=SequenceMatcher(None,n,na).ratio()
            if na in n or n in na: ratio=max(ratio,.95)
            if best is None or ratio>best[0]: best=(ratio,o)
        return best[1] if best and best[0]>=.88 else None

    @staticmethod
    def _compose_safe_text(intent: str, profile: UserProfile, job: dict[str, object]) -> str:
        title=" ".join(str(job.get("title") or "").split())
        company=" ".join(str(job.get("company") or "").split())
        description=normalize_semantic(str(job.get("description") or ""))
        verified=[s for s in profile.skills if normalize_semantic(s) and normalize_semantic(s) in description] or profile.skills[:5]
        skills=", ".join(verified[:5])
        role=title or (profile.target_roles[0] if profile.target_roles else "esta posición")
        company_fragment=f" en {company}" if company else ""
        if intent=="motivation":
            parts=[f"Me interesa la oportunidad de {role}{company_fragment} porque está alineada con mi perfil profesional."]
            if skills: parts.append(f"Puedo aportar experiencia y conocimientos en {skills}.")
            return " ".join(parts)[:1200]
        if intent=="strengths":
            if skills:
                return (f"Mis principales fortalezas para {role} son mis conocimientos verificados en {skills}, junto con mi enfoque en construir soluciones claras, mantenibles y orientadas a resultados.")[:1200]
            if profile.professional_summary: return profile.professional_summary[:1200].strip()
        return ""
