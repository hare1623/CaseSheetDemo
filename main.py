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
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ScribeTitle", parent=styles["Title"], fontName="Times-Bold", fontSize=24, leading=28, alignment=TA_CENTER, textColor=colors.HexColor("#063f3a"), spaceAfter=4))
    styles.add(ParagraphStyle(name="ScribeSub", parent=styles["Normal"], fontSize=8, leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#5d7773"), spaceAfter=12))
    styles.add(ParagraphStyle(name="ScribeSection", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#076f65"), spaceBefore=8, spaceAfter=4, keepWithNext=True))
    styles.add(ParagraphStyle(name="ScribeBody", parent=styles["BodyText"], fontSize=9, leading=13, textColor=colors.HexColor("#263d3b"), spaceAfter=4))
    styles.add(ParagraphStyle(name="ScribeSmall", parent=styles["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#60716e"), spaceAfter=3))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = [
        Paragraph("Scribe", styles["ScribeTitle"]),
        Paragraph("CLINICAL CASE SHEET · AI-GENERATED DRAFT", styles["ScribeSub"])
    ]

    patient = sheet.get("patient", {})
    demographics = [
        [Paragraph("<b>Patient name</b>", styles["ScribeBody"]), Paragraph(safe(patient.get("name")), styles["ScribeBody"]),
         Paragraph("<b>Age / Sex</b>", styles["ScribeBody"]), Paragraph(safe(patient.get("age")) + " / " + safe(patient.get("sex")), styles["ScribeBody"])],
        [Paragraph("<b>Occupation</b>", styles["ScribeBody"]), Paragraph(safe(patient.get("occupation")), styles["ScribeBody"]),
         Paragraph("<b>Date</b>", styles["ScribeBody"]), Paragraph(safe(date or datetime.now().strftime("%Y-%m-%d")), styles["ScribeBody"])],
        [Paragraph("<b>Doctor</b>", styles["ScribeBody"]), Paragraph(safe(doctor), styles["ScribeBody"]), "", ""]
    ]
    table = Table(demographics, colWidths=[25*mm, 56*mm, 22*mm, 61*mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f0f5f0")),
        ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#d5e2dc")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("SPAN", (1,2), (3,2)),
        ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)
    ]))
    story += [table, Spacer(1, 7)]

    for key, label in SECTION_LABELS:
        value = sheet.get(key)
        if key == "chiefComplaints":
            value = "<br/>".join(
                "• " + safe(item.get("complaint", "")) + ((" — " + safe(item.get("duration"))) if item.get("duration") else "")
                for item in (value or [])
            ) or "—"
        elif key == "personalHistory":
            personal = value or {}
            labels = [("Diet", "diet"), ("Appetite", "appetite"), ("Sleep", "sleep"),
                      ("Bowel / bladder", "bowelBladder"), ("Smoking", "smoking"),
                      ("Alcohol", "alcohol"), ("Other", "other")]
            value = "<br/>".join("<b>" + label_ + ":</b> " + safe(personal.get(field)) for label_, field in labels)
        elif isinstance(value, list):
            value = list_text(value)
        else:
            value = safe(value)
        story.append(KeepTogether([Paragraph(escape(label), styles["ScribeSection"]), Paragraph(value, styles["ScribeBody"])]))

    story += [
        Spacer(1, 8),
        Paragraph("Source transcript", styles["ScribeSection"]),
        Paragraph(safe(transcript), styles["ScribeSmall"]),
        Spacer(1, 8),
        Paragraph("Important: This AI-generated document is a draft for demonstration only. Verify the transcript, all extracted facts, and the clinical interpretation. It must not replace clinician judgment or an approved medical record.", styles["ScribeSmall"])
    ]
    doc.build(story)
