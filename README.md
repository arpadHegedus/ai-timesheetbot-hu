# Timesheetbot

Chat (or voice) your hours -> Gemini via a LangGraph pipeline extracts structured entries -> review -> emailed via Gmail.

## Dev
```
cp .env.example .env   # fill in keys
docker compose up --build
```
- UI: http://localhost:5173 (Vite HMR) - API docs: http://localhost:8000/docs
- `./backend` and `./frontend` are bind-mounted; edits reload live. `frontend/node_modules` lives in a named volume.
- After changing `requirements.txt` / `package.json`: `docker compose up --build`.

## Keys
- `GEMINI_API_KEY`: https://aistudio.google.com/apikey
- `GMAIL_APP_PASSWORD`: enable 2-Step Verification, then https://myaccount.google.com/apppasswords
- `GOOGLE_CLIENT_ID`: https://console.cloud.google.com/apis/credentials -> Create credentials -> OAuth client ID -> Web application.
  Add `http://localhost:5173` under *Authorized JavaScript origins* (plus your Cloud Run URL later). You may need to configure the OAuth consent screen first (External, add yourself as a test user).
- `ALLOWED_EMAILS`: comma-separated Google accounts allowed in. Anyone else gets 403.
- `SESSION_SECRET`: random string for signing sessions (pre-generated in `.env`).

## Firebase (history)
1. https://console.firebase.google.com -> create a project (Spark/free plan).
2. Build -> Firestore Database -> Create database (production mode; the backend uses a service account so rules don't matter).
3. Project settings -> Service accounts -> Generate new private key -> save as `secrets/firebase.json` (gitignored, mounted read-only at `/secrets`).
4. `docker compose up -d --force-recreate backend`.

Reports are stored at `users/{email}/reports/{id}` as just the raw entries (date/location/hours/category) — a few hundred bytes each. The PDF isn't stored; it's regenerated on the fly from those entries whenever the history drawer opens one.

## Production (Cloud Run)
```
docker build --build-arg VITE_GOOGLE_CLIENT_ID=... -t REGION-docker.pkg.dev/PROJECT/REPO/timesheetbot .
docker run -p 8080:8080 --env-file .env REGION-docker.pkg.dev/PROJECT/REPO/timesheetbot   # local smoke test
```
Deploy with secrets from Secret Manager (`--set-secrets`), not `--set-env-vars`.
