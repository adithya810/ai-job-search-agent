import re
from typing import Dict, List, Tuple, Any
from config import CANDIDATE_PROFILE, MATCH_THRESHOLD_PERCENT

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
]

# Comprehensive skill alias map -> Canonical Resume Skill Name
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
    ("Dashboard & Data Storytelling", [r"dashboard", r"data\s+visualization", r"data\s+storytelling", r"tableau", r"bi\s+tools"]),
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
    """
    Checks if the job's minimum experience requirement fits Adithya Krishna's 4.5 years experience
    (accepts 0 to 5 years minimum experience; filters out senior 6+ or 8+ year minimum roles).
    """
    combined = f"{exp_str or ''} {desc_str[:600] if desc_str else ''}".lower()
    if not combined.strip():
        return True, "0-4.5 Years"

    # Match explicit ranges like "6-10 years", "8+ years", "7 to 10 yrs"
    range_matches = re.findall(r"(\d+)\s*(?:to|\-|\–)\s*(\d+)\s*(?:yrs|years|yr)", combined)
    for min_s, max_s in range_matches:
        min_y = int(min_s)
        if min_y > 5:
            return False, f"Requires {min_s}-{max_s} yrs (> 4.5 yrs)"

    plus_matches = re.findall(r"(\d+)\+\s*(?:yrs|years|yr)", combined)
    for min_s in plus_matches:
        min_y = int(min_s)
        if min_y > 5:
            return False, f"Requires {min_y}+ yrs (> 4.5 yrs)"

    return True, exp_str or "0-4.5 Years"


def extract_matching_and_missing_skills(job: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Returns (matched_resume_skills, missing_or_bonus_skills) for a given job dict.
    """
    title = (job.get("title") or "").lower()
    skills_txt = (job.get("skills") or "").lower()
    desc_txt = (job.get("description") or "").lower()
    full_blob = f"{title} {skills_txt} {desc_txt}"

    matched: List[str] = []
    for canonical_name, regex_list in RESUME_SKILL_PATTERNS:
        if any(re.search(pat, full_blob) for pat in regex_list):
            matched.append(canonical_name)

    # Ensure core role skills are always surfaced when title matches
    if not matched:
        if "mis" in title or "reporting" in title:
            matched = ["MIS & KPI Reporting", "Advanced Excel", "Power BI", "Power Query", "Data Validation & Reconciliation"]
        elif "power bi" in title:
            matched = ["Power BI", "DAX", "Power Query", "SQL", "Dashboard & Data Storytelling"]
        elif "ai" in title or "ml" in title or "machine learning" in title or "data scientist" in title:
            matched = ["Python", "Pandas", "NumPy", "Scikit-learn", "Machine Learning", "Generative AI & LLMs", "SQL"]
        else:
            matched = ["Python", "SQL", "Power BI", "Advanced Excel", "Pandas", "MIS & KPI Reporting"]

    missing: List[str] = []
    for ext_name, ext_pat in COMMON_EXTERNAL_SKILLS:
        if re.search(ext_pat, full_blob):
            missing.append(ext_name)

    return matched, missing


def compute_resume_match(job: Dict[str, Any], target_companies: List[str] = None) -> Tuple[float, List[str], str]:
    """
    Computes a deterministic resume match score (0 - 100%) comparing the job against
    Adithya Krishna's 4.5-year Data Analyst / MIS Executive / AI-ML Engineer resume.
    Breakdown:
      - Role Alignment: up to 38 pts
      - Technical Skill Overlap: up to 38 pts
      - Experience Fit (<= 4.5 yrs): up to 14 pts
      - Location & Target Company Fit: up to 10 pts
    """
    target_companies = target_companies or []
    title = (job.get("title") or "").lower()
    company = (job.get("company") or "").lower()
    location = (job.get("location") or "").lower()
    exp_str = (job.get("experience") or "")
    desc = (job.get("description") or "")

    # Negative title check
    if any(neg in title for neg in NEGATIVE_TITLES) and not any(pos in title for pos in ["data", "mis", "bi", "analyst", "ai", "ml", "python", "etl"]):
        return 35.0, [], "Filtered out: Non-analytics software engineering/testing role"

    # 1. Role Alignment (up to 38 pts)
    role_pts = 24.0
    if any(hr in title for hr in HIGH_RELEVANCE_TITLES):
        role_pts = 36.0
        if any(exact in title for exact in ["data analyst", "mis executive", "power bi", "ai/ml", "machine learning", "reporting analyst", "insights analyst", "mis analyst", "data scientist"]):
            role_pts = 38.0
    elif any(k in title for k in ["analyst", "analytics", "reporting", "mis", "bi", "data", "ai", "ml", "python"]):
        role_pts = 33.0

    # 2. Technical Skill Overlap (up to 38 pts)
    matched_skills, missing_skills = extract_matching_and_missing_skills(job)
    job["missing_skills"] = missing_skills
    num_matched = len(matched_skills)
    if num_matched >= 7:
        skill_pts = 38.0
    elif num_matched >= 5:
        skill_pts = 36.0
    elif num_matched >= 3:
        skill_pts = 33.5
    elif num_matched >= 2:
        skill_pts = 30.0
    else:
        skill_pts = 26.0

    # 3. Experience Fit (up to 14 pts)
    exp_ok, _ = is_experience_below_4_years(exp_str, desc)
    exp_pts = 14.0 if exp_ok else 6.0

    # 4. Location & Target Company Fit (up to 10 pts)
    loc_pts = 7.0
    pref_locs = ["hyderabad", "bengaluru", "bangalore", "gurugram", "gurgaon", "chennai", "india", "remote"]
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
