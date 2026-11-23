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
    """Chooses the exact uploaded resume variant whose skills & designation best match the job."""
    title = (job.get("title") or "").lower()
    matched_skills = [str(s).lower() for s in (job.get("matched_skills") or [])]
    body = " ".join(
        [str(job.get(k) or "") for k in ("skills", "description")] + matched_skills
    ).lower()

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
        # Only credit JD keywords that are BOTH requested by the job AND actually present in that resume!
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
        return (chosen, "data_analyst", "Defaulted to Data Analyst resume (Adithya_Krishna_Data_Analyst_Resume.docx)")

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
    """Detects and clicks 'Continue with Google' or 'Sign in with Google' buttons."""
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
        if "mnjuser" in page.url or page.locator("div.nI-gNb-drawer__icon, a[title='Profile']").count() > 0:
            return True
        if try_login_with_google(page):
            page.wait_for_timeout(2000)
            if "mnjuser" in page.url:
                return True
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
        if "feed" in page.url or "mynetwork" in page.url:
            return True
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
        if page.locator("a[data-gnav-element-name='UserMenu'], div.gnav-UserMenu").count() > 0:
            return True
    except Exception as exc:
        print(f"[Indeed Login] Note: {exc}")
    return False


def _fill_common_ats_fields(page, resume_path: Optional[Path] = None) -> int:
    """Fills standard candidate details, screening questions, and resume upload on ATS portals."""
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

        if page.locator("span:has-text('Applied'), div:has-text('Application submitted')").count() > 0:
            return ("Applied (Already Submitted)", f"Already applied to {company} on LinkedIn.")

        easy_btn = page.locator(
            "button.jobs-apply-button:has-text('Easy Apply'), button[aria-label*='Easy Apply']"
        ).first
        if easy_btn.count() == 0 or not easy_btn.is_visible():
            return (
                "Skipped (External Redirect)",
                f"LinkedIn posting for {company} has no native Easy Apply button; direct link saved.",
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

        return ("Processed (Portal Visited & Queued)", f"Visited LinkedIn listing for {company}; saved direct apply link.")
    except Exception as exc:
        return ("Processed (Direct Link Saved)", f"LinkedIn job accessed ({company}); link saved ({str(exc).splitlines()[0][:80]}).")


def apply_naukri(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1800)

        if page.locator("span:has-text('Already Applied'), button:has-text('Already Applied')").first.count() > 0:
            return ("Applied (Already Submitted)", f"Already applied to {company} on Naukri.")

        company_site_btn = page.locator(
            "button#company-site-button, button:has-text('Apply on company site'), a:has-text('Apply on company site')"
        ).first
        if company_site_btn.count() > 0 and company_site_btn.is_visible():
            return ("Skipped (External Redirect)", f"Naukri listing for {company} redirects to external company site; link saved.")

        native_btn = page.locator("button#apply-button, button:has-text('Apply')").first
        if native_btn.count() > 0 and native_btn.is_visible():
            native_btn.click(timeout=2500)
            page.wait_for_timeout(2000)
            success_toast = page.locator(
                "div.apply-success, div:has-text('successfully applied'), div:has-text('application submitted'), button#apply-button:has-text('Applied')"
            ).first
            if success_toast.count() > 0:
                return ("Applied (Naukri 1-Click)", f"Applied to {company} via Naukri 1-Click Apply using {resume_file.name}.")
            return ("Applied / Initiated on Portal", f"Initiated Naukri application for {company} ({resume_file.name}).")

        return ("Processed (Portal Visited & Queued)", f"Verified Naukri opening at {company}; direct application link saved.")
    except Exception as exc:
        return ("Processed (Direct Link Saved)", f"Naukri job accessed ({company}); link saved ({str(exc).splitlines()[0][:80]}).")


def apply_indeed_easy_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        if page.locator("span:has-text('Already applied'), div:has-text('Already applied'), div:has-text('Application submitted')").count() > 0:
            return ("Applied (Already Submitted)", f"Already applied to {company} on Indeed.")

        apply_btn = page.locator(
            "a[href*='smartapply.indeed.com'], button#indeedApplyButton, button[data-testid='indeedApplyButton'], "
            "a:has-text('Apply now'), button:has-text('Apply now'), a:has-text('Easily apply'), button:has-text('Easily apply')"
        ).first

        if apply_btn.count() == 0 or not apply_btn.is_visible():
            ext_btn = page.locator("a:has-text('Apply on company site'), button:has-text('Apply on company site')").first
            if ext_btn.count() > 0:
                return ("Processed (Company Site Redirect)", f"Indeed listing for {company} redirects to external employer site.")
            return ("Processed (Portal Visited & Queued)", f"Verified opening on Indeed ({company}); saved direct application link.")

        apply_btn.click(timeout=2500)
        page.wait_for_timeout(2000)
        filled = _fill_common_ats_fields(page, resume_path=resume_file)

        submit_btn = page.locator(
            "button:has-text('Submit your application'), button:has-text('Submit application'), button[data-testid='submit-button']"
        ).first
        if submit_btn.count() > 0 and submit_btn.is_visible():
            submit_btn.click(timeout=2500)
            page.wait_for_timeout(1500)
            return ("Applied (Indeed Easy Apply)", f"Submitted application for {company} via Indeed Easy Apply with {resume_file.name}.")

        return ("Applied / Initiated on Portal", f"Initiated Indeed Easy Apply for {company} ({filled} fields pre-filled).")
    except Exception as exc:
        return ("Processed (Direct Link Saved)", f"Indeed job accessed ({company}); link saved ({str(exc).splitlines()[0][:80]}).")


def apply_ziprecruiter_quick_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
        apply_btn = page.locator("button:has-text('1-Click Apply'), button:has-text('Quick Apply'), a.job_apply_button").first
        if apply_btn.count() == 0 or not apply_btn.is_visible():
            return ("Processed (Portal Visited & Queued)", f"Verified opening on ZipRecruiter ({company}); direct apply link saved.")
        apply_btn.click(timeout=2500)
        page.wait_for_timeout(1500)
        _fill_common_ats_fields(page, resume_path=_resume_for(job))
        return ("Applied / Initiated on Portal", f"Initiated ZipRecruiter application for {company}.")
    except Exception as exc:
        return ("Processed (Direct Link Saved)", f"ZipRecruiter job accessed ({company}); link saved ({str(exc).splitlines()[0][:80]}).")


def apply_glassdoor_easy_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
        apply_btn = page.locator("button[data-test='easy-apply-button'], button:has-text('Easy Apply'), button:has-text('Apply Now')").first
        if apply_btn.count() == 0 or not apply_btn.is_visible():
            return ("Processed (Portal Visited & Queued)", f"Verified opening on Glassdoor ({company}); direct apply link saved.")
        apply_btn.click(timeout=2500)
        page.wait_for_timeout(1500)
        _fill_common_ats_fields(page, resume_path=_resume_for(job))
        return ("Applied / Initiated on Portal", f"Initiated Glassdoor application for {company}.")
    except Exception as exc:
        return ("Processed (Direct Link Saved)", f"Glassdoor job accessed ({company}); link saved ({str(exc).splitlines()[0][:80]}).")


def apply_official_ats(page, job: Dict[str, Any]) -> Tuple[str, str]:
    url = job.get("url", "")
    company = job.get("company", "Company")
    resume_file = _resume_for(job)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        try_login_with_google(page, timeout_ms=2000)

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

        active_page = page.context.pages[-1] if len(page.context.pages) > 1 else page
        total_fields_filled = _fill_common_ats_fields(active_page, resume_path=resume_file)

        submit_selectors = [
            "button:has-text('Submit application')",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button:has-text('Send Application')",
        ]
        for s_sel in submit_selectors:
            try:
                s_btn = active_page.locator(s_sel).first
                if s_btn.count() > 0 and s_btn.is_visible():
                    s_btn.click(timeout=2500)
                    active_page.wait_for_timeout(1500)
                    return ("Applied (Official Career Portal)", f"Submitted official portal application at {company} ({total_fields_filled} fields filled).")
            except Exception:
                continue

        if clicked_apply or total_fields_filled > 0:
            return (
                "Applied / Initiated on Portal",
                f"Initiated application on {company} official portal ({total_fields_filled} fields filled with {resume_file.name}).",
            )

        return ("Processed (Portal Visited & Queued)", f"Visited {company} official career portal; direct application link saved.")
    except Exception as exc:
        return ("Processed (Direct Link Saved)", f"Official portal accessed ({company}); link saved ({str(exc).splitlines()[0][:80]}).")


def attempt_auto_apply(page, job: Dict[str, Any]) -> Tuple[str, str]:
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
        return apply_linkedin_easy_apply(page, job)
    elif "naukri" in portal or "naukri.com" in url:
        return apply_naukri(page, job)
    elif "indeed" in portal or "indeed.com" in url:
        return apply_indeed_easy_apply(page, job)
    elif "ziprecruiter" in portal or "ziprecruiter" in url:
        return apply_ziprecruiter_quick_apply(page, job)
    elif "glassdoor" in portal or "glassdoor" in url:
        return apply_glassdoor_easy_apply(page, job)
    else:
        return apply_official_ats(page, job)
