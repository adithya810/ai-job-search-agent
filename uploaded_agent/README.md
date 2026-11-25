# AI Job Search & Conditional Auto-Apply Agent (Adithya Krishna)

Implements the **6-Stage Job Search & Auto-Apply Agentic Architecture** (`../docs/agentic_workflow_architecture.png`):

1. **`agent_memory.py` (Stages 01 & 02)** — Parses Candidate Resume (`PDF` / `DOCX` / text) into structured skills & roles, reads Target Company Names & Career URLs from `Company name.xlsx`, and persists `agent_memory_state.json`.
2. **`scrapers.py` & `naukri_agent.py` & `firecrawl_scraper.py` (Stage 03)** — Executes the **Sequential 48h Search (`1 -> 2 -> 3 -> 4` Role-by-Role)** across `1. LinkedIn`, `2. Naukri.com`, `3. ZipRecruiter`, and `4. Company Career Pages` (`<= 48h`).
3. **`matcher.py` (Stage 04)** — Deduplicates cross-portal JDs, verifies `<= 48h` recency, scores JD vs Resume Skills (`0–100%`), and enforces the **`>= 80%` Filter Gate** (`< 80%` excluded from Excel).
4. **`auto_applier.py` (Stage 05)** — Selects the best role-tailored resume PDF from `resumes/` and checks whether an **Apply** button (`Easy Apply`, `1-Click Apply`, `Quick Apply`, or portal `Apply` + `Submit`) is available. Submits automatically when available; preserves the direct link when unavailable or verification-gated.
5. **`excel_reporter.py` (Stage 06)** — Generates `Applied_Companies_Tracker.xlsx` (`Matched_Jobs_Output`, `Target_Companies_CheckSheet`, `Resume_Skills_Analysis`), displaying **`APPLIED: <Portal, Resume & IST Timestamp>` instead of the Apply Link** whenever applied, and displaying the **clickable `Apply Link`** otherwise.
6. **`job_agent.py`** — Main end-to-end CLI orchestrator.

## Usage

```powershell
# 1. Install dependencies
python -m pip install -r requirements.txt

# 2. Save portal login sessions once in a visible browser
python job_agent.py --setup-login

# 3. Run the 6-stage Sequential Search, >=80% Gate & Conditional Auto-Apply
python job_agent.py --max-apply 25

# 4. Retry auto-apply on remaining link rows in Applied_Companies_Tracker.xlsx
python job_agent.py --continue --max-apply 25
```
