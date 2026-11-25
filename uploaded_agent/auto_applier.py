"""Stage 05: Apply Button Gate & Conditional Auto-Apply Executor.

For every >= 80% matched job from Stage 04:
  - Selects the best role-tailored resume variant (AI/ML, Power BI, Data Engineer, MIS, Business Analyst, Data Analyst)
  - Inspects the job page for an available native/direct Apply button:
      * LinkedIn `Easy Apply`
      * Naukri `1-Click Apply` (`#apply-button`)
      * ZipRecruiter `1-Click Apply` / `Quick Apply`
      * Company Career Portal `Apply` / `Apply Now` + accessible ATS Submit
  - Safety rule: Never attempts to solve or bypass CAPTCHAs, anti-bot challenges, or unauthenticated walls;
    cleanly falls back to preserving the Direct Apply Link in Output Excel.
  - Returns structured apply outcome so Stage 06 writes the APPLIED RESULT instead of the Apply Link
    whenever applied, and writes the clickable Apply Link otherwise.
"""

from datetime import datetime, timedelta, timezone
import re
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path

from config import (
    BASE_DIR,
    LOGIN_EMAIL,
    LOGIN_PASSWORD,
    CANDIDATE_PROFILE,
    RESUME_PDF_PATH,
    AIML_RESUME_DOCX_PATH,
    DA_RESUME_DOCX_PATH,
    MIS_RESUME_DOCX_PATH,
)

RESUMES_DIR = BASE_DIR / "resumes"

ANTIBOT_PATTERNS = re.compile(
    r"(?:verify\s+you\s+are\s+human|cf-turnstile|g-recaptcha|hcaptcha|security\s+verification|"
    r"unusual\s+traffic|please\s+complete\s+the\s+security\s+check)",
    re.IGNORECASE,
)

RESUME_VARIANTS: List[Dict[str, Any]] = [
    {
        "key": "ai_ml_engineer",
        "file": "Adithya_Krishna_AIML_Engineer.pdf",
        "source_docx": AIML_RESUME_DOCX_PATH,
        "title_keywords": [
            "ai/ml engineer", "ai ml engineer", "machine learning engineer", "data scientist",
            "deep learning", "generative ai", "genai", "nlp engineer", "ai engineer",
            "ml engineer", "llm engineer", "ai & data", "decision science", "analytics engineering & ai",
        ],
        "jd_keywords": [
            "scikit-learn", "tensorflow", "pytorch", "spacy", "keras", "lstm", "cnn",
            "transformers", "generative ai", "genai", "llms", "llm", "machine learning",
            "deep learning", "nlp", "agentic", "prompt engineering", "neural network",
        ],
    },
    {
        "key": "power_bi_developer",
        "file": "Adithya_Krishna_Power_BI_Developer.pdf",
        "source_docx": DA_RESUME_DOCX_PATH,
        "title_keywords": [
            "power bi developer", "power bi analyst", "power bi", "bi developer", "bi analyst",
            "business intelligence", "dashboard developer", "reporting developer", "visualization",
        ],
        "jd_keywords": [
            "power bi", "dax", "power query", "rls", "row-level security",
            "data modeling", "power bi service", "power automate", "power bi fabric", "mcp",
        ],
    },
    {
        "key": "data_engineer",
        "file": "Adithya_Krishna_Data_Engineer.pdf",
        "source_docx": DA_RESUME_DOCX_PATH,
        "title_keywords": [
            "data engineer", "etl developer", "etl", "analytics engineer",
            "big data", "databricks", "pyspark", "data platform",
        ],
        "jd_keywords": [
            "etl", "ssis", "ssms", "sql server", "pyspark", "databricks",
            "azure", "azure databricks", "pipeline", "medallion", "data warehouse", "fabric",
        ],
    },
    {
        "key": "mis_executive",
        "file": "Adithya_Krishna_MIS_Executive.pdf",
        "source_docx": MIS_RESUME_DOCX_PATH,
        "title_keywords": [
            "mis executive", "mis analyst", "mis reporting", "mis", "management information systems",
            "reporting analyst", "reporting executive", "operations analyst", "claims reporting", "operations mis",
        ],
        "jd_keywords": [
            "mis", "advanced excel", "excel reporting", "vlookup", "xlookup", "pivot",
            "macros", "reconciliation", "daily reports", "scheduled report", "ad-hoc", "kpi reporting",
        ],
    },
    {
        "key": "business_analyst",
        "file": "Adithya_Krishna_Business_Analyst.pdf",
        "source_docx": DA_RESUME_DOCX_PATH,
        "title_keywords": ["business analyst", "business data analyst", "insights analyst", "business analytics"],
        "jd_keywords": ["stakeholder", "requirements", "kpi", "business insights", "process improvement", "sops", "power bi", "sql"],
    },
    {
        "key": "data_analyst",
        "file": "Adithya_Krishna_Data_Analyst.pdf",
        "source_docx": DA_RESUME_DOCX_PATH,
        "title_keywords": ["data analyst", "junior data analyst", "associate data analyst", "senior data analyst", "data analytics"],
        "jd_keywords": ["sql", "python", "pandas", "numpy", "excel", "power bi", "dax", "power query", "data analysis", "etl"],
    },
]

_RESUME_TEXT_CACHE: Dict[str, str] = {}


def _ist_now_short() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")


def is_status_applied(status: str) -> bool:
    """Returns True strictly when an application has been submitted or previously applied."""
    s = (status or "").strip().lower()
    return (
        s.startswith("applied (")
        or s.startswith("already applied")
        or "auto-submitted" in s
    )


def _has_antibot_gate(page) -> bool:
    """Detects CAPTCHAs or verification gates without ever interacting with them."""
    try:
        u = (page.url or "").lower()
        if any(tok in u for tok in ("checkpoint/challenge", "captcha", "challenge")):
            return True
        html_head = (page.content() or "")[:8000]
        return bool(ANTIBOT_PATTERNS.search(html_head))
    except Exception:
        return False


def _get_resume_text(docx_path: Path) -> str:
    key = str(docx_path)
    if key in _RESUME_TEXT_CACHE:
        return _RESUME_TEXT_CACHE[key]
    if not docx_path.exists():
        _RESUME_TEXT_CACHE[key] = ""
        return ""
    try:
        import docx as _docx

        d = _docx.Document(str(docx_path))
        txt = "\n".join(p.text for p in d.paragraphs if p.text).lower()
    except Exception:
        txt = ""
    _RESUME_TEXT_CACHE[key] = txt
    return txt


def _kw_in(text: str, keyword: str) -> bool:
    return re.search(r"\b" + re.escape(keyword.lower()) + r"\b", text) is not None


def select_resume_for_job(job: Dict[str, Any]) -> Tuple[Path, str, str]:
    """Chooses the exact resume variant whose skills & designation best match the job."""
    title = (job.get("title") or "").lower()
    matched_skills = [str(s).lower() for s in (job.get("matched_skills") or [])]
    body = " ".join([str(job.get(k) or "") for k in ("skills", "description")] + matched_skills).lower()

    best: Optional[Dict[str, Any]] = None
    best_score = 0
    best_title_hits: List[str] = []
    best_jd_hits: List[str] = []

    for variant in RESUME_VARIANTS:
        pdf_path = RESUMES_DIR / variant["file"]
        src_docx = variant.get("source_docx")
        if not pdf_path.exists() and not (src_docx and Path(src_docx).exists()):
            continue

        resume_txt = _get_resume_text(Path(src_docx)) if src_docx else ""
        title_hits = [k for k in variant["title_keywords"] if _kw_in(title, k)]
        jd_hits = [
            k for k in variant["jd_keywords"]
            if _kw_in(body, k) and (not resume_txt or _kw_in(resume_txt, k))
        ]
        score = sum(12 * len(k.split()) for k in title_hits) + 3 * len(jd_hits)
        if score > best_score:
            best, best_score = variant, score
            best_title_hits, best_jd_hits = title_hits, jd_hits

    if best is None or best_score < 2:
        fallback = RESUMES_DIR / "Adithya_Krishna_Data_Analyst.pdf"
        chosen = fallback if fallback.exists() else RESUME_PDF_PATH
        return (chosen, "data_analyst", "Defaulted to Data Analyst resume")

    src_name = Path(best["source_docx"]).name if best.get("source_docx") else best["file"]
    reason = f"Source: {src_name} | Title match: {best_title_hits or ['skills-based']} | Skill overlap: {best_jd_hits[:6] or ['core']}"
    chosen_path = RESUMES_DIR / best["file"]
    if not chosen_path.exists() and best.get("source_docx"):
        chosen_path = Path(best["source_docx"])
    return (chosen_path, best["key"], reason)


def _resume_for(job: Dict[str, Any]) -> Path:
    rp = job.get("resume_path") if isinstance(job, dict) else None
    if rp:
        p = Path(rp)
        if p.exists():
            return p
    return RESUME_PDF_PATH


def try_login_with_google(page, timeout_ms: int = 2500) -> bool:
    """Detects and clicks 'Continue with Google' or 'Sign in with Google' buttons when session is active."""
    try:
        google_selectors = [
            "button:has-text('Continue with Google')",
            "button:has-text('Sign in with Google')",
            "button:has-text('Log in with Google')",
            "a:has-text('Continue with Google')",
            "a:has-text('Sign in with Google')",
        ]
        for sel in google_selectors:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                try:
                    with page.expect_popup(timeout=timeout_ms) as popup_info:
                        btn.click(timeout=2500)
                    popup = popup_info.value
                    popup.wait_for_timeout(1200)
                    acc = popup.locator(f"div:has-text('{LOGIN_EMAIL}'), li[data-identifier*='adithya']").first
                    if acc.count() > 0 and acc.is_visible():
                        acc.click(timeout=2000)
                        popup.wait_for_timeout(1500)
                    return True
                except Exception:
                    btn.click(timeout=2500)
                    page.wait_for_timeout(1500)
                    return True
    except Exception:
        pass
    return False


def try_login_naukri(page) -> bool:
    try:
        page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
        if _has_antibot_gate(page):
            return False
        if "mnjuser" in page.url or page.locator("div.nI-gNb-drawer__icon, a[title='Profile']").count() > 0:
            return True
        if LOGIN_PASSWORD:
            email_input = page.locator("input#usernameField, input[placeholder*='Email'], input[placeholder*='Username']").first
            pass_input = page.locator("input#passwordField, input[type='password']").first
            if email_input.count() > 0 and pass_input.count() > 0 and email_input.is_visible():
                email_input.fill(LOGIN_EMAIL, timeout=2000)
                pass_input.fill(LOGIN_PASSWORD, timeout=2000)
                submit_btn = page.locator("button[type='submit'], button:has-text('Login')").first
                if submit_btn.count() > 0:
                    submit_btn.click(timeout=2500)
                    page.wait_for_timeout(2500)
                    return "mnjuser" in page.url
    except Exception as exc:
        print(f"[Naukri Login] Note: {exc}")
    return False


def try_login_linkedin(page) -> bool:
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1200)
        if _has_antibot_gate(page):
            return False
        if "feed" in page.url or "mynetwork" in page.url:
            return True
        if LOGIN_PASSWORD:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1200)
            email_in = page.locator("input#username, input[name='session_key']").first
            pass_in = page.locator("input#password, input[name='session_password']").first
            if email_in.count() > 0 and pass_in.count() > 0 and email_in.is_visible():
                email_in.fill(LOGIN_EMAIL, timeout=2000)
                pass_in.fill(LOGIN_PASSWORD, timeout=2000)
                btn = page.locator("button[type='submit']").first
                if btn.count() > 0:
                    btn.click(timeout=2500)
                    page.wait_for_timeout(2500)
                    return "feed" in page.url
    except Exception as exc:
        print(f"[LinkedIn Login] Note: {exc}")
    return False


def try_login_indeed(page) -> bool:
    try:
        page.goto("https://in.indeed.com/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1200)
        if not _has_antibot_gate(page) and page.locator("a[data-gnav-element-name='UserMenu'], div.gnav-UserMenu").count() > 0:
            return True
    except Exception as exc:
        print(f"[Indeed Login] Note: {exc}")
    return False


def _fill_common_ats_fields(page, resume_path: Optional[Path] = None) -> int:
    """Fills standard candidate details and resume upload on ATS portals."""
    filled = 0
    resume_file = resume_path if (resume_path and resume_path.exists()) else RESUME_PDF_PATH
    field_mappings = [
        ("input[name*='firstName' i], input[name*='first_name' i], input[placeholder*='First Name' i]", CANDIDATE_PROFILE["first_name"]),
        ("input[name*='lastName' i], input[name*='last_name' i], input[placeholder*='Last Name' i]", CANDIDATE_PROFILE["last_name"]),
        ("input[name*='fullName' i], input[name*='full_name' i], input[placeholder*='Full Name' i]", CANDIDATE_PROFILE["full_name"]),
        ("input[type='email'], input[name*='email' i], input[placeholder*='Email' i]", CANDIDATE_PROFILE["email"]),
        ("input[type='tel'], input[name*='phone' i], input[name*='mobile' i]", CANDIDATE_PROFILE["phone"]),
        ("input[name*='city' i], input[placeholder*='City' i]", CANDIDATE_PROFILE["city"]),
        ("input[name*='state' i], input[placeholder*='State' i]", CANDIDATE_PROFILE.get("state", "Telangana")),
        ("input[name*='postal' i], input[name*='pin' i], input[name*='zip' i]", CANDIDATE_PROFILE["pincode"]),
        ("input[name*='country' i], input[placeholder*='Country' i]", "India"),
        ("input[name*='linkedin' i], input[placeholder*='LinkedIn' i]", CANDIDATE_PROFILE["linkedin_url"]),
        ("input[name*='company' i], input[placeholder*='Company' i]", CANDIDATE_PROFILE.get("current_company", "Deloitte")),
    ]

    for selector, val in field_mappings:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible():
                existing = loc.input_value(timeout=1000) or ""
                if not existing.strip():
                    loc.fill(val, timeout=1200)
                    filled += 1
        except Exception:
            continue

    try:
        file_inputs = page.locator("input[type='file']").all()
        for fi in file_inputs[:2]:
            try:
                if resume_file.exists():
                    fi.set_input_files(str(resume_file), timeout=2500)
                    filled += 1
            except Exception:
                continue
    except Exception:
        pass

    return filled


def apply_linkedin_easy_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        if _has_antibot_gate(page):
            return ("Apply Link Available (Verification Gate)", f"Verification gate on LinkedIn for {company}; direct link preserved.")

        if page.locator("span:has-text('Applied'), div:has-text('Application submitted')").count() > 0:
            return ("Applied (Already Submitted on LinkedIn)", f"Application already submitted to {company} on LinkedIn.")

        easy_btn = page.locator(
            "button.jobs-apply-button:has-text('Easy Apply'), button[aria-label*='Easy Apply']"
        ).first
        if easy_btn.count() == 0 or not easy_btn.is_visible():
            return (
                "Apply Button Not Available (External Redirect)",
                f"No LinkedIn Easy Apply button for {company}; direct link preserved.",
            )

        easy_btn.click(timeout=2500)
        page.wait_for_timeout(1500)

        for _ in range(6):
            _fill_common_ats_fields(page, resume_path=resume_file)
            submit_btn = page.locator("button[aria-label*='Submit application'], button:has-text('Submit application')").first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_btn.click(timeout=2500)
                page.wait_for_timeout(1500)
                return ("Applied (LinkedIn Easy Apply)", f"Submitted LinkedIn Easy Apply for {company} with {resume_file.name}.")

            next_btn = page.locator(
                "button[aria-label*='Continue to next step'], button[aria-label*='Review your application'], button:has-text('Next'), button:has-text('Review')"
            ).first
            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click(timeout=2000)
                page.wait_for_timeout(1200)
            else:
                break

        return ("Apply Link Available (Custom Questions Pending)", f"LinkedIn modal requires manual input for {company}; direct link preserved.")
    except Exception as exc:
        return ("Apply Link Available (Manual Apply)", f"LinkedIn link preserved ({str(exc).splitlines()[0][:80]}).")


def apply_naukri(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1800)

        if _has_antibot_gate(page):
            return ("Apply Link Available (Verification Gate)", f"Verification gate on Naukri for {company}; direct link preserved.")

        if page.locator("span:has-text('Already Applied'), button:has-text('Already Applied')").first.count() > 0:
            return ("Applied (Already Submitted on Naukri)", f"Already applied to {company} on Naukri.")

        company_site_btn = page.locator(
            "button#company-site-button, button:has-text('Apply on company site'), a:has-text('Apply on company site')"
        ).first
        if company_site_btn.count() > 0 and company_site_btn.is_visible():
            return ("Apply Button Not Available (Company Site Redirect)", f"Naukri redirects to external site for {company}; direct link preserved.")

        native_btn = page.locator("button#apply-button, button.apply-button:has-text('Apply')").first
        if native_btn.count() > 0 and native_btn.is_visible():
            native_btn.click(timeout=2500)
            page.wait_for_timeout(2000)
            if "login" in (page.url or "").lower():
                return ("Apply Link Available (Login Required)", f"Naukri session required for {company}; direct link preserved.")
            success_toast = page.locator(
                "div.apply-success, div:has-text('successfully applied'), div:has-text('application submitted'), "
                "button#apply-button:has-text('Applied'), span:has-text('Applied')"
            ).first
            if success_toast.count() > 0:
                return ("Applied (Naukri 1-Click Apply)", f"Applied to {company} via Naukri 1-Click Apply using {resume_file.name}.")

        return ("Apply Button Not Available (Direct Link)", f"No 1-Click Apply confirmation on Naukri for {company}; direct link preserved.")
    except Exception as exc:
        return ("Apply Link Available (Manual Apply)", f"Naukri link preserved ({str(exc).splitlines()[0][:80]}).")


def apply_indeed_easy_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        if _has_antibot_gate(page):
            return ("Apply Link Available (Verification Gate)", f"Verification gate on Indeed for {company}; link preserved.")

        if page.locator("span:has-text('Already applied'), div:has-text('Already applied'), div:has-text('Application submitted')").count() > 0:
            return ("Applied (Already Submitted on Indeed)", f"Already applied to {company} on Indeed.")

        apply_btn = page.locator(
            "a[href*='smartapply.indeed.com'], button#indeedApplyButton, button[data-testid='indeedApplyButton'], "
            "button:has-text('Apply now'), button:has-text('Easily apply')"
        ).first

        if apply_btn.count() == 0 or not apply_btn.is_visible():
            return ("Apply Button Not Available (External Site)", f"No native Indeed Apply button for {company}; link preserved.")

        apply_btn.click(timeout=2500)
        page.wait_for_timeout(2000)
        _fill_common_ats_fields(page, resume_path=resume_file)

        submit_btn = page.locator(
            "button:has-text('Submit your application'), button:has-text('Submit application'), button[data-testid='submit-button']"
        ).first
        if submit_btn.count() > 0 and submit_btn.is_visible():
            submit_btn.click(timeout=2500)
            page.wait_for_timeout(1500)
            return ("Applied (Indeed Easy Apply)", f"Submitted application for {company} via Indeed Easy Apply with {resume_file.name}.")

        return ("Apply Link Available (Manual Review Needed)", f"Indeed form requires manual step for {company}; link preserved.")
    except Exception as exc:
        return ("Apply Link Available (Manual Apply)", f"Indeed link preserved ({str(exc).splitlines()[0][:80]}).")


def apply_ziprecruiter_quick_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        if _has_antibot_gate(page):
            return ("Apply Link Available (Verification Gate)", f"Verification gate on ZipRecruiter for {company}; link preserved.")

        if page.locator("button:has-text('Applied'), span:has-text('Applied')").first.count() > 0:
            return ("Applied (Already Submitted on ZipRecruiter)", f"Already applied to {company} on ZipRecruiter.")

        apply_btn = page.locator("button:has-text('1-Click Apply'), button:has-text('Quick Apply')").first
        if apply_btn.count() == 0 or not apply_btn.is_visible():
            return ("Apply Button Not Available (External Redirect)", f"No 1-Click/Quick Apply button on ZipRecruiter ({company}); link preserved.")

        apply_btn.click(timeout=2500)
        page.wait_for_timeout(1500)
        _fill_common_ats_fields(page, resume_path=resume_file)

        submit_btn = page.locator("button:has-text('Submit'), button:has-text('Continue'), button[type='submit']").first
        if submit_btn.count() > 0 and submit_btn.is_visible():
            submit_btn.click(timeout=2500)
            page.wait_for_timeout(1500)

        if page.locator("div:has-text('Application sent'), div:has-text('Applied'), span:has-text('Applied')").count() > 0:
            return ("Applied (ZipRecruiter Quick Apply)", f"Submitted ZipRecruiter Quick Apply for {company} ({resume_file.name}).")

        return ("Apply Link Available (Manual Completion Needed)", f"ZipRecruiter requires manual step for {company}; link preserved.")
    except Exception as exc:
        return ("Apply Link Available (Manual Apply)", f"ZipRecruiter link preserved ({str(exc).splitlines()[0][:80]}).")


def apply_glassdoor_easy_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
        if _has_antibot_gate(page):
            return ("Apply Link Available (Verification Gate)", f"Verification gate on Glassdoor for {company}; link preserved.")
        apply_btn = page.locator("button[data-test='easy-apply-button'], button:has-text('Easy Apply')").first
        if apply_btn.count() == 0 or not apply_btn.is_visible():
            return ("Apply Button Not Available (External Site)", f"No Easy Apply button on Glassdoor ({company}); link preserved.")
        apply_btn.click(timeout=2500)
        page.wait_for_timeout(1500)
        _fill_common_ats_fields(page, resume_path=resume_file)
        submit_btn = page.locator("button:has-text('Submit application'), button:has-text('Submit')").first
        if submit_btn.count() > 0 and submit_btn.is_visible():
            submit_btn.click(timeout=2500)
            page.wait_for_timeout(1500)
            return ("Applied (Glassdoor Easy Apply)", f"Submitted Glassdoor Easy Apply for {company} ({resume_file.name}).")
        return ("Apply Link Available (Manual Apply)", f"Glassdoor manual step needed for {company}; link preserved.")
    except Exception as exc:
        return ("Apply Link Available (Manual Apply)", f"Glassdoor link preserved ({str(exc).splitlines()[0][:80]}).")


def apply_official_ats(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        if _has_antibot_gate(page):
            return ("Apply Link Available (Verification Gate)", f"Verification gate on {company} career portal; direct link preserved.")

        apply_selectors = [
            "button#apply-button",
            "button.apply-button",
            "button:has-text('Apply Now')",
            "button:has-text('Apply')",
            "a:has-text('Apply Now')",
            "a:has-text('Apply')",
        ]
        clicked_apply = False
        for sel in apply_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2500)
                    page.wait_for_timeout(1500)
                    clicked_apply = True
                    break
            except Exception:
                continue

        if not clicked_apply:
            return ("Apply Button Not Available (Direct Link)", f"No direct Apply button found on {company} page; link preserved.")

        active_page = page.context.pages[-1] if len(page.context.pages) > 1 else page
        if _has_antibot_gate(active_page) or any(k in (active_page.url or "").lower() for k in ("login", "signin", "auth")):
            return ("Apply Link Available (Portal Account Login Required)", f"{company} ATS requires manual account sign-in; link preserved.")

        total_fields_filled = _fill_common_ats_fields(active_page, resume_path=resume_file)
        if total_fields_filled == 0:
            return ("Apply Link Available (Manual ATS Form)", f"{company} career portal requires custom ATS form; link preserved.")

        submit_selectors = [
            "button:has-text('Submit application')",
            "button:has-text('Submit Application')",
            "button:has-text('Send Application')",
            "button[type='submit']:has-text('Submit')",
        ]
        for s_sel in submit_selectors:
            try:
                s_btn = active_page.locator(s_sel).first
                if s_btn.count() > 0 and s_btn.is_visible():
                    s_btn.click(timeout=2500)
                    active_page.wait_for_timeout(1500)
                    return (
                        "Applied (Company Career Portal)",
                        f"Submitted official portal application at {company} ({total_fields_filled} fields filled with {resume_file.name}).",
                    )
            except Exception:
                continue

        return ("Apply Link Available (Review & Submit Required)", f"Pre-filled {total_fields_filled} fields on {company}; direct link preserved.")
    except Exception as exc:
        return ("Apply Link Available (Manual Apply)", f"Official portal link preserved ({str(exc).splitlines()[0][:80]}).")


def attempt_auto_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    """Checks for an available Apply button on the job's portal and submits if available."""
    portal = (job.get("portal") or "").lower()
    url = (job.get("url") or "").lower()

    if not url:
        return ("Skipped", "No application URL found.")

    if not job.get("resume_path"):
        resume_path, resume_key, resume_reason = select_resume_for_job(job)
        job["resume_path"] = str(resume_path)
        job["resume_variant"] = resume_key
        job["resume_reason"] = resume_reason

    if "linkedin" in portal or "linkedin.com" in url:
        status, notes = apply_linkedin_easy_apply(page, job)
    elif "naukri" in portal or "naukri.com" in url:
        status, notes = apply_naukri(page, job)
    elif "indeed" in portal or "indeed.com" in url:
        status, notes = apply_indeed_easy_apply(page, job)
    elif "ziprecruiter" in portal or "ziprecruiter" in url:
        status, notes = apply_ziprecruiter_quick_apply(page, job)
    elif "glassdoor" in portal or "glassdoor" in url:
        status, notes = apply_glassdoor_easy_apply(page, job)
    else:
        status, notes = apply_official_ats(page, job)

    applied_ok = is_status_applied(status)
    job["is_applied"] = applied_ok
    job["apply_button_available"] = applied_ok
    if applied_ok:
        resume_name = Path(job.get("resume_path") or RESUME_PDF_PATH).name
        job["applied_result_display"] = f"{status} | Resume: {resume_name} | {_ist_now_short()}"
    else:
        job["applied_result_display"] = ""
    return status, notes
