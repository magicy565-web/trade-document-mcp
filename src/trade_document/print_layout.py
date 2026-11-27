"""Print an approved workbook to PDF using an isolated LibreOffice profile."""

import shutil, subprocess, tempfile
from pathlib import Path
from pypdf import PdfReader
from openpyxl import load_workbook
from .audit import compact
from .model import Model


class LayoutReport(Model):
    pages: int
    paper_points: list[tuple[float, float]]
    missing_pages: list[int]
    preview_only: bool = True


def pagereport(path):
    reader = PdfReader(path)
    return LayoutReport(
        pages=len(reader.pages),
        paper_points=[
            (float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages
        ],
        missing_pages=[
            i
            for i, p in enumerate(reader.pages, 1)
            if not (p.extract_text() or "").strip()
        ],
    )


def convert(workbook, pdf):
    binary = shutil.which("soffice")
    if binary is None:
        raise ValueError("Approved enterprise PDF output requires LibreOffice Calc")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                binary,
                "-env:UserInstallation=" + Path(tmp, "profile").as_uri(),
                "--headless",
                "--convert-to",
                "pdf:calc_pdf_Export",
                "--outdir",
                str(pdf.parent),
                str(workbook),
            ],
            check=True,
            timeout=120,
            capture_output=True,
        )
    if not pdf.is_file() or pagereport(pdf).missing_pages:
        raise ValueError("Incomplete spreadsheet print output")


def verify_printed(workbook, pdf):
    wb = load_workbook(workbook, data_only=True)
    text = compact(
        "".join(p.extract_text(extraction_mode="layout") for p in PdfReader(pdf).pages)
    )
    findings = []
    for ws in wb:
        for row in ws:
            for c in row:
                if c.value is None or ws.row_dimensions[c.row].hidden:
                    continue
                if isinstance(c.value, str) and compact(c.value) not in text:
                    # Wrapped cells can be interleaved with other columns in layout mode.
                    if not all(compact(word) in text for word in c.value.split()):
                        findings.append(
                            f"Printed text missing at {ws.title}!{c.coordinate}"
                        )
    return findings
