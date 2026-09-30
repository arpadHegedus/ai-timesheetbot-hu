"""Renders the weekly timesheet (English, matches the paper template).

Font note: Century Gothic isn't available to embed in this environment (no license/font file here),
so the PDF's font resource is registered under that name but backed by DejaVu Sans's outlines, which
also gives correct rendering for any accented Hungarian location names. Drop real Century Gothic .ttf
files into _FONT_DIR and repoint the two registerFont calls below to embed the real thing.
"""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config import settings

_FONT_DIR = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("CenturyGothic", f"{_FONT_DIR}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("CenturyGothic-Bold", f"{_FONT_DIR}/DejaVuSans-Bold.ttf"))
FONT, FONT_BOLD = "CenturyGothic", "CenturyGothic-Bold"

MONTHS_HU = ["január", "február", "március", "április", "május", "június", "július",
             "augusztus", "szeptember", "október", "november", "december"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


def _latest(entries: list) -> datetime:
    return datetime.strptime(max(e.date for e in entries), "%Y-%m-%d")


def period_label(entries: list) -> str:
    """'2026. szeptember' for the month of the latest entry (Hungarian; used for the history list)."""
    d = _latest(entries)
    return f"{d.year}. {MONTHS_HU[d.month - 1]}"


def email_period(entries: list) -> tuple[str, int]:
    """('September', 2026) for the month of the latest entry (English; used for the email)."""
    d = _latest(entries)
    return MONTHS_EN[d.month - 1], d.year


def _uk_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def _fmt(v: float) -> str:
    """Blank for zero (matches the template's per-day cells), otherwise 2 decimals."""
    return f"{v:.2f}" if v else ""


def build_pdf(rows: list[dict], totals: dict, period: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=f"Weekly Time Sheet - {period}")

    title_style = ParagraphStyle("title", fontName=FONT_BOLD, fontSize=15, leading=18, textColor=colors.HexColor("#7a7a7a"), alignment=2)
    company_style = ParagraphStyle("company", fontName=FONT_BOLD, fontSize=17, leading=20)
    caption = ParagraphStyle("caption", fontName=FONT, fontSize=8, textColor=colors.HexColor("#444444"))
    cell = ParagraphStyle("cell", fontName=FONT, fontSize=9, leading=12)
    cell_bold = ParagraphStyle("cellB", fontName=FONT_BOLD, fontSize=9, leading=12)
    head_style = ParagraphStyle("head", fontName=FONT_BOLD, fontSize=8.5, leading=10)
    sig_label = ParagraphStyle("sig", fontName=FONT, fontSize=9, textColor=colors.HexColor("#444444"))

    grey_line = colors.HexColor("#bbbbbb")
    band = colors.HexColor("#f2f2f2")  # totals block shading (unchanged)
    highlight = colors.HexColor("#dbe7f3")
    row_band = colors.HexColor("#f9f9f9")  # alternating day-row shading: 50% lighter than `band`
    date_light = colors.HexColor("#e9e9e9")  # Date column on a white (non-banded) row
    date_dark = colors.HexColor("#dddddd")  # Date column on a banded row: a touch darker than date_light
    GUTTER = 8 * mm
    LEFT_COL, RIGHT_COL = 100 * mm, 178 * mm - 100 * mm - GUTTER

    # --- Header: company / title, a gap, then the (intentionally blank) customer & pay-period fields ---
    header = Table(
        [[Paragraph(settings.COMPANY_NAME, company_style), "", Paragraph("Weekly Time Sheet", title_style)]],
        colWidths=[LEFT_COL, GUTTER, RIGHT_COL],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    info = Table(
        [
            [Paragraph("Customer", caption), "", Paragraph("Pay period start date:", caption)],
            [Paragraph("Address 2", caption), "", Paragraph("Pay period end date:", caption)],
            [Paragraph("City, Postcode", caption), "", ""],
            [Paragraph(f"Employee&nbsp;&nbsp;&nbsp;&nbsp;{settings.EMPLOYEE_NAME}", caption), "", ""],
        ],
        colWidths=[LEFT_COL, GUTTER, RIGHT_COL], rowHeights=7 * mm,
    )
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEBELOW", (0, 0), (0, -1), 0.6, grey_line),
        ("LINEBELOW", (2, 0), (2, 1), 0.6, grey_line),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    # --- Items table: one line per day, hours split into columns, locations in Notes ---
    head = [Paragraph(h, head_style) for h in
            ("Day", "Date", "Regular Hours", "Overtime Hours", "Sick", "Holiday", "Total", "Notes")]
    data = [head]
    for r in rows:
        data.append([
            r["weekday"], _uk_date(r["date"]),
            _fmt(r["regular"]), _fmt(r["overtime"]), _fmt(r["sick"]), _fmt(r["holiday"]),
            f"{r['total']:.2f}", Paragraph(escape(r["notes"]), cell),  # user-derived text: escape before reportlab's mini-XML parser sees it
        ])
    n = len(rows)

    # Totals block: blank Day cell, label sits in the Date column (aligned with the data above it).
    total_row = n + 1
    data.append(["", Paragraph("Total hours", cell_bold), f"{totals['regular']:.2f}", f"{totals['overtime']:.2f}",
                 f"{totals['sick']:.2f}", f"{totals['holiday']:.2f}", f"{totals['total']:.2f}", ""])
    rate_row = total_row + 1
    data.append(["", Paragraph("Rate per hour", cell_bold), "", "", "", "", "", ""])
    pay_row = rate_row + 1
    data.append(["", Paragraph("Total pay", cell_bold), "", "", "", "", "", ""])

    hour_col = 18 * mm  # Regular/Overtime/Sick/Holiday/Total: kept equal width
    col_widths = [18 * mm, 32 * mm, hour_col, hour_col, hour_col, hour_col, hour_col, None]
    items = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, 0), 3), ("RIGHTPADDING", (0, 0), (-1, 0), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (6, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        # Day rows: no grid, just alternating banding. The Date column is always grey too, one shade
        # darker on rows that are also banded, so its own odd/even pattern stays visible.
        ("ROWBACKGROUNDS", (0, 1), (-1, n), [colors.white, row_band]),
        *[("BACKGROUND", (1, i), (1, i), date_dark if (i - 1) % 2 else date_light) for i in range(1, n + 1)],
        # Totals block: bold labels, shaded + bordered on the Date..Total columns only —
        # the Day and Notes columns stay blank and transparent either side of it.
        ("FONTNAME", (0, total_row), (-1, total_row), FONT_BOLD),
        ("BACKGROUND", (1, total_row), (6, total_row), band),
        ("BACKGROUND", (1, rate_row), (6, rate_row), highlight),
        ("BACKGROUND", (1, pay_row), (6, pay_row), band),
        ("GRID", (1, total_row), (6, pay_row), 0.5, grey_line),
    ]
    if n == 0:
        style.append(("SPAN", (0, 1), (-1, 1)))
        data[1] = ["No entries", "", "", "", "", "", "", ""]
    items.setStyle(TableStyle(style))

    sig = Table(
        [
            ["", ""],
            [Paragraph("Employee signature", sig_label), Paragraph("Date", sig_label)],
            ["", ""],
            [Paragraph("Manager signature", sig_label), Paragraph("Date", sig_label)],
        ],
        colWidths=[110 * mm, 68 * mm], rowHeights=[9 * mm, 6 * mm, 9 * mm, 6 * mm],
    )
    sig.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, grey_line),  # sign above the label, not below it
        ("LINEBELOW", (0, 2), (-1, 2), 0.6, grey_line),
    ]))

    doc.build([
        header, Spacer(1, 14), info, Spacer(1, 10),
        items, Spacer(1, 14), sig,
    ])
    return buf.getvalue()
