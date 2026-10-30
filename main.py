import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="CaseSheetDemo", version="0.2.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
NOTE_MODEL = os.getenv("OPENAI_NOTE_MODEL", "gpt-4o-mini")

# Mirrors the supplied case-sheet schema. Every property is required; unknown
# information is represented by null, an empty string, or an empty array.
CASE_SHEET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "patient": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": ["string", "null"]},
                "age": {"type": ["string", "null"]},
                "sex": {"type": ["string", "null"]},
                "occupation": {"type": ["string", "null"]}
            },
            "required": ["name", "age", "sex", "occupation"]
        },
        "chiefComplaints": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "complaint": {"type": "string"},
                    "duration": {"type": ["string", "null"]}
                },
                "required": ["complaint", "duration"]
            }
        },
        "historyOfPresentIllness": {"type": ["string", "null"]},
        "pastMedicalHistory": {"type": "array", "items": {"type": "string"}},
        "pastSurgicalHistory": {"type": "array", "items": {"type": "string"}},
        "medicationHistory": {"type": "array", "items": {"type": "string"}},
        "allergies": {"type": "array", "items": {"type": "string"}},
        "familyHistory": {"type": "array", "items": {"type": "string"}},
        "personalHistory": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "diet": {"type": ["string", "null"]},
                "appetite": {"type": ["string", "null"]},
                "sleep": {"type": ["string", "null"]},
                "bowelBladder": {"type": ["string", "null"]},
                "smoking": {"type": ["string", "null"]},
                "alcohol": {"type": ["string", "null"]},
                "other": {"type": ["string", "null"]}
            },
            "required": ["diet", "appetite", "sleep", "bowelBladder", "smoking", "alcohol", "other"]
        },
        "menstrualObstetricHistory": {"type": ["string", "null"]},
        "reviewOfSystems": {"type": "array", "items": {"type": "string"}},
        "examinationFindings": {"type": "array", "items": {"type": "string"}},
        "provisionalDiagnosis": {"type": ["string", "null"]},
        "plan": {"type": "array", "items": {"type": "string"}},
        "redFlags": {"type": "array", "items": {"type": "string"}}
    },
    "required": [
        "patient", "chiefComplaints", "historyOfPresentIllness", "pastMedicalHistory",
        "pastSurgicalHistory", "medicationHistory", "allergies", "familyHistory",
        "personalHistory", "menstrualObstetricHistory", "reviewOfSystems",
        "examinationFindings", "provisionalDiagnosis", "plan", "redFlags"
    ]
}

SECTION_LABELS = [
    ("chiefComplaints", "Chief complaints"),
    ("historyOfPresentIllness", "History of present illness"),
    ("pastMedicalHistory", "Past medical history"),
    ("pastSurgicalHistory", "Past surgical history"),
    ("medicationHistory", "Medication history"),
    ("allergies", "Allergies"),
    ("familyHistory", "Family history"),
    ("personalHistory", "Personal history"),
    ("menstrualObstetricHistory", "Menstrual / obstetric history"),
    ("reviewOfSystems", "Review of systems"),
    ("examinationFindings", "Examination findings"),
    ("provisionalDiagnosis", "Provisional diagnosis"),
    ("plan", "Plan"),
    ("redFlags", "Red flags")
]


@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok", "app": "CaseSheetDemo"}


def get_client():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or key == "replace_with_your_rotated_api_key":
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured. Add OPENAI_API_KEY to your local .env file or hosting environment variables.")
    return OpenAI(api_key=key)


@app.post("/api/casesheet")
async def create_casesheet(
    audio: UploadFile = File(...),
    patient_name: str = Form(""),
    patient_age: str = Form(""),
    patient_sex: str = Form(""),
    patient_occupation: str = Form(""),
    doctor_name: str = Form(""),
    consultation_date: str = Form("")
):
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Please choose an audio recording.")
    content_type = (audio.content_type or "").lower()
    allowed_types = ("audio/", "video/webm", "video/mp4", "application/octet-stream")
    if not any(content_type.startswith(t) for t in allowed_types):
        raise HTTPException(status_code=415, detail="Please upload an audio file such as WebM, WAV, MP3, or M4A.")

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded recording is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Recording is too large. Maximum size is {MAX_UPLOAD_MB} MB.")

    client = get_client()
    suffix = Path(audio.filename).suffix or ".webm"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            temp_path = Path(tmp.name)
        with temp_path.open("rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model=TRANSCRIPTION_MODEL,
                file=audio_file,
                prompt="Medical consultation between a doctor and patient. Preserve medical terms and Tamil words as spoken; do not guess unclear words."
            )
        transcript = getattr(transcription, "text", "") or ""
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Audio transcription failed: {str(exc)[:300]}")
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)

    if not transcript.strip():
        raise HTTPException(status_code=422, detail="No speech could be transcribed. Try a clearer recording.")

    metadata = {
        "name": patient_name.strip() or None,
        "age": patient_age.strip() or None,
        "sex": patient_sex.strip() or None,
        "occupation": patient_occupation.strip() or None
    }
    context = (
        "Doctor name: " + (doctor_name.strip() or "Not provided") + "\n"
        "Consultation date: " + (consultation_date.strip() or datetime.now().strftime("%Y-%m-%d")) + "\n"
        "Patient details supplied by user: " + json.dumps(metadata, ensure_ascii=False) + "\n"
        "Transcript:\n" + transcript
    )
    system_prompt = """You create a structured DRAFT case sheet from a doctor-patient conversation.
Follow the provided JSON schema exactly. Use only information supported by the transcript or explicitly supplied patient details.
Do not invent or infer a diagnosis, symptoms, examination findings, medications, allergies, duration, or plan.
For unknown scalar values return null; for unknown lists return []; for unknown patient details return null.
Keep the speaker's meaning. Do not turn uncertain speech into a confident medical fact. If a phrase is unclear, place a short note in redFlags such as 'Needs clinician verification: [unclear phrase]' rather than guessing.
Distinguish patient-reported symptoms from clinician statements where possible. A provisional diagnosis must only be included if it was stated in the conversation.
This is a demonstration draft and must be checked and approved by a licensed clinician before clinical use."""
    try:
        response = client.chat.completions.create(
            model=NOTE_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "medical_case_sheet",
                    "strict": True,
                    "schema": CASE_SHEET_SCHEMA
                }
            }
        )
        case_sheet = json.loads(response.choices[0].message.content)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Case sheet generation failed: {str(exc)[:300]}")

    # Explicit form details take precedence over extracted demographic values.
    for key, value in metadata.items():
        if value:
            case_sheet["patient"][key] = value

    safe_patient = "".join(c for c in (patient_name or "patient") if c.isalnum() or c in ("-", "_")).strip()[:40] or "patient"
    output_dir = BASE_DIR / "generated"
    output_dir.mkdir(exist_ok=True)
    pdf_name = f"casesheet_{safe_patient}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = output_dir / pdf_name
    build_pdf(pdf_path, case_sheet, doctor_name.strip(), consultation_date.strip(), transcript)

    return {
        "message": "Draft case sheet generated. Please review all details before any clinical use.",
        "caseSheet": case_sheet,
        "transcript": transcript,
        "pdf_url": f"/api/download/{pdf_name}"
    }


@app.get("/api/download/{filename}")
def download_pdf(filename: str):
    if "/" in filename or "\\" in filename or not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    path = BASE_DIR / "generated" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not found. Generate the case sheet again.")
    return FileResponse(path, media_type="application/pdf", filename=filename)


def safe(value):
    if value is None or not str(value).strip():
        return "—"
    return escape(str(value)).replace("\n", "<br/>")


def list_text(items):
    if not items:
        return "—"
    return "<br/>".join("• " + safe(item) for item in items)


def build_pdf(path: Path, sheet: dict, doctor: str, date: str, transcript: str):
    """Render the downloadable PDF in the supplied Scribe sample style.
    The web UI, API response, extraction schema, and generation flow are unchanged.
    """
    from reportlab.platypus import PageBreak

    styles = getSampleStyleSheet()
    ink = colors.HexColor("#102f2d")
    muted = colors.HexColor("#667875")
    teal = colors.HexColor("#16766d")
    rule = colors.HexColor("#d9dfd9")

    styles.add(ParagraphStyle(
        name="CaseKicker", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.5, leading=10, textColor=muted, tracking=2.2,
        spaceAfter=5
    ))
    styles.add(ParagraphStyle(
        name="CaseName", parent=styles["Title"], fontName="Times-Bold",
        fontSize=22, leading=25, alignment=0, textColor=ink,
        spaceBefore=0, spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        name="CaseMetaLabel", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7, leading=9, textColor=muted, tracking=1.5,
        spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        name="CaseMetaValue", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, leading=12, textColor=ink, spaceAfter=0
    ))
    styles.add(ParagraphStyle(
        name="CaseSection", parent=styles["Normal"], fontName="Times-Bold",
        fontSize=13, leading=16, textColor=ink, spaceBefore=0, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name="CaseBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.5, leading=12.5, textColor=colors.HexColor("#243b39"),
        spaceAfter=3
    ))
    styles.add(ParagraphStyle(
        name="CaseBullet", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.5, leading=12.5, leftIndent=10, firstLineIndent=-7,
        bulletIndent=0, textColor=colors.HexColor("#243b39"), spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        name="CaseMissing", parent=styles["BodyText"], fontName="Helvetica-Oblique",
        fontSize=8.5, leading=12.5, textColor=muted, spaceAfter=3
    ))
    styles.add(ParagraphStyle(
        name="CasePersonalLabel", parent=styles["Normal"], fontName="Helvetica",
        fontSize=8, leading=11, textColor=muted
    ))
    styles.add(ParagraphStyle(
        name="CasePersonalValue", parent=styles["Normal"], fontName="Helvetica",
        fontSize=8, leading=11, textColor=ink
    ))

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        rightMargin=16*mm, leftMargin=16*mm,
        topMargin=17*mm, bottomMargin=16*mm,
        title="Scribe — AI case sheet from consultation",
        author="Scribe"
    )

    def on_page(canvas, document):
        canvas.saveState()
        page_w, page_h = A4
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        stamp = date.strip() if date and date.strip() else datetime.now().strftime("%d/%m/%y")
        canvas.drawString(16*mm, page_h - 9*mm, escape(stamp))
        canvas.drawCentredString(page_w / 2, page_h - 9*mm, "Scribe — AI case sheets from consultations")
        canvas.setStrokeColor(rule)
        canvas.setLineWidth(0.5)
        canvas.line(16*mm, 12*mm, page_w - 16*mm, 12*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawRightString(page_w - 16*mm, 7.5*mm, f"{document.page}")
        canvas.restoreState()

    patient = sheet.get("patient") or {}
    patient_name = (patient.get("name") or "").strip() or "Patient name not stated"
    story = [
        Spacer(1, 2*mm),
        Paragraph("C A S E   S H E E T", styles["CaseKicker"]),
        Paragraph(safe(patient_name), styles["CaseName"]),
    ]

    meta_items = [
        ("AGE", patient.get("age")),
        ("SEX", patient.get("sex")),
        ("OCCUPATION", patient.get("occupation")),
    ]
    meta_cells = []
    for label, value in meta_items:
        value_text = safe(value) if value and str(value).strip() else "—"
        meta_cells.append([
            Paragraph(label, styles["CaseMetaLabel"]),
            Paragraph(value_text, styles["CaseMetaValue"])
        ])
    meta_table = Table(
        [[Table(cell, colWidths=[54*mm], style=TableStyle([
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ])) for cell in meta_cells]],
        colWidths=[57*mm, 57*mm, 57*mm],
        hAlign="LEFT"
    )
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ]))
    story += [meta_table, Spacer(1, 3*mm)]

    divider = Table([[""]], colWidths=[178*mm], rowHeights=[0.4])
    divider.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), rule)]))
    story += [divider, Spacer(1, 7*mm)]

    def value_paragraph(value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return [Paragraph("Not mentioned", styles["CaseMissing"])]
        if isinstance(value, list):
            if not value:
                return [Paragraph("Not mentioned", styles["CaseMissing"])]
            output = []
            for item in value:
                if isinstance(item, dict):
                    complaint = item.get("complaint") or ""
                    duration = item.get("duration")
                    text_value = safe(complaint)
                    if duration and str(duration).strip():
                        text_value += " — " + safe(duration)
                else:
                    text_value = safe(item)
                output.append(Paragraph("• " + text_value, styles["CaseBullet"]))
            return output
        text_value = str(value).strip()
        if not text_value:
            return [Paragraph("Not mentioned", styles["CaseMissing"])]
        return [Paragraph(safe(text_value), styles["CaseBody"])]

    def personal_rows(value):
        value = value or {}
        pairs = [
            ("Diet", "diet"), ("Appetite", "appetite"), ("Sleep", "sleep"),
            ("Bowel/Bladder", "bowelBladder"), ("Smoking", "smoking"),
            ("Alcohol", "alcohol"), ("Other", "other")
        ]
        rows = []
        for label, key in pairs:
            item = value.get(key)
            missing = item is None or not str(item).strip()
            rows.append([
                Paragraph(label, styles["CasePersonalLabel"]),
                Paragraph("—" if missing else safe(item), styles["CasePersonalValue"])
            ])
        table = Table(rows, colWidths=[29*mm, 52*mm], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 3),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        return [table]

    def section(number, key, title):
        heading = Table([[
            Paragraph(f'<font color="#16766d">{number:02d}</font>', styles["CaseMetaValue"]),
            Paragraph(escape(title), styles["CaseSection"])
        ]], colWidths=[9*mm, 75*mm], hAlign="LEFT")
        heading.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 2),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        content = personal_rows(sheet.get(key)) if key == "personalHistory" else value_paragraph(sheet.get(key))
        return [KeepTogether([heading] + content + [Spacer(1, 3*mm)])]

    def two_column(left_section, right_section):
        left = section(*left_section)
        right = section(*right_section)
        # A ReportLab table cell must contain a Flowable, not a Python list.
        # section() returns a one-item list containing a KeepTogether Flowable.
        left_box = Table([[left[0]]], colWidths=[85*mm], hAlign="LEFT")
        right_box = Table([[right[0]]], colWidths=[85*mm], hAlign="LEFT")
        for box in (left_box, right_box):
            box.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING", (0,0), (-1,-1), 0),
                ("RIGHTPADDING", (0,0), (-1,-1), 0),
                ("TOPPADDING", (0,0), (-1,-1), 0),
                ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ]))
        row = Table([[left_box, right_box]], colWidths=[89*mm, 89*mm], hAlign="LEFT")
        row.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 2*mm),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        return row

    # Page 1: match the reference's editorial layout and paired sections.
    story += section(1, "chiefComplaints", "Chief complaints")
    story += section(2, "historyOfPresentIllness", "History of present illness")
    story += [two_column(
        (3, "pastMedicalHistory", "Past medical history"),
        (4, "pastSurgicalHistory", "Past surgical history")
    ), Spacer(1, 3*mm)]
    story += [two_column(
        (5, "medicationHistory", "Medications"),
        (6, "allergies", "Allergies")
    ), Spacer(1, 3*mm)]
    story += [two_column(
        (7, "familyHistory", "Family history"),
        (8, "personalHistory", "Personal history")
    ), Spacer(1, 3*mm)]
    story += section(9, "reviewOfSystems", "Review of systems")

    # Page 2 intentionally mirrors the supplied sample: only sections 10–12.
    story.append(PageBreak())
    story += section(10, "examinationFindings", "Examination findings")
    story += section(11, "provisionalDiagnosis", "Provisional diagnosis")
    story += section(12, "plan", "Plan")

    story += [
        Spacer(1, 5*mm),
        Paragraph(
            "Draft for demonstration only. Verify the transcript, extracted facts, "
            "and clinical interpretation. This document must not replace clinician "
            "judgment or an approved medical record.",
            styles["CaseMissing"]
        )
    ]
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
