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

## 🏗️ Current Pipeline and Django → FastAPI / GCP Migration Blueprint

This section describes the pipeline that exists in this repository and the target architecture for a controlled migration. **BigQuery and FastAPI are not implemented in the current codebase yet.** The target below is a design and rollout plan, not a claim that those services are already deployed.

### 1. Current system at a glance

```text
       CURRENT DJANGO APPLICATION
┌──────────────────────────────────────────────────────────────────────────────┐
│ Browser                                                                      │
│  Landing / Login / Dashboard / Scraper / Extractor / Pitch / Generator      │
└─────────────────────────────────┬────────────────────────────────────────────┘
          │ Django URLs + session authentication
          v
┌──────────────────────────────────────────────────────────────────────────────┐
│ Cloud Run Django container                                                   │
│                                                                              │
│  dashboard.views        scraper.views/services       extractor.views        │
│  ai_agent_pitch.views   pitch_generator.views       middleware/decorators   │
└──────────┬──────────────────────┬──────────────────────┬─────────────────────┘
     │                      │                      │
     v                      v                      v
   PostgreSQL / Django ORM       GCS JSON + CSV       Google Sheets
   users, campaigns,             contacts/{user_...}  supplier / pitch /
   recipients, templates,        scraper_runs/...     LinkedIn exports
   GmailSettings, LeadPitch
     │                      │                      │
     └──────────────┬───────┴──────────────┬───────┘
        v                      v
      Gemini AI / SerpAPI       Gmail SMTP / IMAP

Scheduled path:
Cloud Scheduler -> /app/scraper/scheduler/run/ -> run_daily_scrape()
      -> SerpAPI -> Gemini -> GCS + Sheets -> progress/stats in GCS
```

### 2. Current request and data flows

#### Authenticated dashboard flow

```text
GET /app/
   │
   ├─ LoginRequiredMiddleware / @login_required
   ├─ dashboard.views.home(request.user)
   ├─ list_contacts(category, request.user)
   │      └─ GCS prefix: contacts/user_{id}_{category}/
   └─ dashboard/index.html renders counts and tabs

Browser AJAX
   ├─ /app/api/contacts/list/   -> list only the current user's category
   ├─ /app/api/contacts/add/    -> validate -> deterministic uid -> GCS upsert
   ├─ /app/api/contacts/upload/ -> user-prefixed CSV object in GCS
   ├─ /app/api/contacts/delete/ -> delete only current user's object
   └─ /app/api/gmail/*          -> encrypted Gmail App Password in Cloud SQL
```

#### Scraper flow

```text
User searches profile/domain
  │
  v
SerpAPI search or profile lookup
  │
  v
Gemini analysis + pitch generation
  │
  ├─ interactive response to scraper UI
  ├─ local CSV compatibility path
  ├─ GCS contact upsert: contacts/user_{id}_linkedin/{uid}.json
  └─ Google Sheets append/update when configured

Scheduled keyword/location run
  │
  v
resolve explicit user, otherwise DEFAULT_EMAIL_OWNER_USERNAME
  │
  v
scrape_keyword() -> analyze each profile -> save contact -> save run JSON
  │
  └─ scraper_runs/{date}/{keyword[-location]}.json + progress/stat objects
```

#### Pitch and campaign flow

```text
Pitch Generator: POST /app/generator/create/
  -> SerpAPI research -> Gemini generation -> LeadPitch(user=request.user)
  -> optional Google Sheets export -> result/{pitch_id}/

Campaign Manager: POST /app/pitch/
  -> parse CSV or recipient list -> validate email addresses
  -> EmailTemplate/Campaign/Recipient rows owned by request.user
  -> resolve user's Gmail settings or configured owner sender
  -> SMTP send -> opened tracking updates Recipient.status/opened_at
  -> dashboard and campaign detail pages
```

### 3. Current UI feature contract to preserve

The migration is complete only when the following browser-visible behavior remains available:

| UI area | Existing behavior | FastAPI migration contract |
|---|---|---|
| Authentication | Login, signup, password reset, session redirects | Keep the same browser flow; FastAPI validates the same identity and issues a secure session cookie or short-lived token |
| Dashboard | Per-user contact counts, category tabs, add/edit/delete, CSV upload/download | Keep the existing JSON shapes initially; replace GCS list scans with indexed Cloud SQL queries |
| AI Auto Scraper | Profile/domain search, Gemini analysis, pitch generation, live progress | Return a job id; poll or stream progress; persist every result with `tenant_id` |
| Scheduled scraper | Keyword/location configuration, run-now, runs, stats, scheduler secret | Cloud Scheduler -> authenticated FastAPI job endpoint -> Cloud Run Job/worker |
| Extractor | Owner-only supplier search, CSV export, Google Sheets sync | Preserve owner authorization as a role/policy, not a username-only check |
| Pitch Generator | Research, nine generated outputs, history, Google Sheets export | Synchronous request for small work; queued job for slow research/generation |
| Campaign Manager | HTML editor, templates, AI enhancement, subject generation, send, open tracking | FastAPI command endpoints plus background delivery workers; preserve campaign detail/dashboard views |
| Gmail settings | Per-user connected account, encrypted App Password, connection test | Store ciphertext in Cloud SQL or Secret Manager; never return plaintext |
| Diagnostics | `/app/api/diagnostics/` reports configuration and integration health | Add `/api/v1/health/ready` and `/api/v1/health/integrations`; expose presence and status only |
| Error handling | Branded HTML pages and JSON error payloads | Keep a stable `{success:false,error,request_id}` error envelope and server-side trace logging |

### 4. Target GCP architecture

```text
              ┌──────────────────────────┐
              │ Cloud Load Balancer/WAF   │
              └────────────┬─────────────┘
               v
┌──────────────────────┐     ┌─────────────────────────────────────────────┐
│ Existing templates   │────>│ FastAPI API on Cloud Run                    │
│ and static UI        │     │ /api/v1/auth /contacts /scrapes /campaigns  │
└──────────────────────┘     └──────┬──────────────┬───────────────┬────────┘
            │              │               │
           SQLAlchemy       Cloud Tasks      Pub/Sub
            + asyncpg      (user commands)   (events)
            │              │               │
            v              v               v
         ┌────────────────┐ ┌─────────────┐ ┌──────────────┐
         │ Cloud SQL      │ │ Cloud Run    │ │ BigQuery     │
         │ PostgreSQL     │ │ workers/jobs │ │ facts/events │
         │ source of truth│ └──────┬──────┘ └──────┬───────┘
         └───────┬────────┘        │               │
           │                 v               v
           │          Gemini / SerpAPI   BI / reports
           v
         ┌────────────────┐
         │ Cloud Storage  │  raw CSV, JSON, HTML,
         │ private bucket │  exports, scrape archives
         └────────────────┘

     Secret Manager: Django/FastAPI secret, DB password, API keys, Fernet key
     Cloud Scheduler: daily scrape trigger
     Cloud Logging + Trace: request_id, job_id, tenant_id (never secret values)
```

### 5. Storage boundary: what belongs where

| Data | Primary store | Reason |
|---|---|---|
| Users, roles, tenant membership | Cloud SQL | Transactions, constraints, authentication joins |
| Contacts and deduplication keys | Cloud SQL | Fast dashboard CRUD and unique `(tenant_id, category, external_uid)` |
| Campaigns, recipients, templates, opens | Cloud SQL | Transactional send state and row-level ownership |
| Gmail connection metadata | Cloud SQL + Secret Manager where possible | Encrypted operational secret; never BigQuery |
| Scrape jobs, keywords, locations, job status | Cloud SQL | Reliable state machine and retry ownership |
| Raw profile payloads, CSV, generated HTML, large prompts | GCS | Cheap object storage and lifecycle policies |
| Contact/campaign/scrape analytics | BigQuery | Aggregation, time-series reporting, partition pruning |
| Audit and product events | BigQuery | Append-only history and low-cost analysis |
| Google Sheets | Export/integration only | Human sharing and compatibility, not the system of record |

**Important:** BigQuery should not be used for dashboard CRUD, authentication, campaign sending, or per-request contact lookup. Those operations need Cloud SQL transactions and predictable low latency.

### 6. Multi-user data model and isolation rules

Introduce a stable `tenant_id` (workspace/account) even if the first version maps one user to one tenant. Every business table must carry `tenant_id`; `user_id` identifies the actor/owner.

```text
tenant
  ├─ tenant_member(tenant_id, user_id, role)
  ├─ contact(tenant_id, owner_user_id, category, external_uid, ...)
  ├─ pitch(tenant_id, created_by_user_id, ...)
  ├─ campaign(tenant_id, created_by_user_id, ...)
  ├─ recipient(tenant_id, campaign_id, ...)
  ├─ scrape_job(tenant_id, requested_by_user_id, ...)
  └─ gmail_connection(tenant_id, user_id, encrypted_secret_ref, ...)
```

Required controls:

1. Resolve the tenant from the authenticated identity on the server. Never accept `tenant_id`, `user_id`, or a GCS prefix from the browser as authority.
2. Apply tenant filters in repository/service functions, not only in route handlers. Add PostgreSQL Row-Level Security as a second control where practical.
3. Replace current `user_{id}` object paths with opaque tenant UUIDs: `tenants/{tenant_uuid}/contacts/{category}/{contact_uuid}.json`.
4. Use roles such as `owner`, `member`, and `admin`; preserve extractor access as an explicit permission (for example `extractor.manage`) rather than a hard-coded username.
5. Use object-level authorization for campaign, pitch, recipient, and file ids. A valid id alone must never reveal another tenant's record.
6. Keep secrets out of BigQuery, logs, analytics events, and client responses. Rotate service-account and API credentials through Secret Manager.

### 7. Efficient Cloud SQL and BigQuery write strategy

#### Cloud SQL

```text
API request -> validate command -> one transaction -> commit
              │
              ├─ upsert contact using unique tenant key
              ├─ create outbox event in same transaction
              └─ return normalized resource/job response

Worker -> read outbox rows with FOR UPDATE SKIP LOCKED
       -> publish event / mark delivered
       -> retry with exponential backoff and dead-letter state
```

- Use connection pooling with a bounded pool sized for Cloud SQL and Cloud Run concurrency; do not create a database connection per request.
- Add composite indexes for actual access patterns, for example `(tenant_id, category, updated_at DESC)` and `(tenant_id, external_uid)`.
- Use keyset pagination rather than large `OFFSET` scans.
- Batch contact inserts/upserts in one transaction for CSV and scraper results.
- Keep request transactions short; AI calls, SMTP, Sheets, and GCS uploads belong in jobs, not inside a database transaction.
- Use an outbox table so a successful SQL write cannot silently lose its analytics event.

#### BigQuery

Recommended logical tables:

```text
analytics.contact_events
analytics.scrape_events
analytics.campaign_events
analytics.ai_usage_events
analytics.api_request_events
```

- Append immutable events with `event_id`, `occurred_at`, `tenant_id`, `actor_user_id`, `event_type`, `entity_id`, and a typed `payload`.
- Partition by `DATE(occurred_at)` and cluster by `tenant_id, event_type`; query with both filters whenever possible.
- Use the BigQuery Storage Write API or batched Pub/Sub ingestion for events. Avoid one BigQuery query per button click.
- For scraper batches, write newline-delimited JSON to GCS and load in batches, or publish one event per profile through Pub/Sub. Do not stream huge nested blobs into repeated SQL updates.
- Deduplicate with `event_id` and an ingestion table; design consumers to be idempotent because delivery is at-least-once.
- Apply BigQuery row-level security or authorized views for tenant-scoped analysts and service accounts.
- Set partition expiration for high-volume raw events and keep curated rollups longer.

### 8. FastAPI endpoint shape

Keep the first API version boring and compatible with the current UI. A thin compatibility layer can translate the existing `/app/api/...` calls while the UI is migrated incrementally.

```text
/api/v1/auth/me
/api/v1/contacts?category=linkedin&cursor=...
/api/v1/contacts                 GET/POST
/api/v1/contacts/{contact_id}    PATCH/DELETE
/api/v1/files                    upload metadata / signed URL
/api/v1/scrapes/search           SerpAPI lookup
/api/v1/scrapes/analyze          create analysis job
/api/v1/scrapes/jobs/{job_id}    status and progress
/api/v1/pitches                  create/list/view
/api/v1/campaigns                create/list/view/send
/api/v1/campaigns/{id}/events    open/click tracking
/api/v1/gmail                     connection status/test/update
/api/v1/diagnostics               non-secret integration health
```

Suggested service layers:

```text
routers -> dependencies/auth -> application services -> repositories
              │                    │
              ├─ job publisher      └─ Cloud SQL
              ├─ event publisher
              └─ GCS signer / AI gateway
```

Keep Pydantic schemas separate from SQLAlchemy models. Validate all external payloads, return stable error codes, and include a `request_id` in every response and log record.

### 9. Migration sequence with rollback points

```text
[0] Baseline       inventory routes, UI payloads, models, GCS objects, Sheets columns
       |
[1] Tenant prep    add tenant/member tables and tenant_id columns in Django
       |            backfill current users; add ownership tests and indexes
       |
[2] Cloud SQL      make SQL the contact source of truth; retain GCS as file/archive layer
       |            dual-read or compare GCS counts during a verification window
       |
[3] Event spine    add outbox + Pub/Sub + BigQuery datasets; replay historical events
       |            compare SQL aggregates with BigQuery reports
       |
[4] FastAPI        deploy /api/v1 beside Django; route one feature at a time
       |            keep Django templates and compatibility endpoints working
       |
[5] Async work     move AI, scraping, SMTP, Sheets and exports to Cloud Tasks/Jobs
       |            show job status in the existing UI
       |
[6] Cutover        switch UI calls by feature flag; monitor latency, errors, isolation
       |            and event lag; retain Django rollback routes temporarily
       |
[7] Retirement     remove duplicate writes and old routes only after reconciliation
```

At every stage, record a migration marker and reconcile counts by tenant/category/date. A rollback should disable the feature flag or route traffic back to the Django endpoint; it should not require deleting Cloud SQL or BigQuery data.

### 10. Definition of done and operational checks

- Two test users can never list, download, update, delete, or infer each other's contacts, files, pitches, campaigns, or Gmail settings.
- A scraper retry produces one logical contact and idempotent analytics events, not duplicates.
- A failed Gemini, SerpAPI, SMTP, Sheets, or GCS call produces a visible job failure and retry state without holding a SQL transaction open.
- Dashboard contact lists use indexed Cloud SQL queries and cursor pagination; no per-category GCS full-prefix scan occurs on every page load.
- BigQuery reports are partition-pruned, tenant-filtered, and reconciled against Cloud SQL totals.
- Cloud Run metrics cover request latency, DB pool saturation, job age, Pub/Sub backlog, BigQuery ingestion lag, and per-tenant error rate.
- `/api/v1/diagnostics` checks Cloud SQL, GCS, Pub/Sub, BigQuery, Secret Manager, Gemini, SerpAPI, Sheets, and Gmail without exposing values.
- CI covers tenant authorization, idempotency, migration backfill, API compatibility, and the critical UI flows listed above.

## 🔌 SQL Connect Local Development Setup

This project currently runs Django with PostgreSQL. The workflow below adds Firebase SQL Connect for local schema and API experimentation; it does **not** replace the current Django database automatically. SQL Connect's local emulator uses an embedded PGlite database, while the production design in this README uses Cloud SQL PostgreSQL as the transactional source of truth.

### What this setup provides

```text
Local development
  VS Code + SQL Connect extension
  │
  ├─ Firebase project authentication
  ├─ Firebase project connection
  ├─ firebase init configuration
  └─ Start emulators
     │
     v
  SQL Connect emulator + PGlite
     │
     ├─ local schema/model iteration
     ├─ local queries and generated connectors
     └─ isolated test data (not production data)

Existing application path                         Future migration path
  Django UI -> Django ORM -> PostgreSQL      FastAPI/UI -> SQL Connect API
               │
               v
               Cloud SQL PostgreSQL
```

### 1. Install prerequisites

Install the following tools before opening the SQL Connect workflow:

| Tool | Installation |
|---|---|
| Visual Studio Code | [Download VS Code](https://code.visualstudio.com/download) and complete the installer |
| Node.js | Install through [nvm-windows](https://github.com/coreybutler/nvm-windows) on Windows, or [nvm](https://github.com/creationix/nvm/blob/master/README.md) on macOS/Linux |
| Firebase CLI | [Firebase CLI documentation](https://firebaseopensource.com/projects/firebase/firebase-tools/) or `npm install -g firebase-tools` |
| SQL Connect extension | [Install SQL Connect for VS Code](https://marketplace.visualstudio.com/items?itemName=GoogleCloudTools.firebase-dataconnect-vscode) |

#### Windows PowerShell

Install `nvm-windows` first, then open a new PowerShell window:

```powershell
nvm install lts
nvm use lts
node --version
npm --version
npm install --global firebase-tools
firebase --version
```

#### macOS or Linux

Install `nvm`, restart the terminal, then run:

```bash
nvm install --lts
nvm use --lts
node --version
npm --version
npm install --global firebase-tools
firebase --version
```

Use an active LTS Node.js release. If `firebase` is not found after installation, restart the terminal so the npm global binary directory is on `PATH`.

### 2. Create and open a project directory

The SQL Connect files can live in a new directory or in a dedicated subdirectory of this repository. Keeping them separate from the Django source avoids confusing generated Firebase files with Django migrations.

#### Windows PowerShell

```powershell
New-Item -ItemType Directory -Path "$HOME\Documents\ai-pitch-sqlconnect" -Force
Set-Location "$HOME\Documents\ai-pitch-sqlconnect"
code .
```

#### macOS or Linux

```bash
mkdir -p "$HOME/Documents/ai-pitch-sqlconnect"
cd "$HOME/Documents/ai-pitch-sqlconnect"
code .
```

If `code` is not available, open VS Code manually and choose **File > Open Folder**, then select the project directory.

### 3. Install and open SQL Connect in VS Code

1. Open the Extensions view with `Ctrl+Shift+X` on Windows/Linux or `Cmd+Shift+X` on macOS.
2. Search for **SQL Connect** or **Firebase Data Connect**.
3. Install the extension published by Google Cloud/Firebase, or open the [Marketplace listing](https://marketplace.visualstudio.com/items?itemName=GoogleCloudTools.firebase-dataconnect-vscode).
4. Reload VS Code if prompted.
5. Open the SQL Connect/Firebase Data Connect view from the Activity Bar.

The extension supplies the project actions used in the next steps. The exact view label can vary slightly by extension version because Firebase SQL Connect is also presented as Firebase Data Connect.

### 4. Sign in and connect the Firebase project

Use the extension view rather than putting credentials in `.env` files:

1. Click **Sign in with Google**.
2. Complete the browser consent flow using the Google account that has access to the Firebase project.
3. Return to VS Code and click **Connect a Firebase project**.
4. Select an existing Firebase project or create one in the Firebase Console first.
5. Confirm the selected project and verify that its project id is shown in the SQL Connect view.

CLI equivalent for checking authentication:

```bash
firebase login
firebase projects:list
```

Do not commit access tokens, service-account JSON files, or generated local secrets. Add local credential files to `.gitignore` if the Firebase workflow creates them.

### 5. Initialize SQL Connect

Click **Run firebase init** in the extension. When the Firebase CLI prompts for options:

1. Select the connected Firebase project.
2. Select the SQL Connect/Data Connect service when prompted.
3. Accept the suggested service directory unless this repository already has a deliberate Firebase layout.
4. Review the generated configuration before committing it.

The exact generated filenames depend on the Firebase CLI and extension version. Common configuration includes a Firebase project file plus a Data Connect/SQL Connect service directory containing schema, connector, and generated client files.

After initialization, inspect the generated files and confirm that they do not contain production passwords or private keys. Firebase initialization is configuration setup; it does not migrate the Django models, existing PostgreSQL rows, GCS objects, or Google Sheets automatically.

### 6. Start the local SQL Connect emulator

Click **Start emulators** in the SQL Connect view. The extension starts the local SQL Connect emulator with a PGlite database.

```text
VS Code: Start emulators
  │
  v
Firebase emulator process
  │
  v
PGlite local PostgreSQL-compatible database
  │
  ├─ applies the local SQL Connect schema
  ├─ serves local connectors/queries
  └─ stores test data on the developer machine
```

Use the emulator for schema design, connector testing, seed data, and request-response development. It is not a performance benchmark for Cloud SQL and it is not a replacement for production backups, IAM, pooling, monitoring, or tenant isolation.

If the extension exposes a terminal command for the installed version, the equivalent CLI command is generally based on Firebase emulators:

```bash
firebase emulators:start
```

Use the command shown by the extension for the authoritative SQL Connect service flags. Run `firebase --help` and inspect the generated project configuration when the generic command does not include the expected SQL Connect emulator.

### 7. Validate the local setup

Run these checks after the emulator starts:

```bash
node --version
npm --version
firebase --version
firebase projects:list
```

Then verify in VS Code that:

- the correct Firebase project is connected;
- the SQL Connect/Data Connect service is recognized;
- the emulator status is running;
- the local PGlite database accepts the generated schema or connector request;
- test records are visible only in the local emulator;
- stopping and restarting the emulator does not affect Django PostgreSQL, GCS, Cloud SQL, or BigQuery.

### 8. Relationship to this repository's migration

```text
       DATA OWNERSHIP DURING MIGRATION

┌──────────────────────────────┐       ┌──────────────────────────────┐
│ Current Django application   │       │ SQL Connect prototype        │
│                              │       │                              │
│ Django models + PostgreSQL  │       │ schema + connectors + PGlite │
│ GCS contacts and CSV files  │       │ local emulator only           │
│ Sheets exports              │       │                              │
└──────────────┬───────────────┘       └──────────────┬───────────────┘
         │                                      │
         │ compare model and API contracts     │ test locally
         └──────────────────┬───────────────────┘
          v
        ┌──────────────────────────────┐
        │ Migration implementation     │
        │                              │
        │ FastAPI + SQLAlchemy/adapter │
        │ Cloud SQL PostgreSQL         │
        │ Pub/Sub/outbox -> BigQuery   │
        └──────────────────────────────┘
```

Recommended order:

1. Model the future `tenant`, `tenant_member`, `contact`, `pitch`, `campaign`, `recipient`, and `scrape_job` boundaries in SQL Connect locally.
2. Compare the prototype schema with the current Django models and ownership rules.
3. Add tenant-aware Django migrations or a separate backfill process before changing production reads.
4. Implement the FastAPI adapter against Cloud SQL, preserving the existing UI response shapes where practical.
5. Add the outbox/event path to BigQuery only after transactional Cloud SQL writes are correct.
6. Switch one UI feature at a time behind a feature flag; keep the Django route available for rollback.

### Troubleshooting

| Symptom | Check |
|---|---|
| `node` or `npm` is not recognized | Restart the terminal after nvm installation and verify `nvm current`/`nvm list` |
| `firebase` is not recognized | Reinstall with `npm install --global firebase-tools`, then restart the terminal |
| No Firebase projects appear | Run `firebase login`, use the account with project access, then run `firebase projects:list` |
| **Connect a Firebase project** is unavailable | Confirm the SQL Connect extension is installed and VS Code has been reloaded |
| Emulator will not start | Stop stale emulator processes, inspect the extension output panel, and verify the generated Firebase configuration |
| PGlite data differs from Django data | Expected: PGlite is a separate local database; seed or import test data explicitly |
| Production data is missing | Expected: local emulators do not read Cloud SQL, GCS, BigQuery, or Google Sheets |
