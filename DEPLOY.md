# Deploying Timesheetbot

Full walkthrough: get fresh credentials for every service, run it locally once to confirm
everything works, then deploy to Google Cloud Run.

**Why fresh keys:** the keys currently in your local `.env` were pasted into an AI chat
session while building this app. Treat them as burned and issue new ones below rather than
promoting the old ones to production.

Time estimate: ~45–60 minutes, most of it waiting on Google consoles.

---

## 0. Prerequisites

- A Google account to own the GCP/Firebase project.
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) installed and you've run `gcloud init`.
- Docker Desktop running (for the local smoke test).
- This repo, with `secrets/` and `.env` already gitignored — verify before going further:
  ```
  git check-ignore -v .env secrets/firebase.json
  ```
  Both lines should print a match. If either prints nothing, stop and fix `.gitignore` first.

Pick one GCP project id up front and use it everywhere below, e.g. `timesheetbot-prod`:
```
export PROJECT_ID="timesheetbot-prod"
gcloud projects create "$PROJECT_ID"   # skip if it already exists
gcloud config set project "$PROJECT_ID"
```
Make sure billing is linked to this project (Cloud Run and Firestore both have generous free
tiers, but the project needs a billing account attached to use them): console.cloud.google.com/billing.

---

## 1. Gemini API key

1. Open https://aistudio.google.com/apikey.
2. **Create API key** → choose the project above (or let it create one — if it does, switch
   `PROJECT_ID` above to match, or create the key under your `$PROJECT_ID` explicitly).
3. Copy the key. You'll paste it into `.env` in step 6.

Free-tier quota is per-model and resets daily — that's why `GEMINI_MODELS` in `.env` is a
comma-separated fallback list already; leave it as-is unless you have a reason to change it.

---

## 2. Gmail sending account

Use a real Gmail inbox the app will send *from* (can be a dedicated one, doesn't need to be
your main address).

1. On that Google account: https://myaccount.google.com/security → turn on **2-Step Verification**
   (required for app passwords; skip if already on).
2. https://myaccount.google.com/apppasswords → name it `timesheetbot` → **Create**.
3. Copy the 16-character password (shown once, no spaces needed — Google displays it in groups
   of 4 but it's used as one string).

---

## 3. Google Sign-In (OAuth Client ID)

This lets your whitelisted Google accounts log into the app — it's separate from the Gmail
sending account above.

1. https://console.cloud.google.com/apis/credentials/consent (make sure `$PROJECT_ID` is
   selected in the top bar).
   - User type: **External**.
   - Fill app name, support email, developer contact. Save and continue through scopes
     (none needed) and test users.
   - **Add yourself (and anyone else in `ALLOWED_EMAILS`) as a test user** — while the consent
     screen is unverified/"Testing", only listed test users can sign in. This is fine for an
     internal tool; you don't need to submit for Google verification.
2. https://console.cloud.google.com/apis/credentials → **Create credentials** → **OAuth client ID**
   → Application type **Web application**.
3. Under **Authorized JavaScript origins**, add `http://localhost:5173` for now — you'll add
   the production URL back here in step 9, after the first deploy tells you what it is.
4. **Create** → copy the **Client ID** (looks like `123...apps.googleusercontent.com`).

---

## 4. Firebase (Firestore history)

1. https://console.firebase.google.com → **Add project** → pick **the same `$PROJECT_ID`**
   from the dropdown (Firebase projects are just GCP projects with Firebase enabled — don't
   create a separate one). Skip Google Analytics, you don't need it.
2. Build → **Firestore Database** → **Create database** → production mode → pick a region
   close to you (note it; use the same region for Cloud Run in step 8 to minimize latency).
3. **For local development only:** ⚙️ Project settings → **Service accounts** → **Generate
   new private key** → save the downloaded file as `secrets/firebase.json` in this repo.
   (Production on Cloud Run won't use this file at all — see step 8, which uses the
   service's own identity instead. You still need this key locally to run `docker compose`.)

---

## 5. Session secret

A random string the backend uses to sign login sessions. Generate one:
```
openssl rand -hex 32
```
(or `python3 -c "import secrets; print(secrets.token_hex(32))"` if you don't have openssl).

---

## 6. Fill in `.env` and smoke-test locally

```
cp .env.example .env
```
Edit `.env` with everything gathered above:

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` | from step 1 |
| `GMAIL_USER` | the Gmail address from step 2 |
| `GMAIL_APP_PASSWORD` | the 16-char password from step 2 |
| `REPORT_RECIPIENT` | who should receive the timesheets (their email) |
| `RECIPIENT_NAME` | their first name, used in "Hi ___," |
| `COMPANY_NAME` | printed on the PDF header |
| `EMPLOYEE_NAME` | printed on the PDF and in the email subject |
| `GOOGLE_CLIENT_ID` | from step 3 |
| `ALLOWED_EMAILS` | comma-separated Google accounts allowed to log in (must match your OAuth test users from step 3) |
| `SESSION_SECRET` | from step 5 |

Leave `GEMINI_MODELS` as the default unless you have a reason to change it.

Now run it:
```
docker compose up -d --force-recreate
```
- UI: http://localhost:5173 — sign in, send a chat message, confirm the PDF preview looks
  right, submit it, check the recipient inbox, check the history drawer.
- If anything fails, fix it here before touching Cloud Run — it's much faster to debug locally.

---

## 7. Set up `gcloud` and Artifact Registry

```
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com iam.googleapis.com --project "$PROJECT_ID"

export REGION="europe-west2"   # pick whatever region you chose for Firestore in step 4
gcloud artifacts repositories create timesheetbot \
  --repository-format=docker --location="$REGION" --project "$PROJECT_ID"

gcloud auth configure-docker "${REGION}-docker.pkg.dev"
```

---

## 8. Build, push, and grant Firestore access

Build the image (the Google Client ID is baked into the frontend bundle at build time —
it's not secret, it's meant to be public, so this is safe):
```
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/timesheetbot/app:latest"
docker build --build-arg VITE_GOOGLE_CLIENT_ID="<your GOOGLE_CLIENT_ID from step 3>" \
  -t "$IMAGE" .
docker push "$IMAGE"
```

Create a dedicated, least-privilege service account for the Cloud Run service (instead of
using the downloaded `secrets/firebase.json` key — Cloud Run gets Firestore access through
its own identity, no key file needed in production):
```
gcloud iam service-accounts create timesheetbot-run \
  --display-name "Timesheetbot Cloud Run" --project "$PROJECT_ID"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:timesheetbot-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

Put the real secrets in Secret Manager rather than passing them as plain env vars:
```
gcloud services enable secretmanager.googleapis.com --project "$PROJECT_ID"

printf '%s' "<your GEMINI_API_KEY>"       | gcloud secrets create gemini-api-key       --data-file=- --project "$PROJECT_ID"
printf '%s' "<your GMAIL_APP_PASSWORD>"   | gcloud secrets create gmail-app-password   --data-file=- --project "$PROJECT_ID"
printf '%s' "<your SESSION_SECRET>"       | gcloud secrets create session-secret       --data-file=- --project "$PROJECT_ID"

gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:timesheetbot-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project "$PROJECT_ID"
gcloud secrets add-iam-policy-binding gmail-app-password \
  --member="serviceAccount:timesheetbot-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project "$PROJECT_ID"
gcloud secrets add-iam-policy-binding session-secret \
  --member="serviceAccount:timesheetbot-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project "$PROJECT_ID"
```

Deploy (`--allow-unauthenticated` is intentional — Cloud Run itself stays open, and the app's
own Google Sign-In + email whitelist is what actually gates access). `--min-instances=1` keeps
one instance warm at all times — for a single-digit-user internal tool this costs very little
and eliminates cold-start latency and the startup race described in the troubleshooting section
below:
```
gcloud run deploy timesheetbot \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances=1 \
  --port 8080 \
  --service-account "timesheetbot-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,GMAIL_APP_PASSWORD=gmail-app-password:latest,SESSION_SECRET=session-secret:latest" \
  --set-env-vars="GEMINI_MODELS=gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash,GMAIL_USER=<your Gmail address>,REPORT_RECIPIENT=<recipient email>,RECIPIENT_NAME=<recipient first name>,COMPANY_NAME=<company name>,EMPLOYEE_NAME=<employee name>,GOOGLE_CLIENT_ID=<your GOOGLE_CLIENT_ID>,ALLOWED_EMAILS=<comma-separated allowed emails>" \
  --project "$PROJECT_ID"
```

**On Windows, `cmd.exe` mangles the commas inside `--set-env-vars`.** Skip the single long
flag entirely and use an env file instead — save this as `env.yaml` next to the Dockerfile:
```yaml
GEMINI_MODELS: "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash"
GMAIL_USER: "<your Gmail address>"
REPORT_RECIPIENT: "<recipient email>"
RECIPIENT_NAME: "<recipient first name>"
COMPANY_NAME: "<company name>"
EMPLOYEE_NAME: "<employee name>"
GOOGLE_CLIENT_ID: "<your GOOGLE_CLIENT_ID>"
ALLOWED_EMAILS: "<comma-separated allowed emails>"
```
and replace the `--set-env-vars="..."` line above with `--env-vars-file=env.yaml`. (Also:
`printf` doesn't exist in `cmd.exe` for the Secret Manager commands earlier in this step — use
Git Bash or WSL instead of Command Prompt for every command in this guide; PowerShell's quoting
rules differ too and will cause similar grief.)

Note what it prints — the **Service URL** — you need it next.

---

## 9. Close the loop on Google Sign-In

Back at https://console.cloud.google.com/apis/credentials, open the OAuth client from step 3
and add the Cloud Run Service URL (exactly as printed, including `https://`) to
**Authorized JavaScript origins**. No rebuild needed — this is a console-only setting, checked
by Google at sign-in time, not baked into the app.

---

## 10. Verify the live deployment

1. Open the Service URL. Sign in with a whitelisted account.
2. Send a chat message, confirm the PDF preview looks right (locations, hours, categories).
3. Submit it — check the recipient inbox for the email, and the PDF attachment.
4. Open the history drawer, confirm the just-submitted report is listed and its PDF opens.
5. `gcloud run services logs read timesheetbot --region "$REGION" --project "$PROJECT_ID"`
   if anything looks wrong — the backend logs clearly on auth failures, Gemini errors, and
   email/Firestore failures.

---

## Troubleshooting: intermittent 502 on login (or anything under `/api/`)

**Symptom:** login (or any request) 502s right after the app has been idle, a fresh revision
just rolled out, or traffic just picked up — but works fine once it's "warm." It looks random,
but it's actually deterministic: it depends on whether a request lands inside the container's
startup window or not.

**Cause, confirmed by timing it locally:** the container runs nginx and the Python backend
(`uvicorn`) side by side under `supervisord` with no ordering between them. `uvicorn`'s import
chain (`langgraph`, `google-genai`, `google-cloud-firestore`, …) takes a couple of seconds on a
cold start. Nginx comes up almost instantly and starts accepting connections on port 8080 —
which is also the signal Cloud Run uses to decide the container is "ready" and start routing
real traffic to it — well before `uvicorn` is actually listening on port 8000. Any request that
lands in that gap gets a 502 from nginx (`connection refused` from its upstream). Once `uvicorn`
finishes starting, the same instance works until Cloud Run next cold-starts it — hence "on and
off" rather than consistently broken.

**Fix (already applied in this repo's `Dockerfile`/`supervisord.conf`):** nginx's own startup
now blocks on `uvicorn`'s `/health` endpoint before it binds port 8080 at all, so Cloud Run
won't see the container as ready until the whole stack actually is. If you deployed before this
fix landed, pull the latest code and redo step 8's build/push/deploy.

**This is not the Secret Manager IAM issue** you may have hit earlier while setting this up —
that one fails *consistently* until the IAM binding is fixed, and stays fixed afterward. This
bug is specifically intermittent, tied to cold starts. `--min-instances=1` (in step 8's deploy
command) also mostly sidesteps it in practice, by avoiding scale-to-zero cold starts entirely —
but the real fix is the startup-ordering one above, which also protects the first request after
*any* new revision, even with `--min-instances=1` set.

---

## Updating later

**Code change:** repeat step 8's `docker build` / `docker push` / `gcloud run deploy` three
commands (no need to touch secrets or IAM again).

**Secret value change** (e.g. rotating the Gmail app password): add a new version, then
redeploy with the same `gcloud run deploy` command from step 8 again —
```
printf '%s' "<new value>" | gcloud secrets versions add gmail-app-password --data-file=- --project "$PROJECT_ID"
```
Re-running the same `gcloud run deploy` command creates a new revision, which re-resolves the
`:latest` secret version at deploy time — Cloud Run revisions are immutable once created, so a
secret change alone (without a new revision) will not reach a running container.
