"""Export >=80% resume-matched Apply Queue and run a safe human-in-the-loop Playwright apply assistant."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .browser import detect_anti_bot_challenge, open_persistent_browser
from .resume_matcher import ResumeMatchResult, ResumeProfile

APPLY_QUEUE_CSV_COLUMNS = [
    "resume_match_pct",
    "jd_skill_coverage_pct",
    "experience_fit",
    "best_resume_track",
    "best_resume_name",
    "source",
    "title",
    "company",
    "location",
    "experience",
    "posted_date",
    "matched_skills",
    "missing_skills",
    "url",
    "best_resume_drive_url",
    "best_resume_local_path",
    "tailored_pitch",
]


def export_apply_queue(
    qualified: list[ResumeMatchResult],
    all_matches: list[ResumeMatchResult],
    profiles: list[ResumeProfile],
    output_dir: Path,
    *,
    min_match_pct: int = 80,
) -> tuple[Path, Path]:
    """Write `output/apply_queue.json` and `output/apply_queue.csv` for >=min_match_pct jobs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "apply_queue.json"
    csv_path = output_dir / "apply_queue.csv"

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_match_pct": min_match_pct,
        "total_evaluated": len(all_matches),
        "qualified_count": len(qualified),
        "resumes_used": [p.to_dict() for p in profiles],
        "apply_queue": [r.to_dict() for r in qualified],
        "near_matches_65_to_79": [
            r.to_dict() for r in all_matches if 65 <= r.resume_match_pct < min_match_pct
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=APPLY_QUEUE_CSV_COLUMNS)
        writer.writeheader()
        for r in qualified:
            writer.writerow(
                {
                    "resume_match_pct": r.resume_match_pct,
                    "jd_skill_coverage_pct": r.jd_skill_coverage_pct,
                    "experience_fit": r.experience_fit,
                    "best_resume_track": r.best_resume_track,
                    "best_resume_name": r.best_resume_name,
                    "source": r.source,
                    "title": r.title,
                    "company": r.company,
                    "location": r.location,
                    "experience": r.experience,
                    "posted_date": r.posted_date,
                    "matched_skills": ", ".join(r.matched_skills),
                    "missing_skills": ", ".join(r.missing_skills),
                    "url": r.url,
                    "best_resume_drive_url": r.best_resume_drive_url,
                    "best_resume_local_path": r.best_resume_local_path,
                    "tailored_pitch": r.tailored_pitch,
                }
            )

    return json_path, csv_path


def run_assisted_apply(
    queue_path: Path,
    profile_dir: Path,
    *,
    limit: int = 10,
) -> int:
    """Open each >=80% matched job in a visible local Chromium session for human-reviewed submission.

    Safety rules:
    - Never submits applications unattended or clicks final Submit without human confirmation.
    - Never bypasses CAPTCHAs, 2FA, or login walls.
    - Prints the paired resume path and tailored cover note for fast review and upload.
    """
    if not queue_path.exists():
        print(f"No apply queue found at {queue_path}. Run `python3 -m job_agent match-resumes` first.")
        return 1

    data = json.loads(queue_path.read_text(encoding="utf-8"))
    queue = data.get("apply_queue", [])[:limit]
    if not queue:
        print("Apply queue is currently empty (0 jobs >= min_match_pct).")
        return 0

    applied_log_path = queue_path.parent / "applied_history.json"
    applied_fps: set[str] = set()
    if applied_log_path.exists():
        try:
            applied_fps = set(json.loads(applied_log_path.read_text(encoding="utf-8")).get("applied", []))
        except Exception:
            applied_fps = set()

    pending = [item for item in queue if item.get("fingerprint") not in applied_fps]
    if not pending:
        print("All jobs in the current apply queue have already been marked applied!")
        return 0

    print(f"\n=== Assisted Apply Mode ({len(pending)} jobs >= {data.get('min_match_pct', 80)}% match) ===")
    print("Each job will open in your visible local Chromium session so you can review & click Submit.\n")

    with open_persistent_browser(profile_dir, headless=False) as context:
        page = context.pages[0] if context.pages else context.new_page()
        for idx, item in enumerate(pending, start=1):
            print("=" * 72)
            print(f"[{idx}/{len(pending)}] {item['resume_match_pct']}% Match — {item['title']} @ {item['company']}")
            print(f"Location       : {item['location']} | Exp: {item['experience']} | Posted: {item['posted_date']}")
            print(f"Best Resume    : {item['best_resume_name']}")
            print(f"Local Resume   : {item['best_resume_local_path']}")
            print(f"Matched Skills : {', '.join(item.get('matched_skills', []))}")
            if item.get("missing_skills"):
                print(f"Skill Gaps     : {', '.join(item.get('missing_skills', []))}")
            print(f"\nTailored Pitch (copy/paste if asked):\n  {item['tailored_pitch']}\n")

            page.goto(item["url"], wait_until="domcontentloaded", timeout=35000)
            challenge = detect_anti_bot_challenge(page.content(), page.url)
            if challenge:
                print(f"Notice: {challenge}. Complete verification directly in the browser window.")

            answer = input(
                ">>> Review & submit in the browser, then type [a]pplied, [s]kip, or [q]uit: "
            ).strip().lower()
            if answer == "a":
                applied_fps.add(item["fingerprint"])
                applied_log_path.write_text(
                    json.dumps({"applied": sorted(applied_fps)}, indent=2),
                    encoding="utf-8",
                )
                print("Recorded as APPLIED.")
            elif answer == "q":
                break
            else:
                print("Skipped.")

    return 0
