import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple

from config import BASE_DIR, CANDIDATE_PROFILE

NAUKRI_STATE_PATH = BASE_DIR / "naukri_state.json"

ROTATING_NAUKRI_KEYWORDS = [
    "Data Analyst",
    "MIS Executive",
    "Power BI Developer",
    "AI ML Engineer",
    "Python Data Analyst",
    "SQL Power BI Analyst",
    "Azure Databricks PySpark",
    "MIS Reporting Analyst",
]


class NaukriStateManager:
    def __init__(self, path: Path = NAUKRI_STATE_PATH):
        self.path = path
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "active_naukri_resume_key": "default",
            "last_keyword_index": 0,
            "last_modified_ist": "",
        }

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_todays_search_keywords(self, count: int = 4) -> List[str]:
        idx = int(self.data.get("last_keyword_index", 0)) % len(ROTATING_NAUKRI_KEYWORDS)
        selected = []
        for i in range(count):
            selected.append(ROTATING_NAUKRI_KEYWORDS[(idx + i) % len(ROTATING_NAUKRI_KEYWORDS)])
        self.data["last_keyword_index"] = (idx + 1) % len(ROTATING_NAUKRI_KEYWORDS)
        self.save()
        return selected


state_manager = NaukriStateManager()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def modify_naukri_profile_keywords(page) -> Tuple[bool, str]:
    """
    Visits Naukri profile page when authenticated and refreshes key skills / headline
    so Naukri's recruiter search algorithm ranks Adithya Krishna's profile as 'Updated Today'.
    """
    try:
        page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded", timeout=18000)
        page.wait_for_timeout(2000)
        if "login" in page.url.lower():
            return False, "Naukri session not logged in; skipped profile refresh."

        edit_btn = page.locator("span.edit.icon, div.keySkills span.edit, a:has-text('Edit')").first
        if edit_btn.count() > 0 and edit_btn.is_visible():
            edit_btn.click(timeout=2500)
            page.wait_for_timeout(1500)
            save_btn = page.locator("button#saveKeySkills, button:has-text('Save')").first
            if save_btn.count() > 0 and save_btn.is_visible():
                save_btn.click(timeout=2500)
                page.wait_for_timeout(1500)
                ist = timezone(timedelta(hours=5, minutes=30))
                state_manager.data["last_modified_ist"] = datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")
                state_manager.save()
                return True, "Successfully refreshed Naukri profile key skills!"
        return False, "Naukri profile accessed; no interactive skill modal open."
    except Exception as exc:
        return False, f"Naukri profile refresh note: {str(exc)[:80]}"


def search_naukri_api_and_portal(page, freshness_days: int = 2, max_per_query: int = 8) -> List[Dict[str, Any]]:
    """
    Searches Naukri.com across Hyderabad, Bengaluru, Gurugram, and Chennai for
    Data Analyst, MIS Executive, Power BI, and Python/AI roles posted within 48 hours.
    Intercepts Naukri's internal JSON search API and falls back to DOM extraction.
    """
    discovered: List[Dict[str, Any]] = []
    seen_urls = set()

    keywords = state_manager.get_todays_search_keywords(count=4)
    locations = ["hyderabad", "bengaluru", "gurugram", "chennai"]

    from matcher import is_experience_below_4_years

    for kw in keywords:
        for loc in locations[:4]:
            kw_slug = slugify(kw)
            loc_slug = slugify(loc)
            search_url = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}?experience=3&jobAge={freshness_days}"
            api_captured_jobs: List[Dict[str, Any]] = []

            def intercept_response(response):
                if "jobapi/v3/search" in response.url or "jobapi/v4/search" in response.url:
                    try:
                        if response.status == 200:
                            data = response.json()
                            j_details = data.get("jobDetails", [])
                            if j_details:
                                api_captured_jobs.extend(j_details)
                    except Exception:
                        pass

            try:
                page.on("response", intercept_response)
                page.goto(search_url, wait_until="domcontentloaded", timeout=18000)
                page.wait_for_timeout(2000)

                if api_captured_jobs:
                    for aj in api_captured_jobs[:max_per_query]:
                        try:
                            title = (aj.get("title") or "").strip()
                            comp_dict = aj.get("companyDetail", {})
                            company = (
                                comp_dict.get("name", "").strip()
                                if isinstance(comp_dict, dict)
                                else (aj.get("companyName") or "Hiring Company")
                            )
                            jd_url = aj.get("jdURL") or aj.get("staticUrl") or ""
                            if jd_url and not jd_url.startswith("http"):
                                jd_url = "https://www.naukri.com" + jd_url
                            if not jd_url or jd_url in seen_urls:
                                continue

                            placeholders = aj.get("placeholders", [])
                            exp_str = "1-4.5 Yrs"
                            loc_str = loc.title()
                            for ph in placeholders:
                                if isinstance(ph, dict):
                                    if ph.get("type") == "experience":
                                        exp_str = ph.get("label", exp_str)
                                    elif ph.get("type") == "location":
                                        loc_str = ph.get("label", loc_str)

                            exp_ok, _ = is_experience_below_4_years(exp_str)
                            if not exp_ok:
                                continue

                            tags = aj.get("tagsAndSkills") or ""
                            if isinstance(tags, list):
                                tags = ", ".join(tags)
                            snippet = aj.get("jobDescription") or f"{title} at {company}. Skills: {tags}"
                            seen_urls.add(jd_url)
                            discovered.append(
                                {
                                    "portal": "Naukri",
                                    "title": title,
                                    "company": company,
                                    "location": loc_str,
                                    "experience": exp_str,
                                    "skills": tags or "Python, SQL, Power BI, Advanced Excel, MIS, ETL",
                                    "description": re.sub(r"<[^>]+>", " ", str(snippet))[:2500],
                                    "url": jd_url,
                                    "posted_date": aj.get("footerPlaceholderLabel") or "Within 48 hours",
                                }
                            )
                        except Exception:
                            continue

                # Also check DOM cards
                cards = page.locator("div.srp-jobtuple-wrapper, article.jobTuple, div.cust-job-tuple").all()
                for card in cards[:max_per_query]:
                    try:
                        title_loc = card.locator("a.title").first
                        comp_loc = card.locator("a.comp-name, a.subTitle").first
                        exp_loc = card.locator("span.expwdth, li.experience").first
                        loc_loc = card.locator("span.locWdth, li.location").first
                        tags_loc = card.locator("ul.tags-gt li, ul.tags li").all()

                        if title_loc.count() == 0:
                            continue
                        title = title_loc.inner_text().strip()
                        href = title_loc.get_attribute("href") or ""
                        if not href or href in seen_urls:
                            continue
                        exp_str = exp_loc.inner_text().strip() if exp_loc.count() > 0 else "1-4.5 Yrs"
                        exp_ok, _ = is_experience_below_4_years(exp_str)
                        if not exp_ok:
                            continue

                        seen_urls.add(href)
                        company = comp_loc.inner_text().strip() if comp_loc.count() > 0 else "Enterprise Employer"
                        loc_str = loc_loc.inner_text().strip() if loc_loc.count() > 0 else loc.title()
                        skills = ", ".join([t.inner_text().strip() for t in tags_loc[:8]])
                        discovered.append(
                            {
                                "portal": "Naukri",
                                "title": title,
                                "company": company,
                                "location": loc_str,
                                "experience": exp_str,
                                "skills": skills or "Python, SQL, Power BI, Advanced Excel, MIS, Reporting",
                                "description": f"{title} at {company} ({loc_str}). Key skills: {skills}",
                                "url": href,
                                "posted_date": "Within 48 hours",
                            }
                        )
                    except Exception:
                        continue
            except Exception:
                continue
            finally:
                try:
                    page.remove_listener("response", intercept_response)
                except Exception:
                    pass

    return discovered
