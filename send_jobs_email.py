#!/usr/bin/env python3
"""Send Applied_Companies_Tracker.xlsx via Gmail SMTP using environment variables.

Environment variables:
  - GMAIL_APP_PASSWORD (required): 16-character Google App Password (with 2-Step Verification enabled)
  - GMAIL_SENDER (optional): Sender Gmail address (default: adithyakrishna810@gmail.com)
  - NOTIFY_EMAIL / TO_EMAIL (optional): Recipient email address (default: adithyakrishna810@gmail.com)
  - SMTP_HOST (optional): SMTP server hostname (default: smtp.gmail.com)
  - SMTP_PORT (optional): SMTP SSL port (default: 465)

Usage:
  python3 send_jobs_email.py
  python3 send_jobs_email.py --file uploaded_agent/Applied_Companies_Tracker.xlsx
  python3 send_jobs_email.py --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
import sys
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    from job_agent.env import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_EMAIL = "adithyakrishna810@gmail.com"
DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 465
XLSX_MIME_SUBTYPE = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def get_ist_timestamp() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")


def resolve_tracker_path(explicit_path: Path | None = None) -> Path:
    """Locate Applied_Companies_Tracker.xlsx (or fallback Matched_Jobs_Output.xlsx)."""
    if explicit_path is not None:
        return explicit_path

    candidates = [
        PROJECT_ROOT / "Applied_Companies_Tracker.xlsx",
        PROJECT_ROOT / "uploaded_agent" / "Applied_Companies_Tracker.xlsx",
        PROJECT_ROOT / "output" / "Matched_Jobs_Output.xlsx",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def summarize_excel_tracker(excel_path: Path) -> dict[str, Any]:
    """Extract lightweight counts (total rows, applied vs apply-link) from the Excel workbook."""
    summary: dict[str, Any] = {
        "sheet_name": "",
        "total_jobs": 0,
        "applied_count": 0,
        "link_only_count": 0,
        "highlights": [],
    }
    try:
        import openpyxl

        wb = openpyxl.load_workbook(excel_path, data_only=True)
        if "Matched_Jobs_Output" in wb.sheetnames:
            ws = wb["Matched_Jobs_Output"]
            summary["sheet_name"] = "Matched_Jobs_Output"
            for r in range(2, ws.max_row + 1):
                comp = str(ws.cell(r, 1).value or "").splitlines()[0].strip()
                role = str(ws.cell(r, 4).value or "").splitlines()[0].strip()
                action = str(ws.cell(r, 5).value or "").strip()
                if not comp and not role:
                    continue
                summary["total_jobs"] += 1
                is_applied = "APPLIED:" in action
                if is_applied:
                    summary["applied_count"] += 1
                else:
                    summary["link_only_count"] += 1
                if len(summary["highlights"]) < 5:
                    tag = "APPLIED" if is_applied else "APPLY LINK"
                    summary["highlights"].append(f"- [{tag}] {comp} — {role}")
        elif "Applied_Jobs_Tracker" in wb.sheetnames:
            ws = wb["Applied_Jobs_Tracker"]
            summary["sheet_name"] = "Applied_Jobs_Tracker"
            for r in range(2, ws.max_row + 1):
                comp = str(ws.cell(r, 3).value or "").strip()
                role = str(ws.cell(r, 5).value or "").strip()
                status = str(ws.cell(r, 11).value or "").strip()
                if not comp and not role:
                    continue
                summary["total_jobs"] += 1
                if status.lower().startswith("applied") or "already applied" in status.lower():
                    summary["applied_count"] += 1
                else:
                    summary["link_only_count"] += 1
        wb.close()
    except Exception:
        pass
    return summary


def build_jobs_email_message(
    *,
    sender_email: str,
    recipient_email: str,
    excel_path: Path,
    subject: str | None = None,
) -> EmailMessage:
    """Construct the EmailMessage with summary body and attached Excel workbook."""
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel tracker not found: {excel_path}")

    now_ist = get_ist_timestamp()
    stats = summarize_excel_tracker(excel_path)
    resolved_subject = subject or (
        f"AI Job Search Tracker ({stats['total_jobs']} Matches | "
        f"{stats['applied_count']} Applied) — {now_ist}"
    )

    body_lines = [
        "Hi Adithya,",
        "",
        f"Attached is your latest Job Search & Auto-Apply Excel tracker ({excel_path.name}), generated on {now_ist}.",
        "",
        "Summary:",
        f"- Sheet: {stats['sheet_name'] or 'Excel Tracker'}",
        f"- Total Qualified Jobs (>=80% Match): {stats['total_jobs']}",
        f"- Auto-Applied (Applied Result shown in sheet): {stats['applied_count']}",
        f"- Direct Apply Link Preserved: {stats['link_only_count']}",
    ]
    if stats["highlights"]:
        body_lines.extend(["", "Top Entries:"])
        body_lines.extend(stats["highlights"])
    body_lines.extend(["", "— Autonomous AI Job Search Agent"])

    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = resolved_subject
    msg.set_content("\n".join(body_lines))

    excel_bytes = excel_path.read_bytes()
    msg.add_attachment(
        excel_bytes,
        maintype="application",
        subtype=XLSX_MIME_SUBTYPE,
        filename=excel_path.name,
    )
    return msg


def send_jobs_email(
    *,
    excel_path: Path | None = None,
    recipient_email: str | None = None,
    sender_email: str | None = None,
    subject: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Load credentials from environment / .env and send Applied_Companies_Tracker.xlsx via Gmail SMTP."""
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / "uploaded_agent" / ".env")

    to_addr = (
        recipient_email
        or os.environ.get("NOTIFY_EMAIL")
        or os.environ.get("TO_EMAIL")
        or DEFAULT_EMAIL
    ).strip()
    from_addr = (
        sender_email
        or os.environ.get("GMAIL_SENDER")
        or os.environ.get("SMTP_USER")
        or to_addr
    ).strip()
    app_password = (
        os.environ.get("GMAIL_APP_PASSWORD")
        or os.environ.get("SMTP_PASS")
        or ""
    ).strip()
    smtp_host = (os.environ.get("SMTP_HOST") or DEFAULT_SMTP_HOST).strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or str(DEFAULT_SMTP_PORT))

    tracker_path = resolve_tracker_path(excel_path)
    msg = build_jobs_email_message(
        sender_email=from_addr,
        recipient_email=to_addr,
        excel_path=tracker_path,
        subject=subject,
    )

    if dry_run:
        return {
            "sent": False,
            "dry_run": True,
            "from": from_addr,
            "to": to_addr,
            "subject": msg["Subject"],
            "attachment": str(tracker_path),
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
        }

    if not app_password:
        raise RuntimeError(
            "Missing GMAIL_APP_PASSWORD environment variable. "
            "Set GMAIL_APP_PASSWORD in your environment or .env file "
            "(create a 16-character Google App Password at https://myaccount.google.com/apppasswords)."
        )

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(from_addr, app_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(from_addr, app_password)
            server.send_message(msg)

    return {
        "sent": True,
        "dry_run": False,
        "from": from_addr,
        "to": to_addr,
        "subject": msg["Subject"],
        "attachment": str(tracker_path),
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Email Applied_Companies_Tracker.xlsx via Gmail SMTP using GMAIL_APP_PASSWORD."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to Excel file (default: auto-detect Applied_Companies_Tracker.xlsx or output/Matched_Jobs_Output.xlsx)",
    )
    parser.add_argument(
        "--to",
        type=str,
        default=None,
        help=f"Recipient email address (default: NOTIFY_EMAIL env or {DEFAULT_EMAIL})",
    )
    parser.add_argument(
        "--sender",
        type=str,
        default=None,
        help=f"Sender Gmail address (default: GMAIL_SENDER env or {DEFAULT_EMAIL})",
    )
    parser.add_argument("--subject", type=str, default=None, help="Optional custom email subject")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate attachment and compose email without connecting to SMTP",
    )
    parser.add_argument(
        "--if-exists",
        action="store_true",
        help="Exit 0 silently with a notice if no Excel tracker file exists yet (for scheduled runs)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    resolved_path = resolve_tracker_path(args.file)
    if args.if_exists and not resolved_path.exists():
        print(f"[send_jobs_email] No Excel tracker found at '{resolved_path}'; skipping email.")
        return 0

    try:
        result = send_jobs_email(
            excel_path=resolved_path,
            recipient_email=args.to,
            sender_email=args.sender,
            subject=args.subject,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"[send_jobs_email] Error: {exc}", file=sys.stderr)
        return 1

    if result["dry_run"]:
        print(
            f"[DRY RUN] Ready to send '{result['attachment']}' "
            f"from {result['from']} to {result['to']} | Subject: {result['subject']}"
        )
    else:
        print(
            f"[OK] Emailed '{result['attachment']}' "
            f"from {result['from']} to {result['to']} via {result['smtp_host']}:{result['smtp_port']}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
