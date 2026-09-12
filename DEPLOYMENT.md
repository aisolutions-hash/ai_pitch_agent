# AI Sales Agent — Cloud Run Deployment Guide (Cloud Shell)

Complete, step-by-step instructions to deploy this repository to Google Cloud Run
from Cloud Shell.

- **Project ID (target):** `Project ID`
- **Repository:** `https://github.com/aisolutions-hash/ai_pitch_agent.git`
- **Branch:** `main`
- **Deploy script to use:** `deploy.sh` (Django app)

---

## 1. Understand what is in the repository

This repo contains **two** applications:

| App | Stack | Deploy script | Status |
|---|---|---|---|
| **AI Sales Agent (main)** | Django (`sales_project`, `extractor`, `scraper`, `dashboard`, `pitch_generator`, `ai_agent_pitch`) | `deploy.sh` + `Dockerfile` + `cloudrun.env.yaml` | **Deploy this now** |
| FastAPI sales pipeline | FastAPI (`sales_fastapi/`) | `deploy_sales.sh` + `Dockerfile.sales` + `cloudbuild.sales.yaml` | Future migration target — **do NOT deploy yet** |

> **Why not `deploy_sales.sh`?** It requires a Cloud SQL Postgres instance
> (`INSTANCE_CONNECTION_NAME` is still a placeholder). The live Django app uses
> an external **Neon PostgreSQL** database, which is already configured in
> `cloudrun.env.yaml`. Deploying the FastAPI pipeline without a real Cloud SQL
> instance will fail.

---

## 2. Prerequisites

- A Google Cloud account with billing enabled.
- Owner/editor access to project `gen-lang-client-0132243782`.
- The following service credentials (explained in §4):
  - Google Sheets / GCS service-account key: `credentials.json`
  - The env config file: `cloudrun.env.yaml`
- `gcloud` CLI (pre-installed in Cloud Shell).

---

## 3. Files you must have ready

These two files are **gitignored** and **dockerignored** — they are NOT in the
GitHub repository and are NOT baked into the Docker image. You must upload them
manually to Cloud Shell and keep them out of git.

| File | Purpose | Where it lives at runtime |
|---|---|---|
| `cloudrun.env.yaml` | All app env vars (`DB_*`, API keys, Gmail/SMTP, Sheets IDs, etc.) | Passed to Cloud Run via `--env-vars-file` |
| `credentials.json` | Google service-account JSON (Sheets + GCS access) | Pushed to **Secret Manager** as `google-app-credentials`, mounted as `GOOGLE_CREDENTIALS_JSON` |

`deploy.sh` errors out if either file is missing, so prepare both first.

---

## 4. Prepare: `cloudrun.env.yaml`

1. Start from the committed template:

   ```bash
   cp cloudrun.env.yaml.example cloudrun.env.yaml
   ```

2. Or upload your existing file (recommended — it already contains working values).
   The current working file includes:

   ```yaml
   DJANGO_SECRET_KEY: "..."            # REQUIRED - was missing before, added
   GCS_BUCKET_NAME: "kalisoft-contacts"
   DJANGO_DEBUG: "false"
   ALLOWED_HOSTS: ".run.app"
   APP_USERNAME: "kalisoftai"
   APP_PASSWORD: "..."
   DEFAULT_EMAIL_OWNER_USERNAME: "kalisoftai"
   DB_NAME: "neondb"
   DB_USER: "neondb_owner"
   DB_PASSWORD: "..."
   DB_HOST: "...neon.tech"
   DB_PORT: "5432"
   DB_SSLMODE: "require"
   GEMINI_API_KEY: "..."
   SERPAPI_API_KEY: "..."
   API_KEYS: "..."
   GCS_PROJECT_ID: "gen-lang-client-0681178392"
   GOOGLE_SHEET_ID: "..."
   LINKEDIN_SHEET_ID: "..."
   PITCH_SHEET_ID: "..."
   SCHEDULER_SECRET: "..."
   EMAIL_USER: "..."
   EMAIL_PASS: "..."
   IMAP_SERVER: "imap.gmail.com"
   PITCH_EMAIL_HOST_USER: "..."
   PITCH_GMAIL_APP_PASSWORD: "..."
   DEFAULT_FROM_NAME: "KalisoftAI"
   ```

3. Mandatory checks before deploying:

   - **`DJANGO_SECRET_KEY` is present.** Without it Django falls back to
     `change-me-in-production` (works, but insecure and signs sessions with a
     fixed key).
   - No **duplicate keys** (YAML last-wins or errors — the old file had
     `GCS_BUCKET_NAME` twice; it was cleaned up).
   - **`GCS_PROJECT_ID`** should match the project that owns `credentials.json`
     (currently `gen-lang-client-0681178392`). GCS/Sheets access is governed by
     the service account, not by the Cloud Run deploy project.

4. After the **first** deploy, come back and fill in the Cloud Run URL
   (see §8):

   ```yaml
   CSRF_TRUSTED_ORIGINS: "https://sales-agent-xxxx.a.run.app"
   SITE_URL: "https://sales-agent-xxxx.a.run.app"
   ```

5. **Never commit this file.** It contains live secrets. It is already in
   `.gitignore` (`cloudrun.env*`) and `.dockerignore`.

---

## 5. Prepare: `credentials.json`

- A Google service-account key with access to:
  - The GCS bucket `kalisoft-contacts` (read/write).
  - The Google Sheets referenced by `GOOGLE_SHEET_ID`, `LINKEDIN_SHEET_ID`,
    `PITCH_SHEET_ID` (share the sheets with the service-account email).
- Download the JSON from the GCP Console:
  `IAM & Admin → Service Accounts → your SA → Keys → Add key → JSON`.
- Keep it out of git: it is already in `.gitignore` and `.dockerignore`.

`deploy.sh` uploads it to Secret Manager automatically:

```bash
# if the secret doesn't exist yet:
gcloud secrets create google-app-credentials --data-file=credentials.json
# if it exists (re-deploy): adds a new version
gcloud secrets versions add google-app-credentials --data-file=credentials.json
```

---

## 6. Push the deploy script changes

`deploy.sh` was updated for this project:

- Defaults `PROJECT_ID` to `gen-lang-client-0132243782` (overridable via
  `GOOGLE_CLOUD_PROJECT`).
- Removed the broken `.env → YAML` converter; the script now requires the YAML
  file directly.
- Header notes explicitly that `deploy_sales.sh` is for the FastAPI/Cloud SQL
  path and should not be used here.

`deploy.sh` IS tracked by git, so commit and push it (the two credential files
must NOT be pushed):

```bash
git add deploy.sh
git commit -m "chore: point deploy.sh at cloud run project and simplify env handling"
git push origin main
```

---

## 7. Deploy from Cloud Shell

### 7.1 Open Cloud Shell and set the project

```bash
gcloud config set project gen-lang-client-0132243782
gcloud config get-value project   # verify: gen-lang-client-0132243782
```

### 7.2 Clone the repository

```bash
git clone https://github.com/aisolutions-hash/ai_pitch_agent.git
cd ai_pitch_agent
git checkout main
git pull origin main
```

### 7.3 Upload the credential files

Use the Cloud Shell toolbar menu (**⋮ → Upload file**) to upload, into
`~/ai_pitch_agent/`:

1. `cloudrun.env.yaml`
2. `credentials.json`

Verify both landed in the project root:

```bash
ls -la cloudrun.env.yaml credentials.json
```

### 7.4 Run the deploy script

```bash
chmod +x deploy.sh
bash deploy.sh
```

What the script does, in order:

1. Resolves `PROJECT_ID` (default `gen-lang-client-0132243782`).
2. Verifies `gcloud` is installed and `cloudrun.env.yaml` exists.
3. Enables required APIs (idempotent):
   `run`, `cloudbuild`, `artifactregistry`, `secretmanager`, `storage`,
   `sheets`, `drive`.
4. Pushes `credentials.json` to Secret Manager as `google-app-credentials` and
   grants the Cloud Run runtime service account
   `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com` the role
   `roles/secretmanager.secretAccessor`.
5. Creates the Artifact Registry repository `cloud-run-source-deploy`
   (us-central1) if missing.
6. Builds + pushes the image:
   `gcr`/`run` image `us-central1-docker.pkg.dev/gen-lang-client-0132243782/cloud-run-source-deploy/sales-agent`.
7. Deploys the Cloud Run service **`sales-agent`** with:
   - `--platform managed --region us-central1`
   - `--allow-unauthenticated` (public entry; app login still protects pages)
   - `--memory 1Gi --cpu 1 --timeout 600`
   - `--no-cpu-throttling` (keeps background scrape/campaign threads alive)
   - `--env-vars-file cloudrun.env.yaml`
   - `--set-secrets GOOGLE_CREDENTIALS_JSON=google-app-credentials:latest`
8. Prints the service URL and post-deploy checklist.

### 7.5 Re-run once for the service URL

Cloud Run URLs are `https://sales-agent-<random-hash>.<region>.run.app` and the
hash is only known after the first deploy. Because `CSRF_TRUSTED_ORIGINS` and
`SITE_URL` depend on that URL:

```bash
bash deploy.sh        # second run picks up the new values
```

---

## 8. Post-deploy steps

### 8.1 Get the service URL

```bash
gcloud run services describe sales-agent \
  --region us-central1 \
  --format='value(status.url)'
```

### 8.2 Add the URL to the env file

Edit `cloudrun.env.yaml` (Cloud Shell editor or `nano`):

```yaml
CSRF_TRUSTED_ORIGINS: "https://sales-agent-xxxx.a.run.app"
SITE_URL: "https://sales-agent-xxxx.a.run.app"
```

- `CSRF_TRUSTED_ORIGINS` — required so login/CSRF form POSTs succeed over HTTPS.
- `SITE_URL` — used for password-reset email links.
- `ALLOWED_HOSTS` can stay `.run.app` (accepts every `.run.app` subdomain).

### 8.3 Redeploy so the new env takes effect

```bash
bash deploy.sh
```

### 8.4 Verify with diagnostics

1. Open `https://sales-agent-xxxx.a.run.app/login/` and sign in as `kalisoftai`.
2. Open `https://sales-agent-xxxx.a.run.app/app/api/diagnostics/`.
3. The report shows:
   - `env` — presence of required vars (`DJANGO_SECRET_KEY`, `DB_*`,
     `GEMINI_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, Sheet IDs, GCS vars, etc.)
   - `checks` — `database` (user count), `gcs` (bucket blobs), `sheets` (opens
     the configured sheet), `gemini` (models visible)
   - `overall_ok` — boolean summary
4. Fix anything marked `env missing` or `ok: False`, then re-run `bash deploy.sh`.

---

## 9. Updating the app later

```bash
# on your machine
git add -A && git commit -m "feat: your change"
git push origin main

# Cloud Shell
git pull origin main
bash deploy.sh
```

New revisions only need `bash deploy.sh` — the env file and credentials/
secret is reused.

---

## 10. Rollback

Cloud Run keeps previous revisions:

```bash
gcloud run services update-traffic sales-agent \
  --to-revisions=sales-agent-<REVISION>=100 \
  --region us-central1
```

List revisions:

```bash
gcloud run revisions list --service sales-agent --region us-central1
```

---

## 11. Common problems and fixes

| Symptom | Fix |
|---|---|
| `ERROR: cloudrun.env.yaml not found` | Upload the file to `~/ai_pitch_agent/` (Cloud Shell ⋮ → Upload) |
| `ERROR: credentials.json missing AND no existing secret` | Upload `credentials.json`, or create the secret manually once |
| Login page loads but login POST fails (CSRF / 403) | Set `CSRF_TRUSTED_ORIGINS` to the service URL, redeploy |
| `/app/api/diagnostics/` shows `GOOGLE_CREDENTIALS_JSON` missing | Secret not mounted — check Secret Manager access for the runtime SA and re-deploy so `--set-secrets` applies |
| GCS check `ok: False` | Share bucket `kalisoft-contacts` with the service account in `credentials.json` |
| Sheets check `ok: False` | Share `GOOGLE_SHEET_ID` / `LINKEDIN_SHEET_ID` / `PITCH_SHEET_ID` with the service-account email |
| Database check `ok: False` | Verify `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_SSLMODE=require` (Neon is reachable over the internet) |
| `--allow-unauthenticated` = public | Intended: the home/login page is public; all `/app/*` pages are protected by `LoginRequiredMiddleware` + per-owner access controls |
| `bash deploy.sh` on Windows PowerShell | Use Git Bash / WSL / Cloud Shell, or the provided `deploy_sales.ps1` counterpart for the FastAPI path only |

---

## 12. Security notes

- **Never** commit `cloudrun.env.yaml`, `credentials.json`, `.env`, or any file
  containing real passwords/API keys. They are gitignored and dockerignored.
- Rotate keys via Secret Manager:
  `gcloud secrets versions add google-app-credentials --data-file=credentials.json`
  then redeploy. Old versions are retained until you destroy them.
- The exposed `DJANGO_SECRET_KEY` in the env file signs sessions — rotate it to
  any long random string when desired (invalidates active sessions).
- The config currently uses `APP_PASSWORD` (the admin app password) directly in
  the env file — move it to Secret Manager (`--set-secrets`) for tighter
  control if this app is shared with other developers.