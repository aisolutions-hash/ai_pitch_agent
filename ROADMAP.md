# Kalisoft AI Sales Pipeline — Roadmap & Prototype

A FastAPI sales pipeline that ingests contacts (GCS + manual), segregates them by
**domain / intent / context**, extracts email & LinkedIn signal via **IMAP + SMTP**,
and prepares **WhatsApp (now) → Reddit/LinkedIn (next)** outreach. Secured with
**Google Sign-In**, run on **Cloud Run**, backed by **Postgres** (local → Cloud SQL)
and **Redis** for the cron/voice queue.

> Status: working prototype — 24 backend tests green.

---

## 1. ASCII Flow Diagram

```
                                  ┌─────────────────────────────────────────────┐
                                  │                 SOURCES                     │
                                  │                                             │
   GCS bucket                     │  gs://kalisoftai-datahub/                   │
   kalisoftai-datahub/            │     all-sales-contacts-data/                │
   ┌──────────────────┐          │     (*.xlsx, *.csv, *.vcf, *.json)          │
   │ all-sales-       │          └───────────────┬─────────────────────────────┘
   │ contacts-data/   │◄── ADC ─────────────────┘
   │  packvision.xlsx │                          │
   │  VCFcontacts.vcf │          ┌───────────────▼───────────────┐
   │  company.xlsx    │          │  FastAPI  /api/contacts        │
   └──────────────────┘          │   • import/gcs (parse+dedupe)  │
            ▲                    │   • manual add                 │
            │ upload mirror      └───────────────┬───────────────┘
            │                                    │
   ┌────────┴─────────┐              ┌───────────▼────────────┐
   │  GCS mirror       │◄──── JSON ──│  SEGREGATION ENGINE     │
   │ users/{id}/{cid}  │             │  infer_domain()         │
   └──────────────────┘             │  infer_intent()         │
                                    │  classify_contact()     │
                                    └───────────┬────────────┘
                                                │
                       ┌────────────────────────┼────────────────────────┐
                       │                        │                        │
              ┌────────▼────────┐      ┌────────▼────────┐      ┌────────▼────────┐
              │  IMAP extractor │      │ LinkedIn hiring │      │ Reddit hiring   │
              │  (inbox, intent │      │ alerts/profiles │      │ posts           │
              │   tagging)      │      └────────┬────────┘      └────────┬────────┘
              └────────┬────────┘               │                        │
                       │                        └───────────┬────────────┘
                       │                                    │
              ┌────────▼────────┐                ┌──────────▼──────────┐
              │  SMTP sender    │                │  Postgres / SQLite   │
              │  (outreach)     │                │  users, contacts,    │
              └────────┬────────┘                │  email_connections,  │
                       │                         │  linkedin_profiles,  │
                       │                         │  reddit_posts,       │
                       │                         │  whatsapp_messages   │
                       │                         └──────────┬──────────┘
                       │                                    │
              ┌────────▼────────────────────────────────────▼──────────┐
              │                    FastAPI  /api/v1                      │
              │  /auth/google (Google Sign-In → JWT)                     │
              │  /contacts  /contacts/stats  /contacts/import/gcs        │
              │  /email/connections  /email/connections/{id}/test        │
              │  /email/connections/{id}/inbox   /email/send            │
              │  /social/linkedin/*  /social/reddit/*  /social/whatsapp/*│
              │  /cron/run   /health   /integrations                    │
              └───────────────┬───────────────────────┬─────────────────┘
                              │                       │
                   ┌──────────▼─────────┐   ┌─────────▼──────────┐
                   │  Static frontend   │   │  Cloud Scheduler    │
                   │  (Google Sign-In)  │   │  → /cron/run        │
                   └────────────────────┘   │  → Redis queue      │
                                            └─────────┬──────────┘
                                                      │
                                            ┌─────────▼──────────┐
                                            │  Redis  sales:cron │
                                            │  + voice cache     │
                                            └─────────┬──────────┘
                                                      │
                                            ┌─────────▼──────────┐
                                            │ WhatsApp Cloud API │  (current scope)
                                            │ Reddit / LinkedIn  │  (next scope)
                                            │ Gemma voice (multi-│
                                            │ language, mobile)  │  (future scope)
                                            └────────────────────┘
```

### Request lifecycle (Google Sign-In)

```
 Browser                FastAPI                      Google                 Postgres
   │  click Sign-in        │                            │                       │
   ├───────────────────────┼───────────────────────────►│                       │
   │◄──── ID token (JWT) ───┼────────────────────────────┤                       │
   ├── POST /auth/google ─►│ verify_oauth2_token()      │                       │
   │                       ├───────────────────────────►│                       │
   │                       │◄──── claims (sub,email) ───┤                       │
   │                       ├── upsert user ─────────────┼──────────────────────►│
   │◄── our JWT (1h) ──────┤                            │                       │
   ├── GET /contacts  ────►│ get_current_user()         │                       │
   │   Authorization:      ├── decode JWT + scope user ─┼──────────────────────►│
   │   Bearer <jwt>        │◄── rows ───────────────────┼───────────────────────┤
   │◄── JSON contacts ─────┤                            │                       │
```

---

## 2. Roadmap

### Phase 0 — Prototype (DONE)
- [x] FastAPI app, SQLite/Postgres, GCS import, manual contacts
- [x] Segregation: domain / intent / context
- [x] IMAP/SMTP connection registry + test + inbox + send
- [x] LinkedIn/Reddit hiring-alert stubs persisted to DB
- [x] Google Sign-In (ID token → app JWT), dev mode
- [x] pytest suite (24 tests), Dockerfile, Cloud Run/Cloud Build files

### Phase 1 — Email intelligence (next)
- [ ] Gmail/Outlook OAuth (XOAUTH2) instead of app passwords
- [ ] IMAP thread parsing → auto-create contacts from signatures
- [ ] Gemma summarisation → intent + context enrichment
- [ ] Bounce/unsubscribe handling, send throttling

### Phase 2 — Social signal (next scope)
- [ ] LinkedIn official API + hiring-post alerts → profile enrichment
- [ ] Reddit via PRAW → hiring threads → candidate/company extraction
- [ ] Daily cron: keyword sets per region (Ahmednagar, Pune, Mumbai)

### Phase 3 — Outreach & voice
- [x] WhatsApp message queue (Cloud API ready)
- [ ] WhatsApp template approval + delivery webhooks
- [ ] Gemma multi-language voice summaries (event / company details)
- [ ] Redis cache for generated voice + Whisper/TTS pipeline

### Phase 4 — Platform
- [ ] Redis-backed Celery worker (replace inline cron)
- [ ] Cloud SQL + Cloud Run + Secret Manager (guardsrails, WAF, rate limits)
- [ ] MCP server exposing contacts/outreach tools to agents
- [ ] Multi-tenant RBAC, audit log

### Phase 5 — Mobile (future scope)
- [ ] React Native / Flutter client against `/api/*`
- [ ] Google Sign-In native + secure token storage
- [ ] Push notifications for hot intent leads
- [ ] Offline voice notes → sync to GCS

---

## 3. How to run (local)

```powershell
pip install -r requirements-sales.txt
Copy-Item .env.example .env      # then edit
python run.py --seed             # http://localhost:8000
python -m pytest                 # 24 tests
```

- **Doctor**: `GET /api/health` → DB / Redis / GCS / Google Sign-In status.
- **Docs**: `GET /docs` (Swagger UI).
- Dev sign-in: set `AUTH_DEV_MODE=true`, use `dev:you@kalisoftai.com` as the token.
- With `POSTGRES_HOST` (or `DATABASE_URL`) set, it uses Postgres; otherwise SQLite.
- On Cloud Run, ADC + `CLOUD_SQL_CONNECTION_NAME` wire GCS and Cloud SQL automatically.

### Deploy (Cloud Run)

```powershell
./deploy_sales.ps1 -ProjectId <proj> -CloudSqlInstance <proj>:asia-south1:<db>
# or
bash deploy_sales.sh
```

`cloudbuild.sales.yaml` builds `Dockerfile.sales`, injects `SALES_SECRET_KEY` and
`SALES_DATABASE_URL` from Secret Manager, attaches the Cloud SQL instance, and
deploys with `--no-cpu-throttling`.

---

## 4. API quick reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/google` | Exchange Google ID token → app JWT |
| GET | `/api/auth/me` | Current user |
| GET | `/api/contacts` | List + filters (`domain,intent,context,source,q`) |
| POST | `/api/contacts` | Add contact (auto domain/intent) |
| GET | `/api/contacts/stats` | Counts by domain/intent/source |
| POST | `/api/contacts/import/gcs` | Import from `all-sales-contacts-data` |
| PATCH/DELETE | `/api/contacts/{id}` | Update / delete |
| GET/POST | `/api/email/connections` | Register IMAP/SMTP account |
| POST | `/api/email/connections/{id}/test` | Test IMAP + SMTP |
| GET | `/api/email/connections/{id}/inbox` | Fetch + intent-tag mail |
| POST | `/api/email/send` | Send via SMTP |
| POST | `/api/social/linkedin/search` | LinkedIn hiring alerts |
| POST | `/api/social/reddit/search` | Reddit hiring posts |
| POST/GET | `/api/social/whatsapp/messages` | Queue / list WhatsApp |
| POST | `/api/cron/run` | Trigger scheduled sweep |
| GET | `/api/health`, `/api/integrations` | Diagnostics |

### Example seed contact (Ahmednagar)

```
Company : Mahindra Accelo Ltd. (Mahindra & Mahindra group) – Supa, Ahmednagar
Email   : info@mahindraaccelo.com
Phone   : 22 2493 5185 / 5186
SCM     : Smaranika Mohapatra – Assistant Manager (Procurement & SCM)
LinkedIn: Tushar Ithape, Vishal Karad, Ganesh Pagire
Address : F-221, Gat No. 167 K/2, Supa MIDC, Ahmednagar, MH 414301
Intent  : procurement   Domain: mahindraaccelo.com
```

---

## 5. NotebookLM — test scenarios

Upload the repo docs + this `ROADMAP.md`, then run these prompts/scenarios:

1. **Onboarding** — "Explain the contact lifecycle from GCS import to WhatsApp queue
   using the ASCII diagram." Expected: correctly names segregation, dedupe, GCS mirror.
2. **Segregation** — "Given `info@mahindraaccelo.com` with context *SCM procurement
   Supa MIDC*, what are domain/intent/context?" Expected: `mahindraaccelo.com / procurement`.
3. **Email** — "Which IMAP/SMTP ports and security are used, and how is the password
   stored?" Expected: 993 SSL / 587 STARTTLS; Fernet-encrypted at rest.
4. **Multi-user** — "Show that two users cannot see each other's contacts." Expected:
   user-scoped queries (`test_contacts_are_user_scoped`).
5. **Failure modes** — "What happens if GCS/Redis/LinkedIn are unavailable?"
   Expected: graceful degradation, `available=false`, HTTP 503 on hard GCS import.
6. **Scale** — "Compare local SQLite vs Cloud SQL path selection." Expected:
   `DATABASE_URL` > `CLOUD_SQL_CONNECTION_NAME` > `POSTGRES_HOST` > SQLite.
7. **Security** — "List the guardsrails." Expected: Google token audience/issuer/domain
   checks, short-lived JWT, no secrets returned, CORS allow-list, Secret Manager.

---

## 6. Testing

**Backend**
```powershell
python -m pytest -v            # tests/test_auth.py, test_contacts.py, test_social.py, test_system.py, test_services.py
```
Covers: auth (dev/JWT), contact CRUD + segregation + user scoping, stats, LinkedIn/
Reddit idempotency, WhatsApp queue, cron, health/config.

**Frontend (manual, served at `/`)**
1. Open `http://localhost:8000` → dev sign-in `dev:owner@kalisoftai.com`.
2. Add the Mahindra contact → appears with domain/intent chips.
3. Filter by intent `procurement` → only that row.
4. "LinkedIn hiring search" / "Reddit hiring search" → JSON result in output.
5. "Import from GCS" → `{imported, skipped}` (requires ADC + bucket access).

**Cloud Run smoke**
```powershell
curl https://<service-url>/api/health
```

---

## 7. Changelog

| Date | Change |
|---|---|
| 2026-09-12 | FastAPI prototype: contacts + segregation, IMAP/SMTP, LinkedIn/Reddit, WhatsApp queue |
| 2026-09-12 | Google Sign-In (ID token → JWT), dev mode, user-scoped data |
| 2026-09-12 | Cloud Run: Dockerfile.sales, cloudbuild.sales.yaml, deploy_sales.sh/.ps1 |
| 2026-09-12 | Test suite (24 passing), seed data (Mahindra Accelo), ROADMAP + ASCII diagrams |
| _next_ | OAuth XOAUTH2 email, Celery/Redis worker, Gemma voice, LinkedIn/Reddit live APIs |
