# Scribe — Case Sheet Demo

A lightweight, deployable **medical-scribe proof of concept**. The interface is styled as “Scribe” and is intended for demonstrations and feedback, not for real clinical use.

## What it does

1. Enter optional patient details, doctor name, and consultation date.
2. Record a simulated doctor–patient conversation in the browser, or upload an audio recording.
3. Send the audio to the backend for speech-to-text transcription using OpenAI.
4. Convert the transcript into a structured draft case sheet using an OpenAI language model and a defined JSON schema.
5. Review the transcript and generated case sheet in the web interface.
6. Download a PDF case sheet formatted to resemble the supplied sample.

The PDF includes patient details and structured clinical sections such as chief complaints, history of present illness, medical and surgical history, medication history, allergies, family and personal history, review of systems, examination findings, provisional diagnosis, and plan. Information that was not present in the conversation should be marked as not mentioned rather than invented. The PDF is a draft and must be checked by a qualified clinician.

The case-sheet panel has its own scroll area on desktop, with a minimum height targeted at 80% of the consultation card height (subject to available viewport height). On smaller screens, the layout returns to normal page scrolling.

> **Prototype only:** This project is not for diagnosis, treatment, or production clinical records. Use synthetic or properly consented test audio. Review every output with a qualified clinician. Do not upload identifiable patient data unless your organization has approved the provider, data flow, retention, and legal/compliance requirements.

## Technology

- **Backend:** Python, FastAPI, Uvicorn
- **AI:** OpenAI audio transcription and structured case-sheet generation
- **PDF:** ReportLab
- **Frontend:** HTML, CSS, and JavaScript served from `static/index.html`
- **Deployment:** Render (configured through `render.yaml`)

## Requirements

- Python 3.10+
- An OpenAI API key with API access and billing configured
- A modern browser (Chrome or Edge recommended)

## Run locally — Windows PowerShell

From the repository directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a `.env` file in the project root (or update the existing one) and add your API key:

```env
OPENAI_API_KEY=your_api_key_here
```

Start the app:

```powershell
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 in your browser.

## Run locally — macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Add `OPENAI_API_KEY` to a root-level `.env` file, then run:

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000.

## Deploy on Render

This repository includes a `render.yaml` blueprint.

1. Push the repository to GitHub.
2. In Render, create a Web Service from the repository or use the Blueprint option to apply `render.yaml`.
3. In the service's Environment settings, set `OPENAI_API_KEY` to a valid API key. Do not commit the key to GitHub or put it in `render.yaml`.
4. Deploy and open the service's primary URL.
5. Check the health endpoint at `/health`. A healthy service returns a response similar to:

   ```json
   {"status":"ok","app":"CaseSheetDemo"}
   ```

The server binds to the port supplied by Render using the command in `render.yaml`.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | Secret API key used by the backend | Required |
| `OPENAI_TRANSCRIPTION_MODEL` | OpenAI model used to transcribe audio | `gpt-4o-mini-transcribe` |
| `OPENAI_NOTE_MODEL` | OpenAI model used to generate the structured case sheet | `gpt-4o-mini` |
| `MAX_UPLOAD_MB` | Maximum accepted audio upload size in MB | `25` |

## API endpoints

- `GET /` — serves the Scribe web interface.
- `GET /health` — health check for deployment.
- `POST /api/casesheet` — accepts an audio file and optional patient/consultation fields, transcribes it, generates the structured case sheet, and returns the transcript, case-sheet data, and PDF download path.
- `GET /api/download/{filename}` — downloads a generated PDF.

The case-sheet generation endpoint expects an audio upload in a multipart form. Supported upload content types include audio formats and common browser-recording formats such as WebM/MP4. The configured size limit is enforced by the backend.

## Output and storage limitations

- Generated PDFs are written to the server's `generated/` directory.
- Temporary audio files are deleted by the backend after transcription is attempted.
- There is no database or user account system. Generated PDFs are not a durable medical-record store.
- On Render's free/ephemeral filesystem, generated files can disappear after a restart or redeploy. Download PDFs promptly after generating them.
- The API key is used by the backend and should never be placed in frontend code.

## Troubleshooting

- **503 — API key not configured:** Set `OPENAI_API_KEY` in the local `.env` file or Render's environment settings.
- **401/429 from OpenAI:** Check the key, API access, billing, and project usage limits.
- **502 — transcription or case-sheet generation failed:** Check the Render logs for the underlying OpenAI/API error and verify that the selected models are available to your account.
- **413 — recording too large:** Use a shorter or smaller audio file, or adjust `MAX_UPLOAD_MB` if appropriate for the demo.
- **415 — unsupported upload:** Try a common audio format such as WebM, WAV, MP3, or M4A.
- **Microphone does not work:** Grant browser microphone permission. Deployed sites require HTTPS; `localhost` works for local development.
- **PDF generation fails:** Check the Render logs for the Python traceback and confirm the latest commit has deployed.

## Security and clinical safety

- Keep API keys in environment variables; never commit secrets.
- If an API key was ever shared in chat, screenshots, logs, or source control, revoke it and replace it.
- This prototype does not provide login, access control, a database, encryption-at-rest, audit logs, or production-grade retention controls.
- Do not use real patient data in a public demo without the appropriate organizational approval and privacy/compliance safeguards.
- AI transcription may misrecognize medical terms, regional accents, or Tamil words. Verify the transcript and every generated field manually. The prompt asks the transcription model to preserve Tamil words and medical terms as spoken, but this does **not** guarantee correct translation or interpretation.
- The case sheet is AI-generated draft content and must be reviewed by a qualified clinician before any clinical use.

## Before any real-world pilot

Add authentication and authorization, explicit consent handling, secure storage and encryption, access/audit logs, automatic deletion and a documented retention policy, clinician review/approval, monitoring, and a formal privacy/security/compliance assessment.
