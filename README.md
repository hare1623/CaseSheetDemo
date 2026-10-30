# CaseSheetDemo

A small, deployable medical-scribe proof of concept:
1. Record a simulated doctor–patient conversation in the browser, or upload an audio file.
2. Send audio to OpenAI speech-to-text from the server.
3. Turn the transcript into a structured draft clinical note.
4. Preview the transcript and note, and download a PDF.

> **Prototype only:** Not for diagnosis, treatment, or production clinical records. Use synthetic or properly consented test audio. Review every output with a qualified clinician. Do not upload identifiable patient data unless your organization has approved the provider, data flow, retention, and legal/compliance requirements.

## 1. Requirements
- Python 3.10+
- An OpenAI API key with API billing/access enabled
- A modern browser (Chrome/Edge recommended)

## 2. Run locally (Windows PowerShell)

```powershell
cd CaseSheetDemo
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Open `.env` and replace the placeholder with a **newly rotated** API key:

```env
OPENAI_API_KEY=your_new_api_key_here
```

Start the server:

```powershell
uvicorn main:app --reload
```

Open http://127.0.0.1:8000

## 3. Run locally (macOS/Linux)

```bash
cd CaseSheetDemo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Add your key to `.env`, then:

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000

## 4. Deploy on Render

This repo includes `render.yaml`.
1. Push the project to a **private GitHub repository**. `.gitignore` excludes `.env`; verify it is not tracked before pushing.
2. In Render, create a new Web Service from that repository. Render should detect `render.yaml`.
3. In the service's Environment settings, set `OPENAI_API_KEY` to your newly rotated key. Do not add the key to GitHub or `render.yaml`.
4. Deploy and open the service URL. The app listens on the platform-provided `PORT`.
5. Test `/health`; it should return `{"status":"ok","app":"CaseSheetDemo"}`.

You can also deploy to Railway or another Python host that supports environment variables and a persistent or ephemeral filesystem. Generated PDFs are stored temporarily on the server and may disappear after restart/redeploy; download them promptly. For a demo, this is acceptable.

## 5. Security notes
- The API key is used only by the backend; it is never sent to the browser.
- `.env` is intentionally ignored by Git. Keep it locally; set secrets using the host's Environment Variables / Secrets interface after deployment.
- The key shared in chat should be considered exposed. Revoke it and create a replacement before running or deploying this demo.
- This prototype has no login, access control, database, encryption-at-rest, or production-grade retention controls. Do not publish it with real patient data.
- Browser microphone recording requires a secure context: `localhost` works for local development; deployed sites should use HTTPS.
- Do not rely on generated notes without human review.

## 6. Troubleshooting
- **503 API key not configured:** set `OPENAI_API_KEY` in `.env` locally or the hosting provider's environment settings.
- **401/429 from OpenAI:** verify the replacement key, API access, billing, and project limits.
- **Microphone not working:** allow microphone access, use HTTPS when deployed, or upload an audio file.
- **Audio too large:** shorten the recording or reduce its size; default limit is 25 MB.
- **No speech found:** use clearer audio with less background noise.

## Suggested next iteration
Add login, consent capture, role-based access, encrypted storage, audit logs, automatic deletion, clinician review/approval, and an explicit retention policy before any real clinical pilot.
