"""Multi-resume parser and >=80% JD skill-match engine powered by Google Drive resumes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from .filters import parse_experience_bounds
from .models import JobListing

# Comprehensive skill taxonomy across Data Analytics, BI/ETL, ML, and Gen AI.
SKILL_TAXONOMY: dict[str, list[str]] = {
    # BI & Analytics
    "Power BI": [r"\bpower\s*bi\b", r"\bpowerbi\b", r"\bpower bi service\b"],
    "DAX": [r"\bdax\b"],
    "Power Query": [r"\bpower\s*query\b", r"\bm\s+language\b"],
    "Power BI Fabric": [r"\bmicrosoft fabric\b", r"\bpower bi fabric\b", r"\bfabric\b"],
    "Row-Level Security (RLS)": [r"\brow[- ]level security\b", r"\brls\b"],
    "Excel": [r"\bexcel\b", r"\bpivot\s*table", r"\bvlookup\b", r"\bxlookup\b", r"\bopenpyxl\b"],
    "Tableau": [r"\btableau\b"],
    "Looker": [r"\blooker\b"],
    "Qlik": [r"\bqlik\b", r"\bqliksense\b"],
    "KPI / Dashboarding": [r"\bkpi\b", r"\bdashboard", r"\bdata visualization\b", r"\bdata storytelling\b"],
    "Power Automate": [r"\bpower\s*automate\b"],
    # SQL, Databases & Data Engineering / ETL
    "SQL": [r"\bsql\b", r"\bt-sql\b", r"\bpl/sql\b", r"\bmysql\b", r"\bpostgresql\b", r"\bpostgres\b"],
    "SQL Server / SSMS": [r"\bsql server\b", r"\bssms\b", r"\bmssql\b"],
    "SSIS": [r"\bssis\b"],
    "ETL / Data Pipelines": [r"\betl\b", r"\bdata pipeline", r"\bdata ingestion\b", r"\bdata integration\b", r"\bmedallion\b"],
    "Data Modeling": [r"\bdata model", r"\bstar schema\b", r"\bdata warehouse\b", r"\bdata warehousing\b"],
    "Data Quality / Validation": [r"\bdata cleansing\b", r"\bdata validation\b", r"\bdata quality\b", r"\broot[- ]cause\b"],
    "Azure": [r"\bazure\b"],
    "Azure Databricks": [r"\bdatabricks\b", r"\bazure databricks\b"],
    "PySpark / Spark": [r"\bpyspark\b", r"\bapache spark\b", r"\bspark\b"],
    "Snowflake": [r"\bsnowflake\b"],
    "AWS": [r"\baws\b", r"\bredshift\b", r"\bs3\b"],
    "GCP / BigQuery": [r"\bgcp\b", r"\bbigquery\b", r"\bgoogle cloud\b"],
    "Airflow / dbt": [r"\bairflow\b", r"\bdbt\b"],
    # Python & Machine Learning
    "Python": [r"\bpython\b"],
    "Pandas / NumPy": [r"\bpandas\b", r"\bnumpy\b"],
    "Data Viz (Matplotlib/Seaborn)": [r"\bmatplotlib\b", r"\bseaborn\b"],
    "EDA / Statistics": [r"\beda\b", r"\bexploratory data\b", r"\bstatistics\b", r"\bstatistical\b", r"\ba/b testing\b"],
    "Machine Learning": [r"\bmachine learning\b", r"\bml models?\b", r"\bxgboost\b", r"\brandom forest\b", r"\bscikit-learn\b", r"\bpredictive model"],
    "Deep Learning (PyTorch/TF)": [r"\bpytorch\b", r"\btensorflow\b", r"\bdeep learning\b", r"\bneural network"],
    "MLOps": [r"\bmlops\b", r"\bmlflow\b", r"\bkubeflow\b", r"\bsagemaker\b"],
    # Gen AI & Agentic AI
    "Generative AI / LLMs": [r"\bgenerative ai\b", r"\bgen\s*ai\b", r"\bgenai\b", r"\bllm\b", r"\blarge language model"],
    "Agentic AI / Workflows": [r"\bagentic\b", r"\bai agent", r"\bworkflow automation\b", r"\blangchain\b", r"\blanggraph\b"],
    "MCP / AI Connectors": [r"\bmcp\b", r"\bmodel context protocol\b"],
    "RAG / Vector DB": [r"\brag\b", r"\bretrieval[- ]augmented\b", r"\bvector database\b", r"\bpinecone\b", r"\bchromadb\b"],
    # Other tools sometimes requested in JDs (to detect real gaps honestly)
    "R": [r"\br programming\b", r"\brstudio\b", r"\bpython/r\b", r"\bpython or r\b"],
    "Java / Scala": [r"\bjava\b", r"\bscala\b"],
    "Kubernetes / Docker": [r"\bkubernetes\b", r"\bdocker\b"],
    "Salesforce / CRM": [r"\bsalesforce\b"],
    "SAP / ERP": [r"\bsap\b"],
}

TRACK_TITLE_SIGNALS: dict[str, tuple[str, ...]] = {
    "Data Analyst / Power BI & ETL": (
        "data analyst",
        "power bi",
        "bi analyst",
        "business intelligence",
        "business analyst",
        "insights analyst",
        "reporting analyst",
        "mis",
        "etl",
        "data engineer",
        "analytics analyst",
    ),
    "Gen AI & Agentic Analytics": (
        "gen ai",
        "genai",
        "generative ai",
        "agentic",
        "ai analyst",
        "ai engineer",
        "llm",
        "automation",
        "power bi",
        "data analyst",
    ),
    "ML & Data Science": (
        "machine learning",
        "ml engineer",
        "data scientist",
        "data science",
        "predictive",
        "ai/ml",
        "analytics",
        "data analyst",
    ),
}


@dataclass
class ResumeProfile:
    """Extracted skill profile for one resume file from Google Drive."""

    profile_id: str
    track: str
    name: str
    drive_file_id: str
    drive_url: str
    local_path: str
    years_experience: float
    skills: list[str] = field(default_factory=list)
    summary_highlights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResumeMatchResult:
    """Evaluation of a single job against the candidate's best-fit resume."""

    job_id: str
    fingerprint: str
    source: str
    title: str
    company: str
    location: str
    experience: str
    posted_date: str
    url: str
    resume_match_pct: int
    jd_skill_coverage_pct: int
    experience_fit: str  # "strong" | "stretch" | "mismatch"
    best_resume_id: str
    best_resume_track: str
    best_resume_name: str
    best_resume_local_path: str
    best_resume_drive_url: str
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    jd_skills_detected: list[str] = field(default_factory=list)
    tailored_pitch: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_text_from_docx(docx_path: Path) -> str:
    """Read plain text from a .docx file using Python standard library only."""
    with zipfile.ZipFile(docx_path) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines: list[str] = []
    for para in root.findall(".//w:p", ns):
        txt = "".join(node.text or "" for node in para.findall(".//w:t", ns)).strip()
        if txt:
            lines.append(txt)
    return "\n".join(lines)


def extract_skills(text: str) -> list[str]:
    """Return sorted canonical skills present in `text`."""
    found: list[str] = []
    for skill_name, patterns in SKILL_TAXONOMY.items():
        if any(re.search(pat, text, re.IGNORECASE) for pat in patterns):
            found.append(skill_name)
    return found


def build_profiles_from_drive_resumes(resumes_dir: Path) -> list[ResumeProfile]:
    """Build resume profiles from Adithya's downloaded Google Drive resumes."""
    master_docx = resumes_dir / "resume_2026-10-16.docx"
    attached_da_docx = Path("/home/antigravity/Adithya_Krishna.docx")
    da_docx = attached_da_docx if attached_da_docx.exists() else (resumes_dir / "resume_data_analyst_2026-09-02.docx")
    master_pdf = resumes_dir / "resume_2026-10-26.pdf"

    master_text = extract_text_from_docx(master_docx) if master_docx.exists() else ""
    da_text = extract_text_from_docx(da_docx) if da_docx.exists() else master_text

    master_skills = extract_skills(master_text)
    da_skills = extract_skills(da_text)

    profiles = [
        ResumeProfile(
            profile_id="data_analyst_experienced",
            track="Data Analyst / Power BI & ETL",
            name="Adithya_Krishna.docx (All resumes/Data analyst experienced)",
            drive_file_id="1w1xPVOaNVVCM-3aAmr_ThCeIMOmVPVw9",
            drive_url="https://drive.google.com/file/d/1RF2QTawYhbXBvGvhPM6FZLnwhGN3wpka/view?usp=drivesdk",
            local_path=str(da_docx if da_docx.exists() else master_docx),
            years_experience=4.5,
            skills=da_skills,
            summary_highlights=[
                "4.5 years across Deloitte, NTT DATA, and Optum delivering Power BI, SQL Server, SSIS, DAX, and Power Query solutions",
                "Automated 8+ Power BI workflows with Power Query & Power Automate, cutting manual reporting effort by ~80%",
                "Hands-on Azure Databricks, PySpark, Medallion Architecture, and Power BI Fabric ETL pipelines",
            ],
        ),
        ResumeProfile(
            profile_id="genai_powerbi_ai",
            track="Gen AI & Agentic Analytics",
            name="Adithya_Krishna.pdf (Oct 2026 — Power BI with AI & Agentic Workflows)",
            drive_file_id="15AM2et_gg4aOpBHh41mIwTaDPURSzMjU",
            drive_url="https://drive.google.com/file/d/15AM2et_gg4aOpBHh41mIwTaDPURSzMjU/view?usp=drivesdk",
            local_path=str(master_pdf if master_pdf.exists() else master_docx),
            years_experience=4.5,
            skills=master_skills,
            summary_highlights=[
                "4.5 years in BI, ETL & AI-enabled automation across Deloitte, NTT DATA, and Optum",
                "Built Python agentic workflows & MCP connector integrations for Power BI with Generative AI debugging/automation",
                "Certified in Introduction to LLM, Gen AI & Agentic AI (2026) and OdinSchool Data Science & Gen AI (2024)",
            ],
        ),
        ResumeProfile(
            profile_id="ml_data_science",
            track="ML & Data Science",
            name="Adithya_Krishna.docx (Oct 2026 — Analytics, Python, ML & Gen AI)",
            drive_file_id="16hf-nSajaeDZi1Ll6URz2H0HocBPIxsh",
            drive_url="https://docs.google.com/document/d/16hf-nSajaeDZi1Ll6URz2H0HocBPIxsh/edit?usp=drivesdk",
            local_path=str(master_docx),
            years_experience=4.5,
            skills=master_skills,
            summary_highlights=[
                "4.5 years in analytics & data engineering with Python (Pandas, NumPy, Matplotlib, Seaborn), SQL, PySpark & Azure Databricks",
                "Built XGBoost & Random Forest predictive ML models and EDA pipelines",
                "OdinSchool Data Science certification covering ML models, Python analytics, and Generative AI",
            ],
        ),
    ]
    return profiles


def _experience_fit(candidate_years: float, job: JobListing) -> tuple[str, int]:
    """Assess whether candidate_years (4.5) matches the job's experience requirement."""
    bounds = parse_experience_bounds(job.experience) or parse_experience_bounds(job.description)
    if bounds is None:
        return "unknown", 0
    lo, hi = bounds
    if lo <= candidate_years + 0.5 and (hi is None or candidate_years <= hi + 2):
        # e.g. 3-5 yrs, 3-6 yrs, 3+ yrs, 4+ yrs, 5+ yrs (4.5 is within 0.5 yr)
        return "strong", 10
    if lo <= candidate_years + 1.5:
        # e.g. 6+ yrs is a slight stretch for 4.5 yrs
        return "stretch", 2
    # e.g. 8+ or 10+ years is significantly above 4.5 yrs
    return "mismatch", -18


def _build_tailored_pitch(job: JobListing, profile: ResumeProfile, matched: list[str]) -> str:
    top_skills = ", ".join(matched[:6]) if matched else "Power BI, SQL, Python, and ETL"
    highlight = profile.summary_highlights[0] if profile.summary_highlights else ""
    return (
        f"Hi {job.company} Hiring Team — I am applying for the {job.title} role in {job.location}. "
        f"With {profile.years_experience} years of experience ({highlight}), I bring direct hands-on "
        f"strength in {top_skills}. At Deloitte and Optum, I automated 8+ Power BI/SQL reporting "
        f"workflows cutting manual effort by 50–80%, and I build Python/Gen AI agentic automation pipelines."
    )


def evaluate_job_against_profile(job: JobListing, profile: ResumeProfile) -> ResumeMatchResult:
    """Compute an honest 0-100% match score between a job posting and a single ResumeProfile."""
    jd_text = f"{job.title}\n{job.description}\n{' '.join(job.raw_skills)}"
    jd_skills = extract_skills(jd_text)
    resume_skill_set = set(profile.skills)

    matched = [s for s in jd_skills if s in resume_skill_set]
    missing = [s for s in jd_skills if s not in resume_skill_set]

    if not jd_skills:
        coverage_pct = 0
    else:
        coverage_pct = int(round((len(matched) / len(jd_skills)) * 100))

    # Require at least 3 concrete JD skills before full coverage weight applies,
    # preventing sparse/boilerplate JDs from falsely scoring >=80%.
    richness_factor = min(1.0, len(jd_skills) / 3.0) if jd_skills else 0.0
    skill_component = coverage_pct * 0.80 * richness_factor

    title_lower = job.title.lower()
    track_keywords = TRACK_TITLE_SIGNALS.get(profile.track, ())
    title_bonus = 10.0 if any(k in title_lower for k in track_keywords) else 0.0

    exp_label, exp_delta = _experience_fit(profile.years_experience, job)

    final_score = int(round(max(0.0, min(100.0, skill_component + title_bonus + exp_delta))))

    return ResumeMatchResult(
        job_id=job.job_id,
        fingerprint=job.fingerprint,
        source=job.source,
        title=job.title,
        company=job.company,
        location=job.location,
        experience=job.experience,
        posted_date=job.posted_date,
        url=job.url,
        resume_match_pct=final_score,
        jd_skill_coverage_pct=coverage_pct,
        experience_fit=exp_label,
        best_resume_id=profile.profile_id,
        best_resume_track=profile.track,
        best_resume_name=profile.name,
        best_resume_local_path=profile.local_path,
        best_resume_drive_url=profile.drive_url,
        matched_skills=matched,
        missing_skills=missing,
        jd_skills_detected=jd_skills,
        tailored_pitch=_build_tailored_pitch(job, profile, matched),
    )


def match_jobs_to_resumes(
    jobs: list[JobListing],
    profiles: list[ResumeProfile],
    *,
    min_match_pct: int = 80,
) -> tuple[list[ResumeMatchResult], list[ResumeMatchResult]]:
    """Evaluate every job against all resume profiles, returning (all_matches, qualified_>=min_match)."""
    all_best: list[ResumeMatchResult] = []
    for job in jobs:
        candidates = [evaluate_job_against_profile(job, p) for p in profiles]
        best = max(
            candidates,
            key=lambda r: (r.resume_match_pct, r.jd_skill_coverage_pct, len(r.matched_skills)),
        )
        all_best.append(best)

    all_best.sort(key=lambda r: (-r.resume_match_pct, -r.jd_skill_coverage_pct, r.company.lower()))
    qualified = [r for r in all_best if r.resume_match_pct >= min_match_pct]
    return all_best, qualified


def save_resume_profiles(profiles: list[ResumeProfile], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([p.to_dict() for p in profiles], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path
