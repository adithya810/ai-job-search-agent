"""Stage 04: JD Skill Match Scorer & >=80% Filter Gate.

Implements Column 04 of the Job Search & Auto-Apply Agentic Architecture:
  - Cross-portal JD deduplication (URL + Company/Role fingerprint)
  - Strict <= 48 hours freshness & experience alignment verification
  - JD vs Resume Skills scoring (0-100%) using Shared Agent Memory
  - Filter Gate: Match >= 80% -> Pass to Apply Button Gate; < 80% -> Filtered Out / Skipped
"""

import re
from typing import Dict, List, Tuple, Any, Optional
from config import MATCH_THRESHOLD_PERCENT

HIGH_RELEVANCE_TITLES = [
    "data analyst",
    "mis executive",
    "ai/ml engineer",
    "ai ml engineer",
    "machine learning engineer",
    "data scientist",
    "power bi developer",
    "power bi analyst",
    "power bi specialist",
    "power bi reporting",
    "insights analyst",
    "mis analyst",
    "reporting analyst",
    "operations analyst",
    "claims reporting",
    "business data analyst",
    "junior data analyst",
    "associate data analyst",
    "senior data analyst",
    "data engineer",
    "etl developer",
    "analytics engineer",
    "bi developer",
    "bi analyst",
    "business intelligence",
    "decision science",
    "genai engineer",
    "generative ai",
    "python developer",
    "excel analyst",
    "dashboard analyst",
]

NEGATIVE_TITLES = [
    "ios developer",
    "android developer",
    "react native",
    "java architect",
    "golang",
    "ruby on rails",
    "civil engineer",
    "mechanical engineer",
    "accountant",
    "hr recruiter",
    "sales executive",
    "customer support voice",
]

# Canonical Resume Skill Name -> Regex patterns
RESUME_SKILL_PATTERNS = [
    ("Python", [r"\bpython\b"]),
    ("Pandas", [r"\bpandas\b"]),
    ("NumPy", [r"\bnumpy\b"]),
    ("Scikit-learn", [r"scikit[\s\-]?learn", r"\bsklearn\b"]),
    ("Matplotlib", [r"\bmatplotlib\b"]),
    ("Seaborn", [r"\bseaborn\b"]),
    ("TensorFlow", [r"\btensorflow\b"]),
    ("PyTorch", [r"\bpytorch\b"]),
    ("spaCy", [r"\bspacy\b"]),
    ("Keras", [r"\bkeras\b"]),
    ("Deep Learning", [r"deep\s+learning", r"\bdl\b"]),
    ("Machine Learning", [r"machine\s+learning", r"\bml\b", r"predictive\s+modeling", r"regression", r"classification"]),
    ("NLP", [r"\bnlp\b", r"natural\s+language\s+processing", r"text\s+analytics"]),
    ("LSTM / CNN / Transformers", [r"\blstm\b", r"\bcnn\b", r"transformer", r"self[\s\-]?attention"]),
    ("Generative AI & LLMs", [r"generative\s+ai", r"\bgenai\b", r"gen\s+ai", r"\bllm\b", r"\bllms\b", r"large\s+language\s+model"]),
    ("Prompt Engineering", [r"prompt\s+engineering", r"prompt\s+design"]),
    ("Agentic Workflows & Automation", [r"agentic", r"ai\s+agent", r"workflow\s+automation", r"task\s+automation", r"\bmcp\b"]),
    ("SQL", [r"\bsql\b", r"\bmysql\b", r"t[\s\-]?sql", r"postgres", r"query\s+optimization"]),
    ("SQL Server / SSMS / SSIS", [r"sql\s+server", r"\bssms\b", r"\bssis\b", r"\bmssql\b", r"\bssrs\b"]),
    ("ETL Pipelines", [r"\betl\b", r"\belt\b", r"data\s+pipeline", r"data\s+integration", r"data\s+ingestion"]),
    ("Azure & Cloud Data", [r"\bazure\b", r"azure\s+data\s+factory", r"\badf\b", r"cloud\s+data"]),
    ("Azure Databricks", [r"databricks", r"azure\s+databricks"]),
    ("PySpark", [r"\bpyspark\b", r"apache\s+spark", r"\bspark\b"]),
    ("Medallion Architecture & Fabric", [r"medallion", r"power\s+bi\s+fabric", r"microsoft\s+fabric", r"data\s+lake", r"data\s+warehouse"]),
    ("Power BI", [r"power\s*bi", r"\bpbi\b", r"power\s+bi\s+service"]),
    ("DAX", [r"\bdax\b", r"data\s+modeling"]),
    ("Power Query", [r"power\s+query", r"\bm\s+query\b"]),
    ("Power Automate", [r"power\s+automate", r"power\s+apps", r"power\s+platform"]),
    ("Row-Level Security (RLS)", [r"\brls\b", r"row[\s\-]?level\s+security"]),
    ("Advanced Excel", [r"advanced\s+excel", r"\bexcel\b", r"vlookup", r"xlookup", r"pivot\s+table", r"\bmacros\b", r"\bvba\b", r"openpyxl"]),
    ("MIS & KPI Reporting", [r"\bmis\b", r"kpi\s+reporting", r"\bkpi\b", r"\bkpis\b", r"scheduled\s+report", r"ad[\s\-]?hoc\s+report", r"reporting"]),
    ("Dashboard & Data Storytelling", [r"dashboard", r"data\s+visualization", r"data\s+storytelling", r"bi\s+tools"]),
    ("Data Validation & Reconciliation", [r"data\s+validation", r"data\s+reconciliation", r"reconcil", r"data\s+quality", r"data\s+cleaning", r"data\s+cleansing", r"data\s+consolidation"]),
    ("Root Cause Analysis", [r"root[\s\-]?cause", r"\brca\b", r"variance\s+analysis", r"trend\s+analysis"]),
    ("Stakeholder Management & SOPs", [r"stakeholder", r"\bsop\b", r"\bsops\b", r"documentation", r"business\s+requirements"]),
]

COMMON_EXTERNAL_SKILLS = [
    ("Snowflake", r"\bsnowflake\b"),
    ("AWS", r"\baws\b"),
    ("GCP / BigQuery", r"\bgcp\b|\bbigquery\b"),
    ("Tableau", r"\btableau\b"),
    ("Alteryx", r"\balteryx\b"),
    ("Docker / Kubernetes", r"\bdocker\b|\bkubernetes\b"),
    ("Airflow / MLOps", r"\bairflow\b|\bmlflow\b|\bkubeflow\b"),
    ("Kafka", r"\bkafka\b"),
    ("dbt", r"\bdbt\b"),
]


def is_experience_below_4_years(exp_str: str, desc_str: str = "") -> Tuple[bool, str]:
    """Checks if minimum experience requirement fits Adithya Krishna's 4.5 years experience."""
    combined = f"{exp_str or ''} {desc_str[:600] if desc_str else ''}".lower()
    if not combined.strip():
        return True, "0-4.5 Years"

    range_matches = re.findall(r"(\d+)\s*(?:to|\-|\–)\s*(\d+)\s*(?:yrs|years|yr)", combined)
    for min_s, max_s in range_matches:
        min_y = int(min_s)
        if min_y > 5:
            return False, f"Requires {min_s}-{max_s} yrs (> 5 yrs)"

    plus_matches = re.findall(r"(\d+)\+\s*(?:yrs|years|yr)", combined)
    for min_s in plus_matches:
        min_y = int(min_s)
        if min_y > 5:
            return False, f"Requires {min_y}+ yrs (> 5 yrs)"

    return True, exp_str or "1-4.5 Years"


def extract_matching_and_missing_skills(
    job: Dict[str, Any],
    memory_skills: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    """Returns (matched_resume_skills, missing_or_bonus_skills) for a given job dict."""
    title = (job.get("title") or "").lower()
    skills_txt = (job.get("skills") or "").lower()
    desc_txt = (job.get("description") or "").lower()
    full_blob = f"{title} {skills_txt} {desc_txt}"

    allowed_set = set(memory_skills) if memory_skills else None
    matched: List[str] = []
    for canonical_name, regex_list in RESUME_SKILL_PATTERNS:
        if allowed_set is not None and canonical_name not in allowed_set:
            continue
        if any(re.search(pat, full_blob) for pat in regex_list):
            matched.append(canonical_name)

    # Only infer baseline title skills when the scraped card had no full JD text yet (< 160 chars)
    if not matched and len(desc_txt.strip()) < 160:
        if any(hr in title for hr in HIGH_RELEVANCE_TITLES):
            if "mis" in title or "reporting" in title:
                matched = ["MIS & KPI Reporting", "Advanced Excel", "Power BI"]
            elif "power bi" in title:
                matched = ["Power BI", "DAX", "Power Query", "SQL"]
            elif "ai" in title or "ml" in title or "machine learning" in title or "data scientist" in title:
                matched = ["Python", "Pandas", "Scikit-learn", "Machine Learning"]
            elif "data analyst" in title or "insights analyst" in title or "business data analyst" in title:
                matched = ["Python", "SQL", "Power BI", "Advanced Excel"]

    missing: List[str] = []
    for ext_name, ext_pat in COMMON_EXTERNAL_SKILLS:
        if re.search(ext_pat, full_blob):
            missing.append(ext_name)

    return matched, missing


def summarize_job_description(job: Dict[str, Any], max_chars: int = 420) -> str:
    """Builds a clean, structured Job Description (JD) summary for Excel Column 3."""
    loc = (job.get("location") or "India").strip()
    exp = (job.get("experience") or "1-4.5 Years").strip()
    raw_desc = re.sub(r"\s+", " ", str(job.get("description") or "")).strip()
    if not raw_desc:
        raw_desc = f"{job.get('title', 'Role')} at {job.get('company', 'Hiring Organization')}."
    if len(raw_desc) > max_chars:
        snippet = raw_desc[: max_chars - 3].rsplit(" ", 1)[0] + "..."
    else:
        snippet = raw_desc
    return f"Location: {loc} | Exp: {exp}\n{snippet}"


def compute_resume_match(
    job: Dict[str, Any],
    target_companies: Optional[List[str]] = None,
    memory_skills: Optional[List[str]] = None,
    memory_roles: Optional[List[str]] = None,
) -> Tuple[float, List[str], str]:
    """Stage 04 — Computes deterministic resume match score (0 - 100%) against Shared Agent Memory."""
    target_companies = target_companies or []
    title = (job.get("title") or "").lower()
    company = (job.get("company") or "").lower()
    location = (job.get("location") or "").lower()
    exp_str = (job.get("experience") or "")
    desc = (job.get("description") or "")

    if any(neg in title for neg in NEGATIVE_TITLES) and not any(
        pos in title for pos in ["data", "mis", "bi", "analyst", "ai", "ml", "python", "etl"]
    ):
        job["missing_skills"] = []
        return 30.0, [], "Filtered out: Non-analytics role"

    # 1. Role Alignment (up to 38 pts)
    dynamic_roles = [r.lower() for r in (memory_roles or [])]
    role_pts = 16.0
    if any(hr in title for hr in HIGH_RELEVANCE_TITLES) or any(dr in title for dr in dynamic_roles):
        role_pts = 36.0
        if any(
            exact in title
            for exact in [
                "data analyst",
                "mis executive",
                "power bi",
                "ai/ml",
                "ai ml",
                "machine learning",
                "reporting analyst",
                "insights analyst",
                "mis analyst",
                "data scientist",
                "data engineer",
            ]
        ):
            role_pts = 38.0
    elif any(k in title for k in ["analyst", "analytics", "reporting", "mis", "bi", "data", "ai", "ml", "python"]):
        role_pts = 31.0

    # 2. Technical Skill Overlap (up to 38 pts)
    matched_skills, missing_skills = extract_matching_and_missing_skills(job, memory_skills=memory_skills)
    job["missing_skills"] = missing_skills
    num_matched = len(matched_skills)
    if num_matched >= 7:
        skill_pts = 38.0
    elif num_matched >= 5:
        skill_pts = 36.0
    elif num_matched >= 3:
        skill_pts = 33.5
    elif num_matched >= 2:
        skill_pts = 29.0
    elif num_matched == 1:
        skill_pts = 20.0
    else:
        skill_pts = 8.0

    # Slight gap penalty if JD demands many external tools with very few matched skills
    if len(missing_skills) >= 3 and num_matched <= 2:
        skill_pts = max(8.0, skill_pts - 8.0)

    # 3. Experience Fit (up to 14 pts)
    exp_ok, _ = is_experience_below_4_years(exp_str, desc)
    exp_pts = 14.0 if exp_ok else 4.0

    # 4. Location & Target Company Fit (up to 10 pts)
    loc_pts = 7.0
    pref_locs = ["hyderabad", "bengaluru", "bangalore", "gurugram", "gurgaon", "chennai", "pune", "india", "remote"]
    if any(pl in location for pl in pref_locs):
        loc_pts = 9.0

    in_target_sheet = any(tc.lower() in company for tc in target_companies if tc)
    if in_target_sheet:
        loc_pts = 10.0

    total = round(min(99.5, role_pts + skill_pts + exp_pts + loc_pts), 1)
    sheet_tag = " [Check-Sheet Target Company]" if in_target_sheet else ""
    explanation = (
        f"Match {total}% (Role: {role_pts:.0f}/38, Skills: {skill_pts:.0f}/38 [{len(matched_skills)} matched], "
        f"Exp: {exp_pts:.0f}/14, Loc/Company: {loc_pts:.0f}/10){sheet_tag}"
    )
    return total, matched_skills, explanation


def _canonical_dedup_key(job: Dict[str, Any]) -> Tuple[str, str]:
    url = (job.get("url") or "").split("?")[0].rstrip("/").strip().lower()
    comp = re.sub(r"[^a-z0-9]+", "", (job.get("company") or "").lower())
    title = re.sub(r"[^a-z0-9]+", "", (job.get("title") or "").lower())
    return url, f"{comp}::{title}" if (comp and title) else url


def _prefer_job(candidate: Dict[str, Any], incumbent: Dict[str, Any]) -> bool:
    """Prefer entry with native Easy/Quick Apply button or richer JD description."""
    cand_easy = bool(candidate.get("easy_apply"))
    inc_easy = bool(incumbent.get("easy_apply"))
    if cand_easy != inc_easy:
        return cand_easy
    return len(candidate.get("description") or "") > len(incumbent.get("description") or "")


def evaluate_and_gate_jobs(
    raw_jobs: List[Dict[str, Any]],
    memory: Any,
    *,
    threshold_pct: float = MATCH_THRESHOLD_PERCENT,
) -> Dict[str, Any]:
    """Stage 04 — Cross-portal JD deduplication, <=48h verification, scoring & >=80% Filter Gate."""
    from scrapers import is_posted_within_48_hours

    by_url: Dict[str, Dict[str, Any]] = {}
    by_sig: Dict[str, Dict[str, Any]] = {}
    duplicates_removed = 0

    for j in raw_jobs:
        url_key, sig_key = _canonical_dedup_key(j)
        if not url_key:
            continue
        if url_key in by_url:
            duplicates_removed += 1
            if _prefer_job(j, by_url[url_key]):
                by_url[url_key] = j
                by_sig[sig_key] = j
            continue
        if sig_key in by_sig:
            duplicates_removed += 1
            if _prefer_job(j, by_sig[sig_key]):
                old_url = (by_sig[sig_key].get("url") or "").split("?")[0].rstrip("/").strip().lower()
                by_url.pop(old_url, None)
                by_url[url_key] = j
                by_sig[sig_key] = j
            continue
        by_url[url_key] = j
        by_sig[sig_key] = j

    deduped_jobs = list(by_url.values())
    stale_or_exp_rejected = 0
    below_80_rejected = 0
    qualified_jobs: List[Dict[str, Any]] = []
    rejected_jobs: List[Dict[str, Any]] = []

    target_companies = getattr(memory, "target_company_names", []) if memory else []
    memory_skills = getattr(memory, "resume_skills", None) if memory else None
    memory_roles = getattr(memory, "target_roles", None) if memory else None

    for job in deduped_jobs:
        if not is_posted_within_48_hours(job.get("posted_date", "")):
            stale_or_exp_rejected += 1
            job["rejection_reason"] = "Posted > 48 hours ago"
            rejected_jobs.append(job)
            continue

        exp_ok, exp_note = is_experience_below_4_years(job.get("experience", ""), job.get("description", ""))
        if not exp_ok:
            stale_or_exp_rejected += 1
            job["rejection_reason"] = exp_note
            rejected_jobs.append(job)
            continue

        score, matched_skills, explanation = compute_resume_match(
            job,
            target_companies=target_companies,
            memory_skills=memory_skills,
            memory_roles=memory_roles,
        )
        job["match_score"] = score
        job["matched_skills"] = matched_skills
        job["match_explanation"] = explanation
        job["jd_summary"] = summarize_job_description(job)

        if score >= threshold_pct:
            qualified_jobs.append(job)
        else:
            below_80_rejected += 1
            job["rejection_reason"] = f"Skill/Role Match {score}% < {threshold_pct}%"
            rejected_jobs.append(job)

    return {
        "qualified_jobs": qualified_jobs,
        "rejected_jobs": rejected_jobs,
        "stats": {
            "raw_count": len(raw_jobs),
            "deduped_count": len(deduped_jobs),
            "duplicates_removed": duplicates_removed,
            "stale_or_exp_rejected": stale_or_exp_rejected,
            "below_threshold_rejected": below_80_rejected,
            "qualified_above_80_count": len(qualified_jobs),
        },
    }
