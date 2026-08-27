# AI Sales Agent 🚀

A powerful Django-based web application that automates the entire B2B sales pipeline — from supplier discovery and email extraction to AI-powered pitch generation and tracked email campaign delivery.

---

## 🛡️ Authentication & Session Security

### Owner-Only Access Control
- **Extractor app** (`/app/search/`) is **visible and accessible only** to the `kalisoftai` user (via `DEFAULT_EMAIL_OWNER_USERNAME`).
- Non-authenticated users are redirected to `/login/`.
- Other users receive a friendly **403 Access Denied** page (logged server-side, no internals exposed to user).
- Dashboard sidebar and top nav links automatically hide for non-owners via the `IS_APP_OWNER` context flag.
- `@owner_required` decorator applied to all extractor views (`search`, `download_csv`, `sync_all_to_google_sheet`).

### Friendly Error Pages (poore app maine)
- **Any unhandled error** across the app shows a branded KalisoftAI error page with **"Our technical team has been notified and will resolve this issue as soon as possible."**
- **API calls** → JSON payload `{success: false, error: "Our team has been notified..."}` so toasts remain functional.
- **Pages** → Full-screen branded template with "Go to Dashboard" / "Try Again" buttons.
- **Real tracebacks** are logged server-side (visible only to the team), never shown to the user.
- Decorator `owner_required` in `sales_project/decorators.py` gives identical behavior in DEBUG and production.

### Diagnostic Endpoint
- **`/app/api/diagnostics/`** (login required) returns a JSON report:
  - `env` map of required keys presence (e.g. `DJANGO_SECRET_KEY`, `GEMINI_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, DB vars, etc.)
  - `checks`: `database` (user count), `gcs` (blob count under `user_1_linkedin`), `sheets` (opened sheet title), `gemini` (models visible)
  - `overall_ok` boolean
- Helps instantly identify what's missing on a deployed Cloud Run revision without guessing.

### CPU Throttling Fix
- Deploy script now passes `--no-cpu-throttling` to `gcloud run deploy`, keeping background scrape/campaign threads alive between requests.

---

## 📧 Gmail Settings & SMTP
- **Gmail Accounts** connected via App Passwords (not raw passwords).
- **SMTP config**: `smtp.gmail.com:587` with `EMAIL_USE_TLS=True` + `use_tls=False` override (fixes `ValueError` on Cloud Run).
- **Diagnostics** verify Sheets/Gemini/DB connectivity on every deploy.
- **Add Contact** functionality now works in both **LinkedIn Contacts** and **Campaign Contacts** sections — flat payload accepted, uid auto-derived from linkedin slug, storage failure surfaces as toast instead of silent zero.

---

## 📦 LinkedIn Scraped Contacts → GCS + Google Sheets
- Scraper now **actually saves to GCS** in addition to Sheets.
- Three call sites fixed (`scraper/views.py:237`, `scraper/views.py:406`, `scraper/services.py:524`) — all pass `user=request.user` (or resolved owner for scheduler).
- `gcs_saved` counter added to scrape summary; `gcs_saved >= 1` verified in mock test.
- GCS client cached per process (cold-start performance).
- Deduplication: same linkedin_url → same uid → upsert (no duplicates).

---

## 📬 Add Contact Functionality
- **Flat payload** `{category, name, company, email, phone, linkedin_url, website, tags, notes}` accepted.
- `uid` auto-derived: from `linkedin_url` slug (deterministic, dedupe) or `slug(name) + short hash`.
- Backward compatible: legacy `{category, uid, data:{...}}` format still works.
- Validation: name required, category validated against `('linkedin','suppliers','buyers','events')`.
- Storage failure → **502** with message + toast on frontend (`Could not load contact counts` / `Contact added successfully`).
- Success → modal closes, category list + counts refresh immediately; error → toast appears.

---

## 📦 Supplier Extractor (Access Control)
- **Extractor** (`/app/search/`) **visible/accessible only** to `kalisoftai`.
- Three views decorated `@owner_required` (`search_view`, `download_csv`, `sync_all_to_google_sheet`).
- Nav links in both `templates/base.html` and `templates/dashboard/base.html` hide for non-owners via `{% if IS_APP_OWNER %}`.
- `IS_APP_OWNER` injected by `sales_project.context_processors.app_flags`.

---

## 📦 Deployment Checklist (Cloud Run)
```bash
# 1. Local commit & push
git add -A && git commit -m "feat: owner access + add contact + scraper GCS"
git push origin main

# 2. Cloud Shell
gcloud auth login
gcloud config set project <PROJECT_ID>

# 3. Config files (upload via Cloud Shell ⋮ → Upload)
#    - cloudrun.env.yaml  (copy from .example, fill real values)
#    - credentials.json   (upload the service-account key)

# 4. Deploy
./deploy.sh

# 5. Post-deploy verification
#    Open http://<url>/app/api/diagnostics/ while logged in as kalisoftai
#    Fix any `env missing` or `checks.ok: False` items, then re-deploy:
#      ./deploy.sh   (second run picks up the new ALLOWED_HOSTS / SITE_URL)
```

---

## 📦 Core Features (as documented)
- **Email Supplier Extractor** (`/search/`) — IMAP + Gemini AI + Google Sheets sync + CSV export.
- **AI Email Campaign Manager** (`/pitch/`) — HTML editor, AI enhancement, subject generator, open tracking, dashboard.
- **AI Pitch Generator** (`/generator/`) — SerpAI research, 9-output pitch, auto-export to Google Sheet.
- **Post-deploy**: `./deploy.sh` → verify with `/app/api/diagnostics/`.

---
*AI Sales Agent — B2B Sales Workflow with AI*