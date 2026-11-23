# Data Analyst Job Search Agent (India)

A hybrid **Data Analyst job search agent** targeting **LinkedIn**, **Naukri**, **ZipRecruiter**, plus **Exa**, **Firecrawl**, and **MCP (Model Context Protocol)** web-search connectors — configured by default for **India hubs** (`Bengaluru`, `Hyderabad`, `Pune`, `All-India`), **experience > 3 years (`3+` / `3–5+` yrs)**, and **freshness <= 48 hours**.

## Default Search Filters

Configured in `config.json` (and overridable via CLI flags or MCP tool arguments):
- **Experience (`min_experience_years: 3`, `strict_experience_filter: true`):** Keeps postings requiring **3+ / >3 years** of experience (e.g., `3–5 years`, `4+ years`, `5–8 years`) and excludes fresher/junior/0–2/1–3/2–4 year listings.
- **Freshness (`max_age_hours: 48`, `strict_freshness_filter: true`):** Applied both **natively at query time** (`f_TPR=r172800` on LinkedIn, `jobAge=2&experience=3` on Naukri, `days=2` on ZipRecruiter, `startPublishedDate` on Exa, `tbs` on Firecrawl) and **strictly post-scrape** via `job_agent/filters.py`.

## Security & Authentication Model

- **No password storage or email scraping:** `config.json` only holds an optional `email_hint` (`adithyakrishna810@gmail.com`) to pre-fill the email input during manual interactive login.
- **Persistent local browser session:** `python3 -m job_agent login --site all` opens a **visible Chromium window** backed by `.browser_profile/` (gitignored) so you sign in once (handling password, 2FA, and CAPTCHAs directly) and reuse the session locally.
- **API keys via `.env`:** Copy `.env.example` to `.env` (gitignored) and add `EXA_API_KEY` and/or `FIRECRAWL_API_KEY`.

## Quick Start

### 1. Run Live Search (3+ Years Exp, <= 48h Freshness)

```bash
# Public LinkedIn + API connectors (Exa & Firecrawl activate automatically when keys are in .env)
python3 -m job_agent search --mode public --enrich-details

# Override filters from CLI if needed
python3 -m job_agent search --mode public --min-exp 3 --max-age-hours 48
```

### 2. Enable Exa & Firecrawl Webpage Connectors

```bash
cp .env.example .env
# Edit .env and set:
#   EXA_API_KEY=...
#   FIRECRAWL_API_KEY=fc-...

# Search job webpages via Exa and Firecrawl
python3 -m job_agent search --sites linkedin,exa,firecrawl --min-exp 3 --max-age-hours 48

# Scrape and score any individual job webpage URL directly (uses Firecrawl -> Exa -> HTTP)
python3 -m job_agent scrape "https://in.linkedin.com/jobs/view/..."
```

### 3. MCP Integration (Both Server & Client)

#### A) Use this agent as an MCP Server in Claude Desktop, Cursor, Windsurf, or Antigravity
Drop [mcp.json](./mcp.json) into your MCP client config (it wires `job-search-agent`, `exa-mcp-server`, and `firecrawl-mcp` together), or run the stdio server directly:

```bash
python3 -m job_agent mcp-serve

# Verify tools exposed over stdio JSON-RPC
python3 -m job_agent mcp-list-tools --server self
```

Exposed MCP tools:
- `search_jobs` — Multi-provider search (`linkedin`, `naukri`, `ziprecruiter`, `exa`, `firecrawl`, `mcp`) with `>3y` & `<=48h` filtering + CSV/JSON/HTML export
- `search_web_exa` — Neural web search via Exa connector
- `search_web_firecrawl` — Web search + clean Markdown extraction via Firecrawl connector
- `scrape_job_webpage` — Scrape & skill-score any job URL
- `get_saved_jobs` — Query saved `output/jobs.json` by `min_score`, `city`, `source`, or `skill`

#### B) Call External MCP Servers (`exa-mcp-server`, `firecrawl-mcp`) from this Agent
In `config.json`, set `"enabled": true` under `mcp_servers.exa` or `mcp_servers.firecrawl`, export your API key in `.env`, and run:

```bash
python3 -m job_agent search --sites mcp
```

### 4. Enable Naukri & ZipRecruiter via Persistent Browser Session

```bash
pip install -r requirements.txt
python3 -m playwright install chromium

# Sign in manually once in a visible browser (pre-fills adithyakrishna810@gmail.com)
python3 -m job_agent login --site all

# Run hybrid mode across all boards & connectors
python3 -m job_agent search --mode hybrid --headed
```

## Outputs (`output/`)

| File | Description |
|---|---|
| `output/jobs.csv` | Excel / Google Sheets–ready table with match score, experience, posted date, matched & missing skills, and URLs |
| `output/jobs.json` | Structured dataset including active filter stats, per-site statuses, and skill demand counts |
| `output/dashboard.html` | Self-contained offline interactive HTML dashboard |
| `output/seen_jobs.json` | Deduplication fingerprint history |

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```
