"""Stage 01 & Stage 02: Resume Skill Extraction, Input Excel Career Pages & Persistent Agent Memory State.

Implements the first two columns of the Job Search & Auto-Apply Agentic Architecture:
- 01 • INPUTS & EXTRACTION:
    * Candidate Resume Parser (PDF / DOCX / Plain Text) -> structured JSON Profile Payload
    * Input Excel Loader (`Company name.xlsx`) -> Target Company Names & Direct Career Portal URLs
- 02 • AGENT MEMORY STATE:
    * Persisted context (`target_roles[]`, `resume_skills[]`, `search_keywords[]`,
      `career_pages[]`, `freshness_window_hours = 48`, `match_threshold_pct = 80.0`)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

import openpyxl

from config import (
    AGENT_MEMORY_STATE_PATH,
    AIML_RESUME_DOCX_PATH,
    BASE_DIR,
    CANDIDATE_PROFILE,
    COMPANY_CHECK_SHEET,
    DA_RESUME_DOCX_PATH,
    MATCH_THRESHOLD_PERCENT,
    MAX_POSTED_AGE_HOURS,
    MIS_RESUME_DOCX_PATH,
    OFFICIAL_COMPANY_PORTALS,
    RESUME_DOCX_PATH,
    RESUME_PDF_PATH,
)
from matcher import RESUME_SKILL_PATTERNS
from resume_builder import ensure_company_check_sheet


ROLE_EXTRACTION_PATTERNS: List[tuple[str, str]] = [
    ("Data Analyst", r"\bdata\s+analyst\b"),
    ("MIS Executive", r"\bmis\s+(?:executive|analyst|reporting)\b|\bmanagement\s+information\s+systems\b"),
    ("Power BI Developer", r"\bpower\s*bi\b"),
    ("AI/ML Engineer", r"\bai/?ml\s+engineer\b|\bmachine\s+learning\b|\bgenerative\s+ai\b"),
    ("Reporting Analyst", r"\breporting\s+analyst\b|\bkpi\s+reporting\b|\bclaims\s+reporting\b"),
    ("Data Engineer", r"\bdata\s+engineer\b|\betl\b|\bdatabricks\b|\bpyspark\b"),
    ("Insights Analyst", r"\binsights\s+analyst\b|\bbusiness\s+analyst\b"),
    ("Operations Analyst", r"\boperations\s+analyst\b"),
]

PRIMARY_SKILL_NAMES = {
    "Python",
    "Pandas",
    "NumPy",
    "SQL",
    "SQL Server / SSMS / SSIS",
    "Power BI",
    "DAX",
    "Power Query",
    "Advanced Excel",
    "MIS & KPI Reporting",
    "ETL Pipelines",
    "Azure Databricks",
    "PySpark",
    "Machine Learning",
    "Generative AI & LLMs",
    "Agentic Workflows & Automation",
}


def _ist_timestamp() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")


def _extract_docx_text(path: Path) -> str:
    """Extract text from a .docx file via python-docx with XML fallback."""
    if not path.exists():
        return ""
    try:
        import docx

        doc = docx.Document(str(path))
        parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        for tbl in doc.tables:
            for row in tbl.rows:
                row_txt = " | ".join(c.text.strip() for c in row.cells if c.text and c.text.strip())
                if row_txt:
                    parts.append(row_txt)
        if parts:
            return "\n".join(parts)
    except Exception:
        pass

    try:
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
        return " ".join(texts)
    except Exception:
        return ""


def _extract_pdf_or_text(path: Path) -> str:
    """Extract text from plain text or lightweight PDF stream strings."""
    if not path.exists():
        return ""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    if suffix == ".docx":
        return _extract_docx_text(path)
    if suffix == ".pdf":
        try:
            raw = path.read_bytes()
            ascii_chunks = re.findall(rb"[A-Za-z0-9 ,.;:/()+\-_]{4,}", raw)
            return " ".join(chunk.decode("latin-1", errors="ignore") for chunk in ascii_chunks)
        except Exception:
            return ""
    return ""


def parse_resume_to_profile_payload(resume_paths: Optional[List[Path]] = None) -> Dict[str, Any]:
    """Stage 01 — Parse Candidate Resume(s) (PDF / DOCX / Plain Text) into JSON Profile Payload."""
    default_candidates = [
        DA_RESUME_DOCX_PATH,
        AIML_RESUME_DOCX_PATH,
        MIS_RESUME_DOCX_PATH,
        RESUME_DOCX_PATH,
        RESUME_PDF_PATH,
    ]
    resumes_dir = BASE_DIR / "resumes"
    if resumes_dir.exists():
        for item in sorted(resumes_dir.iterdir()):
            if item.suffix.lower() in (".docx", ".pdf", ".txt"):
                default_candidates.append(item)

    paths_to_scan = resume_paths if resume_paths is not None else default_candidates
    parsed_texts: List[str] = []
    sources_used: List[str] = []

    for p in paths_to_scan:
        if p and p.exists():
            txt = _extract_pdf_or_text(p)
            if txt.strip():
                parsed_texts.append(txt)
                sources_used.append(p.name)

    # Always merge canonical profile text so no core skill is missed if only one role variant is present
    fallback_text = str(CANDIDATE_PROFILE.get("resume_text") or "")
    combined_text = "\n".join(parsed_texts + [fallback_text]).strip()
    lower_blob = combined_text.lower()

    extracted_skills: List[str] = []
    for canonical_name, regex_list in RESUME_SKILL_PATTERNS:
        if any(re.search(pat, lower_blob) for pat in regex_list):
            extracted_skills.append(canonical_name)

    primary_skills = [s for s in extracted_skills if s in PRIMARY_SKILL_NAMES]
    secondary_skills = [s for s in extracted_skills if s not in PRIMARY_SKILL_NAMES]

    extracted_roles: List[str] = []
    for role_label, pat in ROLE_EXTRACTION_PATTERNS:
        if re.search(pat, lower_blob):
            extracted_roles.append(role_label)
    for cfg_role in CANDIDATE_PROFILE.get("target_roles", [])[:8]:
        if cfg_role not in extracted_roles:
            extracted_roles.append(cfg_role)

    # Build role + skill search keyword permutations for sequential portal queries
    top_skill_tags = ["Python", "SQL", "Power BI", "ETL", "MIS"]
    search_keywords: List[str] = []
    for r in extracted_roles[:6]:
        search_keywords.append(r)
    for combo in [
        "Data Analyst Python SQL Power BI",
        "MIS Executive Advanced Excel Power BI",
        "Power BI Developer DAX SQL",
        "AI ML Engineer Python Machine Learning",
        "Reporting Analyst Power BI SQL",
        "Data Engineer Azure Databricks PySpark",
    ]:
        if combo not in search_keywords:
            search_keywords.append(combo)

    exp_match = re.search(r"(\d+(?:\.\d+)?)\+?\s*years?\s+of\s+experience", lower_blob)
    exp_years = (
        float(exp_match.group(1))
        if exp_match
        else float(CANDIDATE_PROFILE.get("total_experience_years", 4.5))
    )

    return {
        "candidate_name": CANDIDATE_PROFILE.get("full_name", "Adithya Krishna"),
        "email": CANDIDATE_PROFILE.get("email", ""),
        "seniority_years": exp_years,
        "resume_sources_parsed": sources_used or ["CANDIDATE_PROFILE.resume_text"],
        "primary_skills": primary_skills,
        "secondary_skills": secondary_skills,
        "resume_skills": primary_skills + secondary_skills,
        "target_roles": extracted_roles,
        "search_keywords": search_keywords,
        "domain_skill_tags": top_skill_tags,
    }


def load_career_pages_from_excel(excel_path: Path = COMPANY_CHECK_SHEET) -> List[Dict[str, str]]:
    """Stage 01 — Read Target Company Names & Direct Career Portal URLs from `Company name.xlsx`."""
    ensure_company_check_sheet()
    entries: List[Dict[str, str]] = []
    seen_companies: set[str] = set()

    if excel_path.exists():
        try:
            wb = openpyxl.load_workbook(excel_path, data_only=True)
            ws = wb.active
            for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if not row or not row[0]:
                    continue
                comp = str(row[0]).strip()
                if row_idx == 1 and comp.lower() in ("company name", "company", "companies"):
                    continue
                if not comp:
                    continue
                norm_key = comp.lower()
                if norm_key in seen_companies:
                    continue
                seen_companies.add(norm_key)

                sheet_url = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                role_hint = str(row[2]).strip() if len(row) > 2 and row[2] else ""

                portal_cfg = OFFICIAL_COMPANY_PORTALS.get(norm_key, {})
                if not portal_cfg:
                    for k, v in OFFICIAL_COMPANY_PORTALS.items():
                        if k in norm_key or norm_key in k:
                            portal_cfg = v
                            break

                careers_url = (
                    sheet_url
                    if sheet_url.startswith("http")
                    else portal_cfg.get(
                        "careers_url",
                        f"https://www.google.com/search?q={urllib.parse.quote(comp + ' careers Data Analyst India')}",
                    )
                )
                entries.append(
                    {
                        "company": portal_cfg.get("name", comp),
                        "raw_company": comp,
                        "careers_url": careers_url,
                        "target_roles": role_hint or "Data Analyst / AI & ML Engineer / MIS / Gen AI / Power BI",
                    }
                )
            wb.close()
        except Exception:
            entries = []

    if not entries:
        for v in OFFICIAL_COMPANY_PORTALS.values():
            entries.append(
                {
                    "company": v["name"],
                    "raw_company": v["name"],
                    "careers_url": v["careers_url"],
                    "target_roles": "Data Analyst / MIS Executive / Power BI",
                }
            )
    return entries


@dataclass
class AgentMemoryState:
    """Stage 02 — Shared Context / Persistent Agent Memory across all search & evaluation steps."""

    candidate_name: str
    seniority_years: float
    target_roles: List[str] = field(default_factory=list)
    primary_skills: List[str] = field(default_factory=list)
    secondary_skills: List[str] = field(default_factory=list)
    resume_skills: List[str] = field(default_factory=list)
    search_keywords: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=lambda: ["Hyderabad", "Bengaluru", "Gurugram", "Chennai"])
    career_pages: List[Dict[str, str]] = field(default_factory=list)
    resume_sources_parsed: List[str] = field(default_factory=list)
    freshness_window_hours: int = MAX_POSTED_AGE_HOURS
    match_threshold_pct: float = MATCH_THRESHOLD_PERCENT
    updated_at_ist: str = field(default_factory=_ist_timestamp)

    @property
    def target_company_names(self) -> List[str]:
        return [item["company"] for item in self.career_pages if item.get("company")]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: Path = AGENT_MEMORY_STATE_PATH) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def build_and_persist(
        cls,
        *,
        resume_paths: Optional[List[Path]] = None,
        excel_path: Path = COMPANY_CHECK_SHEET,
        state_path: Path = AGENT_MEMORY_STATE_PATH,
        locations: Optional[List[str]] = None,
    ) -> "AgentMemoryState":
        payload = parse_resume_to_profile_payload(resume_paths=resume_paths)
        career_pages = load_career_pages_from_excel(excel_path=excel_path)
        state = cls(
            candidate_name=payload["candidate_name"],
            seniority_years=payload["seniority_years"],
            target_roles=payload["target_roles"],
            primary_skills=payload["primary_skills"],
            secondary_skills=payload["secondary_skills"],
            resume_skills=payload["resume_skills"],
            search_keywords=payload["search_keywords"],
            locations=locations or ["Hyderabad", "Bengaluru", "Gurugram", "Chennai"],
            career_pages=career_pages,
            resume_sources_parsed=payload["resume_sources_parsed"],
            freshness_window_hours=MAX_POSTED_AGE_HOURS,
            match_threshold_pct=MATCH_THRESHOLD_PERCENT,
        )
        state.save(state_path)
        return state
