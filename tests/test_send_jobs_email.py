"""Unit tests for send_jobs_email.py (attachment MIME, summary body, SMTP SSL mock, missing password)."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import openpyxl

import send_jobs_email


class TestSendJobsEmail(unittest.TestCase):
    def _create_sample_tracker(self, path: Path) -> Path:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Matched_Jobs_Output"
        ws.append([
            "Company Name",
            "Matched & JD Skills",
            "Job Description (JD)",
            "Job Role & Match %",
            "Portal, Posted Date & Applied Result / Apply Link",
        ])
        ws.append([
            "Deloitte",
            "Matched: Python, SQL, Power BI",
            "Location: Hyderabad | Exp: 3-5 Years",
            "Senior Data Analyst — 96.5% Match",
            "Step 1: LinkedIn | Posted: 6h ago | APPLIED: LinkedIn Easy Apply",
        ])
        ws.append([
            "HCL",
            "Matched: Power BI, DAX, SQL",
            "Location: Bengaluru | Exp: 3-5 Years",
            "Power BI Developer — 88.0% Match",
            "Step 4: Company Career Page | Posted: 1d ago | Apply Link: https://careers.hcltech.com/go/NonTPDemand/9558355/",
        ])
        wb.save(path)
        wb.close()
        return path

    def test_build_message_and_mocked_smtp_ssl_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = self._create_sample_tracker(Path(tmp) / "Applied_Companies_Tracker.xlsx")

            mock_server = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value = mock_server

            with (
                patch.dict(
                    os.environ,
                    {
                        "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
                        "GMAIL_SENDER": "adithyakrishna810@gmail.com",
                        "NOTIFY_EMAIL": "adithyakrishna810@gmail.com",
                    },
                    clear=False,
                ),
                patch("send_jobs_email.smtplib.SMTP_SSL", return_value=mock_ctx) as mock_ssl,
            ):
                result = send_jobs_email.send_jobs_email(excel_path=xlsx)

            self.assertTrue(result["sent"])
            self.assertEqual(result["to"], "adithyakrishna810@gmail.com")
            self.assertEqual(result["from"], "adithyakrishna810@gmail.com")
            mock_ssl.assert_called_once_with("smtp.gmail.com", 465, timeout=30)
            mock_server.login.assert_called_once_with("adithyakrishna810@gmail.com", "abcd efgh ijkl mnop")
            mock_server.send_message.assert_called_once()

            sent_msg = mock_server.send_message.call_args[0][0]
            self.assertEqual(sent_msg["To"], "adithyakrishna810@gmail.com")
            self.assertIn("2 Matches | 1 Applied", sent_msg["Subject"])
            attachments = list(sent_msg.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), "Applied_Companies_Tracker.xlsx")
            self.assertEqual(
                attachments[0].get_content_type(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    def test_missing_gmail_app_password_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = self._create_sample_tracker(Path(tmp) / "Applied_Companies_Tracker.xlsx")
            with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": "", "SMTP_PASS": ""}, clear=False):
                with self.assertRaises(RuntimeError) as ctx:
                    send_jobs_email.send_jobs_email(excel_path=xlsx)
                self.assertIn("GMAIL_APP_PASSWORD", str(ctx.exception))

    def test_dry_run_without_password_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = self._create_sample_tracker(Path(tmp) / "Applied_Companies_Tracker.xlsx")
            with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": ""}, clear=False):
                res = send_jobs_email.send_jobs_email(excel_path=xlsx, dry_run=True)
            self.assertTrue(res["dry_run"])
            self.assertFalse(res["sent"])

    def test_if_exists_flag_exits_zero_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nonexistent_tracker.xlsx"
            rc = send_jobs_email.main(["--file", str(missing), "--if-exists"])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
