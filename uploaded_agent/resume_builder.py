import shutil
import sys
from pathlib import Path
from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, HRFlowable
import docx
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import openpyxl

from config import (
    BASE_DIR,
    COMPANY_CHECK_SHEET,
    RESUME_PDF_PATH,
    RESUME_DOCX_PATH,
    MIS_RESUME_DOCX_PATH,
    DA_RESUME_DOCX_PATH,
    AIML_RESUME_DOCX_PATH,
    CANDIDATE_PROFILE,
    OFFICIAL_COMPANY_PORTALS,
)


def ensure_company_check_sheet() -> Path:
    """Ensures 'Company name.xlsx' exists in the project folder with the 12 target companies."""
    if COMPANY_CHECK_SHEET.exists():
        return COMPANY_CHECK_SHEET
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Target Companies"
    ws.append(["Company Name", "Official Careers Portal", "Target Roles"])
    default_roles = "Data Analyst / AI & ML Engineer / MIS / Gen AI / Power BI"
    companies = [
        ("Deloitte", OFFICIAL_COMPANY_PORTALS["deloitte"]["careers_url"], default_roles),
        ("Capgemini", OFFICIAL_COMPANY_PORTALS["capgemini"]["careers_url"], default_roles),
        ("Infosys", OFFICIAL_COMPANY_PORTALS["infosys"]["careers_url"], default_roles),
        ("Cognizant", OFFICIAL_COMPANY_PORTALS["cognizant"]["careers_url"], default_roles),
        ("Randstad", OFFICIAL_COMPANY_PORTALS["randstad"]["careers_url"], default_roles),
        ("NTT DATA", OFFICIAL_COMPANY_PORTALS["ntt data"]["careers_url"], default_roles),
        ("Indium Software", OFFICIAL_COMPANY_PORTALS["indium"]["careers_url"], default_roles),
        ("Wipro", OFFICIAL_COMPANY_PORTALS["wipro"]["careers_url"], default_roles),
        ("Tech Mahindra", OFFICIAL_COMPANY_PORTALS["techmahindra"]["careers_url"], default_roles),
        ("Optum", OFFICIAL_COMPANY_PORTALS["optum"]["careers_url"], default_roles),
        ("Accenture", OFFICIAL_COMPANY_PORTALS["accenture"]["careers_url"], default_roles),
        ("EY", OFFICIAL_COMPANY_PORTALS["ey"]["careers_url"], default_roles),
    ]
    for row in companies:
        ws.append(list(row))
    wb.save(COMPANY_CHECK_SHEET)
    return COMPANY_CHECK_SHEET


def _read_docx_lines(docx_path: Path) -> List[str]:
    """Extract non-empty paragraph lines from a .docx resume."""
    d = docx.Document(str(docx_path))
    lines = [p.text.strip() for p in d.paragraphs if p.text and p.text.strip()]
    return lines


def _render_lines_to_pdf(lines: List[str], out_pdf: Path) -> Path:
    """Render structured resume lines into a clean ATS-friendly PDF using ReportLab."""
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_pdf),
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=28,
        bottomMargin=28,
    )
    styles = getSampleStyleSheet()

    header_name = ParagraphStyle(
        "HeaderName",
        parent=styles["Heading1"],
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#12355B"),
        spaceAfter=2,
    )
    header_sub = ParagraphStyle(
        "HeaderSub",
        parent=styles["Normal"],
        fontSize=9.2,
        leading=12.5,
        textColor=colors.HexColor("#222222"),
        spaceAfter=4,
    )
    sec_heading = ParagraphStyle(
        "SecHeading",
        parent=styles["Heading2"],
        fontSize=10.5,
        leading=13.5,
        textColor=colors.HexColor("#12355B"),
        spaceBefore=7,
        spaceAfter=3,
    )
    body_style = ParagraphStyle(
        "BodyTextCustom",
        parent=styles["Normal"],
        fontSize=9.0,
        leading=12.2,
        textColor=colors.HexColor("#111111"),
        spaceAfter=2.5,
    )

    section_headers = {
        "SUMMARY",
        "TECHNICAL SKILLS",
        "PROFESSIONAL EXPERIENCE",
        "ACHIEVEMENTS",
        "PROJECTS",
        "CERTIFICATIONS",
        "EDUCATION",
        "LANGUAGES",
        "CORE COMPETENCIES",
    }

    story = []
    for idx, line in enumerate(lines):
        safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        normalized = line.upper().rstrip(":").strip()
        if idx == 0:
            story.append(Paragraph(f"<b>{safe_line}</b>", header_name))
        elif idx in (1, 2, 3):
            story.append(Paragraph(safe_line, header_sub))
            if idx == 3:
                story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#12355B"), spaceAfter=4))
        elif normalized in section_headers:
            story.append(Paragraph(f"<b>{safe_line.upper().rstrip(':')}</b>", sec_heading))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC"), spaceAfter=3))
        elif line.startswith("- ") or line.startswith("• "):
            story.append(Paragraph(f"&bull; {safe_line[2:].strip()}", body_style))
        elif " — " in line and "|" in line:
            story.append(Paragraph(f"<b>{safe_line}</b>", body_style))
        else:
            story.append(Paragraph(safe_line, body_style))

    doc.build(story)
    return out_pdf


def ensure_resume_files() -> Path:
    """
    Builds role-specific ATS-friendly PDFs in `resumes/` directly from each uploaded
    role-tailored `.docx` resume (AI/ML Engineer, Data Analyst / Power BI / ETL, MIS Executive),
    rather than duplicating one generic PDF across all roles.
    """
    ensure_company_check_sheet()

    resumes_subdir = BASE_DIR / "resumes"
    resumes_subdir.mkdir(parents=True, exist_ok=True)

    # Only check Windows E:\all resumes when running on Windows
    if sys.platform == "win32":
        all_resumes_dir = Path(r"E:\all resumes")
        if all_resumes_dir.exists():
            copy_map = [
                (all_resumes_dir / "Adithya_Krishna_MIS_Executive_Resume.docx", MIS_RESUME_DOCX_PATH),
                (all_resumes_dir / "Adithya_Krishna_Data Scientist_with AI.docx", AIML_RESUME_DOCX_PATH),
                (all_resumes_dir / "Adithya cover letter.docx", BASE_DIR / "Adithya_Cover_Letter.docx"),
                (all_resumes_dir / "Data analyst experienced" / "Adithya_Krishna.docx", DA_RESUME_DOCX_PATH),
            ]
            for src, dst in copy_map:
                try:
                    if src.exists() and not dst.exists():
                        shutil.copy2(src, dst)
                except Exception:
                    pass

    # 1. Build primary master PDF (from uploaded Adithya_Krishna_Resume.docx if present, else config text)
    if RESUME_DOCX_PATH.exists():
        master_lines = _read_docx_lines(RESUME_DOCX_PATH)
    else:
        master_lines = [line.strip() for line in CANDIDATE_PROFILE["resume_text"].strip().splitlines() if line.strip()]
    _render_lines_to_pdf(master_lines, RESUME_PDF_PATH)

    # 2. Build EACH role-specific PDF from its genuine corresponding uploaded .docx resume!
    variant_sources = [
        ("Adithya_Krishna_AIML_Engineer.pdf", AIML_RESUME_DOCX_PATH),
        ("Adithya_Krishna_Data_Analyst.pdf", DA_RESUME_DOCX_PATH),
        ("Adithya_Krishna_Power_BI_Developer.pdf", DA_RESUME_DOCX_PATH),
        ("Adithya_Krishna_Data_Engineer.pdf", DA_RESUME_DOCX_PATH),
        ("Adithya_Krishna_Business_Analyst.pdf", DA_RESUME_DOCX_PATH),
        ("Adithya_Krishna_MIS_Executive.pdf", MIS_RESUME_DOCX_PATH),
    ]
    for pdf_name, src_docx in variant_sources:
        out_pdf = resumes_subdir / pdf_name
        if src_docx.exists():
            lines = _read_docx_lines(src_docx)
            _render_lines_to_pdf(lines, out_pdf)
        else:
            shutil.copy2(RESUME_PDF_PATH, out_pdf)

    # Preserve uploaded RESUME_DOCX_PATH if it already exists; only build if missing
    if not RESUME_DOCX_PATH.exists():
        d = docx.Document()
        for section in d.sections:
            section.top_margin = Inches(0.5)
            section.bottom_margin = Inches(0.5)
            section.left_margin = Inches(0.5)
            section.right_margin = Inches(0.5)
        for idx, line in enumerate(master_lines):
            p = d.add_paragraph()
            if idx == 0:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                run = p.add_run(line)
                run.bold = True
                run.font.size = Pt(15)
                run.font.color.rgb = RGBColor(0x12, 0x35, 0x5B)
            else:
                run = p.add_run(line)
                run.font.size = Pt(9.5)
        d.save(str(RESUME_DOCX_PATH))

    return RESUME_PDF_PATH


if __name__ == "__main__":
    pdf = ensure_resume_files()
    print(f"Generated role-specific Resume PDFs in {BASE_DIR / 'resumes'} (primary: {pdf})")
