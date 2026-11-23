# AI Job Search & Auto-Apply Agent (Adithya Krishna)

A complete, modular Python job-search, web-scraping, resume-matching, and auto-apply agent built for **Adithya Krishna** (`AI/ML Engineer | Python | Machine Learning | Deep Learning | Generative AI | Data Analyst | MIS Executive`).

## Project Files
- `config.py` — Candidate profile, full resume text, categorized skills, target roles, locations (`Hyderabad`, `Bengaluru`, `Gurugram`, `Chennai`), API keys (`Exa` & `Firecrawl`), and official company career portal configurations.
- `resume_builder.py` — Builds ATS-ready `Adithya_Krishna_Resume.pdf`, `Adithya_Krishna_Resume.docx`, role-specific resume variants in `resumes/`, and `Company name.xlsx`.
- `matcher.py` — Deterministic resume skill matcher (`>= 80%` threshold) that extracts exact matching skills from Adithya's resume (`Python`, `Pandas`, `NumPy`, `Scikit-learn`, `TensorFlow`, `PyTorch`, `spaCy`, `Keras`, `Deep Learning`, `Generative AI & LLMs`, `SQL`, `SQL Server / SSMS / SSIS`, `ETL Pipelines`, `Azure Databricks`, `PySpark`, `Power BI`, `DAX`, `Power Query`, `Power Automate`, `RLS`, `Advanced Excel`, `MIS & KPI Reporting`, `Data Validation & Reconciliation`, `Root Cause Analysis`) and identifies any missing/bonus skills.
- `scrapers.py` — Deterministic Python web scrapers (`requests`, `BeautifulSoup`, `Playwright`) for LinkedIn (Guest API & Easy Apply), Naukri, Indeed (Easily Apply), ZipRecruiter, Glassdoor, and Official Company Career Portals from `Company name.xlsx`.
- `naukri_agent.py` — Naukri API interceptor (`jobapi/v3/search` & `v4/search`), DOM fallback scraper, and daily keyword rotator.
- `firecrawl_scraper.py` — Web search and page enrichment using `exa-py` (`Exa`), `firecrawl-py` (`Firecrawl`), and MCP-discovered jobs (`mcp_discovered_jobs.json`).
- `auto_applier.py` — Automated browser application handler across LinkedIn Easy Apply, Naukri 1-Click Apply, Indeed Easy Apply, ZipRecruiter Quick Apply, Glassdoor Easy Apply, and Official ATS portals.
- `excel_reporter.py` — Generates `Applied_Companies_Tracker.xlsx` with 3 tabs (`Applied_Jobs_Tracker`, `Target_Companies_CheckSheet`, and `Resume_Skills_Analysis`).
- `job_agent.py` — Main orchestrator CLI entrypoint.

## How Another AI Model (e.g. Gemini 4 Hydrogen) or User Can Run This Project

```powershell
# 1. Install dependencies (already installed in C:\Python315)
& "C:\Python315\python.exe" -m pip install -r "E:\job search agent\requirements.txt"

# 2. Run the full Job Search, Skill Matcher & Auto-Apply Agent (up to 25 applications)
& "C:\Python315\python.exe" "E:\job search agent\job_agent.py" --max-apply 25

# 3. Continue applying to queued jobs from Applied_Companies_Tracker.xlsx
& "C:\Python315\python.exe" "E:\job search agent\job_agent.py" --continue --max-apply 25

# 4. Open interactive browser session setup (to log in to portals once)
& "C:\Python315\python.exe" "E:\job search agent\job_agent.py" --setup-login
```
