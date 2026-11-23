"""Exporters for CSV, JSON, and a self-contained offline interactive HTML dashboard."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .models import JobListing, SiteRunStatus

CSV_COLUMNS = [
    "match_score",
    "is_new",
    "source",
    "title",
    "company",
    "location",
    "work_mode",
    "experience",
    "salary",
    "posted_date",
    "matched_core_skills",
    "missing_core_skills",
    "matched_bonus_skills",
    "query_matched",
    "url",
]


def export_csv(jobs: list[JobListing], output_path: Path) -> Path:
    """Write matched jobs to a UTF-8 CSV ready for Excel or Google Sheets."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for job in jobs:
            writer.writerow(
                {
                    "match_score": job.match_score,
                    "is_new": "Yes" if job.is_new else "No",
                    "source": job.source,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "work_mode": job.work_mode,
                    "experience": job.experience,
                    "salary": job.salary,
                    "posted_date": job.posted_date,
                    "matched_core_skills": ", ".join(job.matched_core_skills),
                    "missing_core_skills": ", ".join(job.missing_core_skills),
                    "matched_bonus_skills": ", ".join(job.matched_bonus_skills),
                    "query_matched": job.query_matched,
                    "url": job.url,
                }
            )
    return output_path


def build_report_payload(
    jobs: list[JobListing],
    statuses: list[SiteRunStatus],
    skill_summary: dict[str, Any],
    *,
    mode: str,
    locations: list[str],
    queries: list[str],
    filter_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the canonical JSON report payload."""
    avg_score = round(sum(j.match_score for j in jobs) / len(jobs), 1) if jobs else 0.0
    by_source: dict[str, int] = {
        "linkedin": 0,
        "naukri": 0,
        "ziprecruiter": 0,
    }
    for j in jobs:
        by_source[j.source] = by_source.get(j.source, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "locations": locations,
        "queries": queries,
        "filters": filter_stats or {},
        "summary": {
            "total_jobs": len(jobs),
            "new_jobs": sum(1 for j in jobs if j.is_new),
            "avg_match_score": avg_score,
            "high_match_jobs": sum(1 for j in jobs if j.match_score >= 60),
            "by_source": by_source,
        },
        "site_statuses": [s.to_dict() for s in statuses],
        "skill_demand": skill_summary,
        "jobs": [j.to_dict() for j in jobs],
    }


def export_json(payload: dict[str, Any], output_path: Path) -> Path:
    """Write the structured JSON report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def render_offline_dashboard_html(payload: dict[str, Any]) -> str:
    """Render a zero-dependency offline interactive HTML dashboard for local browsers."""
    safe_json = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Data Analyst Job Search Agent — India Dashboard</title>
  <style>
    :root {{
      --bg: #0f172a;
      --surface: #1e293b;
      --surface-2: #263348;
      --border: #334155;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --green: #34d399;
      --amber: #fbbf24;
      --rose: #fb7185;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 24px 20px 48px; }}
    header {{
      display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end;
      gap: 12px; padding-bottom: 18px; border-bottom: 1px solid var(--border);
    }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: -0.02em; }}
    .sub {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
    .kpis {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px; margin: 20px 0;
    }}
    .card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 14px 16px;
    }}
    .kpi-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
    .kpi-val {{ font-size: 26px; font-weight: 700; margin-top: 4px; }}
    .statuses {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; margin-bottom: 18px; }}
    .status-pill {{
      display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px;
      border-radius: 999px; text-transform: uppercase;
    }}
    .st-ok {{ background: rgba(52, 211, 153, 0.16); color: var(--green); }}
    .st-warn {{ background: rgba(251, 191, 36, 0.16); color: var(--amber); }}
    .st-err {{ background: rgba(251, 113, 133, 0.16); color: var(--rose); }}
    .controls {{
      display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 14px; margin-bottom: 16px;
    }}
    input, select, button {{
      background: var(--bg); color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 8px 10px; font-size: 13px;
    }}
    input[type="search"] {{ flex: 1; min-width: 220px; }}
    button {{ cursor: pointer; font-weight: 600; }}
    button.primary {{ background: var(--accent); color: #082f49; border-color: transparent; }}
    .skills-bar {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }}
    .skill-chip {{
      font-size: 12px; padding: 4px 10px; border-radius: 999px;
      border: 1px solid var(--border); background: var(--surface); cursor: pointer;
    }}
    .skill-chip.active {{ background: var(--accent); color: #082f49; border-color: var(--accent); font-weight: 600; }}
    .job-list {{ display: grid; gap: 12px; }}
    .job-card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 16px; display: grid;
      grid-template-columns: 1fr auto; gap: 12px;
    }}
    .job-title {{ font-size: 17px; font-weight: 700; color: var(--accent); text-decoration: none; }}
    .job-title:hover {{ text-decoration: underline; }}
    .meta {{ color: var(--muted); font-size: 13px; margin: 4px 0 8px; display: flex; flex-wrap: wrap; gap: 10px; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    .tag {{ font-size: 11px; padding: 2px 8px; border-radius: 6px; background: var(--surface-2); border: 1px solid var(--border); }}
    .tag.hit {{ border-color: rgba(52, 211, 153, 0.5); color: var(--green); }}
    .tag.miss {{ color: var(--muted); opacity: 0.7; }}
    .score-box {{
      min-width: 84px; text-align: center; padding: 10px; border-radius: 10px;
      background: var(--bg); border: 1px solid var(--border); align-self: start;
    }}
    .score-num {{ font-size: 24px; font-weight: 800; }}
    .desc {{ color: var(--muted); font-size: 13px; margin-top: 8px; max-height: 74px; overflow: hidden; }}
    .actions {{ display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }}
    .btn-sm {{ font-size: 12px; padding: 5px 10px; }}
    .saved {{ border-color: var(--green); color: var(--green); }}
    .empty {{ text-align: center; padding: 36px; color: var(--muted); }}
    @media (max-width: 720px) {{
      .job-card {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>Data Analyst Job Search Agent — India</h1>
        <div class="sub" id="meta-line"></div>
      </div>
      <div style="display:flex; gap:8px;">
        <button id="export-csv-btn" class="primary">Download Filtered CSV</button>
      </div>
    </header>

    <section class="kpis" id="kpi-grid"></section>
    <section class="statuses" id="site-statuses"></section>

    <section class="controls">
      <input id="q" type="search" placeholder="Search title, company, city, or description..." />
      <select id="src-filter">
        <option value="all">All Sources</option>
        <option value="linkedin">LinkedIn</option>
        <option value="naukri">Naukri</option>
        <option value="ziprecruiter">ZipRecruiter</option>
      </select>
      <select id="city-filter"><option value="all">All Locations</option></select>
      <select id="status-filter">
        <option value="all">All Jobs</option>
        <option value="saved">Bookmarked Only</option>
        <option value="applied">Applied Only</option>
        <option value="new">New This Run</option>
      </select>
      <label style="font-size:12px; color:var(--muted); display:flex; align-items:center; gap:6px;">
        Min Score: <strong id="min-score-val">0</strong>
        <input id="min-score" type="range" min="0" max="90" step="5" value="0" />
      </label>
      <select id="sort-by">
        <option value="score">Sort: Match Score</option>
        <option value="date">Sort: Posted Date</option>
        <option value="company">Sort: Company A-Z</option>
      </select>
    </section>

    <div class="skills-bar" id="skills-bar"></div>
    <div id="count-line" class="sub" style="margin-bottom:10px;"></div>
    <section class="job-list" id="job-list"></section>
  </div>

  <script>
    const DATA = {safe_json};
    const STORAGE_KEY = "da_job_agent_tracker_v1";
    const tracker = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{"saved":{{}},"applied":{{}}}}');
    let activeSkill = "";

    const esc = (s) => String(s || "").replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));

    function saveTracker() {{
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tracker));
    }}

    function scoreColor(score) {{
      if (score >= 70) return "var(--green)";
      if (score >= 45) return "var(--amber)";
      return "var(--muted)";
    }}

    function renderHeader() {{
      document.getElementById("meta-line").textContent =
        `Generated ${{DATA.generated_at}} | Mode: ${{DATA.mode}} | Locations: ${{(DATA.locations || []).join(", ")}}`;

      const s = DATA.summary || {{}};
      const kpis = [
        ["Total Unique Jobs", s.total_jobs || 0],
        ["New This Run", s.new_jobs || 0],
        ["Avg Match Score", `${{s.avg_match_score || 0}} / 100`],
        ["Strong Matches (60+)", s.high_match_jobs || 0],
      ];
      document.getElementById("kpi-grid").innerHTML = kpis.map(([label, val]) => `
        <div class="card">
          <div class="kpi-label">${{esc(label)}}</div>
          <div class="kpi-val">${{esc(val)}}</div>
        </div>
      `).join("");

      document.getElementById("site-statuses").innerHTML = (DATA.site_statuses || []).map(st => {{
        const cls = st.status === "ok" ? "st-ok" : (st.status === "partial" || st.status === "requires_browser_session" ? "st-warn" : "st-err");
        return `
          <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
              <strong style="text-transform:capitalize;">${{esc(st.site)}} (${{esc(st.mode_used)}})</strong>
              <span class="status-pill ${{cls}}">${{esc(st.status)}}</span>
            </div>
            <div style="font-size:12px; color:var(--muted);">${{esc(st.message)}}</div>
          </div>
        `;
      }}).join("");

      const cities = Array.from(new Set((DATA.jobs || []).map(j => (j.location || "").split(",")[0].trim()).filter(Boolean))).sort();
      const citySel = document.getElementById("city-filter");
      cities.forEach(c => {{
        const opt = document.createElement("option");
        opt.value = c.toLowerCase();
        opt.textContent = c;
        citySel.appendChild(opt);
      }});

      const coreCounts = (DATA.skill_demand && DATA.skill_demand.core) || {{}};
      const bar = document.getElementById("skills-bar");
      const allSkills = ["SQL", "Python", "Excel", "Power BI", "Tableau", ...Object.keys(coreCounts)];
      const uniqueSkills = Array.from(new Set(allSkills));
      bar.innerHTML = `<button class="skill-chip active" data-skill="">All Core Skills</button>` +
        uniqueSkills.map(sk => `<button class="skill-chip" data-skill="${{esc(sk)}}">${{esc(sk)}} (${{coreCounts[sk] || 0}})</button>`).join("");
      bar.querySelectorAll(".skill-chip").forEach(btn => {{
        btn.addEventListener("click", () => {{
          activeSkill = btn.dataset.skill;
          bar.querySelectorAll(".skill-chip").forEach(b => b.classList.toggle("active", b === btn));
          renderJobs();
        }});
      }});
    }}

    function getFilteredJobs() {{
      const q = document.getElementById("q").value.trim().toLowerCase();
      const src = document.getElementById("src-filter").value;
      const city = document.getElementById("city-filter").value;
      const st = document.getElementById("status-filter").value;
      const minScore = Number(document.getElementById("min-score").value || 0);
      const sortBy = document.getElementById("sort-by").value;

      let list = (DATA.jobs || []).filter(j => {{
        if (src !== "all" && j.source !== src) return false;
        if (city !== "all" && !(j.location || "").toLowerCase().includes(city)) return false;
        if (j.match_score < minScore) return false;
        if (activeSkill && !(j.matched_core_skills || []).includes(activeSkill)) return false;
        if (st === "saved" && !tracker.saved[j.fingerprint]) return false;
        if (st === "applied" && !tracker.applied[j.fingerprint]) return false;
        if (st === "new" && !j.is_new) return false;
        if (q) {{
          const hay = `${{j.title}} ${{j.company}} ${{j.location}} ${{j.description}} ${{(j.matched_core_skills || []).join(" ")}}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }}
        return true;
      }});

      if (sortBy === "score") list.sort((a, b) => b.match_score - a.match_score);
      else if (sortBy === "date") list.sort((a, b) => String(b.posted_date || "").localeCompare(String(a.posted_date || "")));
      else if (sortBy === "company") list.sort((a, b) => String(a.company || "").localeCompare(String(b.company || "")));
      return list;
    }}

    function renderJobs() {{
      const list = getFilteredJobs();
      document.getElementById("count-line").textContent = `Showing ${{list.length}} of ${{(DATA.jobs || []).length}} unique jobs`;
      const container = document.getElementById("job-list");
      if (!list.length) {{
        container.innerHTML = `<div class="card empty">No jobs match the current filters. Try lowering Min Score or clearing filters.</div>`;
        return;
      }}

      container.innerHTML = list.map(j => {{
        const isSaved = !!tracker.saved[j.fingerprint];
        const isApplied = !!tracker.applied[j.fingerprint];
        const hitTags = (j.matched_core_skills || []).map(s => `<span class="tag hit">+ ${{esc(s)}}</span>`).join("");
        const bonusTags = (j.matched_bonus_skills || []).map(s => `<span class="tag">${{esc(s)}}</span>`).join("");
        const missTags = (j.missing_core_skills || []).map(s => `<span class="tag miss">- ${{esc(s)}}</span>`).join("");
        const snippet = j.description ? esc(j.description.slice(0, 260)) + (j.description.length > 260 ? "..." : "") : "Open posting to view full description.";
        return `
          <article class="job-card">
            <div>
              <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                <a class="job-title" href="${{esc(j.url)}}" target="_blank" rel="noopener noreferrer">${{esc(j.title)}}</a>
                <span class="tag" style="text-transform:uppercase;">${{esc(j.source)}}</span>
                ${{j.is_new ? '<span class="tag hit">NEW</span>' : ''}}
                ${{j.work_mode ? `<span class="tag">${{esc(j.work_mode)}}</span>` : ''}}
              </div>
              <div class="meta">
                <strong>${{esc(j.company)}}</strong>
                <span>${{esc(j.location)}}</span>
                ${{j.experience ? `<span>Exp: ${{esc(j.experience)}}</span>` : ''}}
                ${{j.salary ? `<span>Salary: ${{esc(j.salary)}}</span>` : ''}}
                ${{j.posted_date ? `<span>Posted: ${{esc(j.posted_date)}}</span>` : ''}}
              </div>
              <div class="desc">${{snippet}}</div>
              <div class="tags">${{hitTags}}${{bonusTags}}${{missTags}}</div>
              <div class="actions">
                <a href="${{esc(j.url)}}" target="_blank" rel="noopener noreferrer"><button class="btn-sm primary">Open Job</button></a>
                <button class="btn-sm ${{isSaved ? 'saved' : ''}}" data-act="save" data-fp="${{esc(j.fingerprint)}}">${{isSaved ? 'Bookmarked' : 'Bookmark'}}</button>
                <button class="btn-sm ${{isApplied ? 'saved' : ''}}" data-act="apply" data-fp="${{esc(j.fingerprint)}}">${{isApplied ? 'Applied' : 'Mark Applied'}}</button>
              </div>
            </div>
            <div class="score-box">
              <div style="font-size:11px; color:var(--muted); text-transform:uppercase;">Match</div>
              <div class="score-num" style="color:${{scoreColor(j.match_score)}}">${{j.match_score}}</div>
              <div style="font-size:11px; color:var(--muted);">/ 100</div>
            </div>
          </article>
        `;
      }}).join("");

      container.querySelectorAll("button[data-act]").forEach(btn => {{
        btn.addEventListener("click", () => {{
          const fp = btn.dataset.fp;
          if (btn.dataset.act === "save") tracker.saved[fp] = !tracker.saved[fp];
          if (btn.dataset.act === "apply") tracker.applied[fp] = !tracker.applied[fp];
          saveTracker();
          renderJobs();
        }});
      }});
    }}

    document.getElementById("export-csv-btn").addEventListener("click", () => {{
      const rows = getFilteredJobs();
      const cols = ["match_score","source","title","company","location","work_mode","experience","posted_date","url"];
      const csv = [cols.join(","), ...rows.map(r => cols.map(c => `"${{String(r[c] ?? "").replace(/"/g, '""')}}"`).join(","))].join("\\n");
      const blob = new Blob([csv], {{ type: "text/csv;charset=utf-8;" }});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "filtered_data_analyst_jobs.csv";
      a.click();
    }});

    ["q","src-filter","city-filter","status-filter","sort-by"].forEach(id => {{
      document.getElementById(id).addEventListener("input", renderJobs);
      document.getElementById(id).addEventListener("change", renderJobs);
    }});
    document.getElementById("min-score").addEventListener("input", (e) => {{
      document.getElementById("min-score-val").textContent = e.target.value;
      renderJobs();
    }});

    renderHeader();
    renderJobs();
  </script>
</body>
</html>
"""


def export_dashboard_html(payload: dict[str, Any], output_path: Path) -> Path:
    """Write the offline interactive HTML dashboard to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_offline_dashboard_html(payload), encoding="utf-8")
    return output_path
