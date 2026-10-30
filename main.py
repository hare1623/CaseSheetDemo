import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="CaseSheetDemo", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
NOTE_MODEL = os.getenv("OPENAI_NOTE_MODEL", "gpt-4o-mini")


@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


def get_client():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or key == "replace_with_your_rotated_api_key":
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key is not configured. Add OPENAI_API_KEY to your local .env file or hosting environment variables."
        )
    return OpenAI(api_key=key)


@app.get("/health")
def health():
    return {"status": "ok", "app": "CaseSheetDemo"}


@app.post("/api/casesheet")
async def create_casesheet(
    audio: UploadFile = File(...),
    patient_name: str = Form(""),
    patient_age: str = Form(""),
    doctor_name: str = Form(""),
    consultation_date: str = Form(""),
):
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Please choose an audio recording.")
    content_type = (audio.content_type or "").lower()
    allowed_types = ("audio/", "video/webm", "application/octet-stream")
    if not any(content_type.startswith(t) for t in allowed_types):
        raise HTTPException(status_code=415, detail="Please upload an audio file such as WebM, WAV, MP3, or M4A.")

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded recording is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Recording is too large. Maximum size is {MAX_UPLOAD_MB} MB.")

    client = get_client()
    suffix = Path(audio.filename).suffix or ".webm"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            temp_path = Path(tmp.name)
        try:
            with temp_path.open("rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model=TRANSCRIPTION_MODEL,
                    file=audio_file,
                )
            transcript = getattr(transcription, "text", "") or ""
        finally:
            temp_path.unlink(missing_ok=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Audio transcription failed: {str(exc)[:300]}")

    if not transcript.strip():
        raise HTTPException(status_code=422, detail="No speech could be transcribed. Try a clearer recording.")

    metadata = {
        "Patient name": patient_name.strip() or "Not provided",
        "Age": patient_age.strip() or "Not provided",
        "Doctor": doctor_name.strip() or "Not provided",
        "Consultation date": consultation_date.strip() or datetime.now().strftime("%Y-%m-%d"),
    }
    prompt = f"""
You are assisting with a DEMONSTRATION medical documentation workflow. Convert the doctor-patient conversation transcript into a concise draft clinical visit note.

Rules:
- Use only facts stated in the transcript or metadata. Never invent symptoms, diagnoses, medications, allergies, examination findings, or treatment.
- If a detail is absent or unclear, write "Not stated" or "Needs clinician review".
- Do not make independent diagnoses or treatment recommendations.
- Clearly label this as an AI-generated DRAFT that must be reviewed and approved by a licensed clinician before use.
- Preserve uncertainty and distinguish patient-reported information from clinician statements.
- Return plain text with these exact section headings:
Chief Complaint
History of Present Illness
Relevant Medical History
Medications and Allergies
Review of Systems
Examination / Observations
Assessment (as stated in conversation)
Plan (as stated in conversation)
Follow-up
Items Requiring Clinician Review

Patient metadata:
{metadata}

Conversation transcript:
{transcript}
"""
    try:
        response = client.responses.create(
            model=NOTE_MODEL,
            input=prompt,
        )
        note = response.output_text.strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Case sheet generation failed: {str(exc)[:300]}")

    safe_patient = "".join(c for c in (patient_name or "patient") if c.isalnum() or c in ("-", "_")).strip()[:40] or "patient"
    pdf_path = BASE_DIR / "generated" / f"casesheet_{safe_patient}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path.parent.mkdir(exist_ok=True)
    build_pdf(pdf_path, metadata, transcript, note)
    return {
        "message": "Draft case sheet generated. Review it carefully before any clinical use.",
        "metadata": metadata,
        "transcript": transcript,
        "note": note,
        "pdf_url": f"/api/download/{pdf_path.name}",
    }


@app.get("/api/download/{filename}")
def download_pdf(filename: str):
    # Only allow PDFs generated in this app's output directory.
    if "/" in filename or "\\" in filename or not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    path = BASE_DIR / "generated" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not found. Generate the case sheet again.")
    return FileResponse(path, media_type="application/pdf", filename=filename)


def build_pdf(path: Path, metadata: dict, transcript: str, note: str):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#17324d"), spaceAfter=8))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#17324d"), spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=9, leading=13, spaceAfter=5))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    story = [
        Paragraph("CaseSheetDemo", styles["DocTitle"]),
        Paragraph("AI-GENERATED DRAFT — CLINICIAN REVIEW REQUIRED", styles["Heading3"]),
        Spacer(1, 5),
    ]
    rows = [[Paragraph(f"<b>{k}</b>", styles["BodySmall"]), Paragraph(escape_pdf(v), styles["BodySmall"])] for k, v in metadata.items()]
    table = Table(rows, colWidths=[38*mm, 130*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#eef3f8")),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#ccd6e0")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story += [table, Spacer(1, 8), Paragraph("Draft Clinical Note", styles["Section"])]
    for line in note.splitlines():
        line = line.strip()
        if not line:
            story.append(Spacer(1, 3))
        elif len(line) < 70 and (line.endswith(":") or line.lower() in {
            "chief complaint", "history of present illness", "relevant medical history",
            "medications and allergies", "review of systems", "examination / observations",
            "assessment (as stated in conversation)", "plan (as stated in conversation)",
            "follow-up", "items requiring clinician review"
        }):
            story.append(Paragraph(escape_pdf(line), styles["Section"]))
        else:
            story.append(Paragraph(escape_pdf(line), styles["BodySmall"]))
    story += [Spacer(1, 8), Paragraph("Source Transcript", styles["Section"])]
    story.append(Paragraph(escape_pdf(transcript), styles["BodySmall"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Privacy note: This demo processes uploaded audio through the configured AI provider. Use synthetic or consented test recordings only. Do not upload identifiable patient data without appropriate authorization and safeguards.", styles["Italic"]))
    doc.build(story)


def escape_pdf(text: str) -> str:
    from xml.sax.saxutils import escape
    return escape(str(text)).replace("\n", "<br/>")
