# AI Sales Agent 🚀

A powerful Django-based web application that automates the entire B2B sales pipeline — from supplier discovery and email extraction to AI-powered pitch generation and tracked email campaign delivery.

---

## About The Project

**AI Sales Agent** is an integrated, AI-driven sales suite built for agencies, freelancers, and B2B sales teams. It eliminates manual prospecting and outreach by combining email intelligence, AI research, content generation, and campaign analytics into one unified platform.

The project is organized into **3 core Django apps**:

| App | Purpose |
|-----|---------|
| `extractor` | Find supplier leads by scanning your email inbox with AI |
| `ai_agent_pitch` | Compose, personalize, and send HTML email campaigns with open-tracking |
| `pitch_generator` | Research companies and auto-generate full multi-format sales pitches using AI |

---

## ✨ Features

### 📧 Email Supplier Extractor (`/search/`)
- Connects to your Gmail or Outlook inbox via **IMAP**.
- Intelligently identifies supplier emails (Purchase Orders, RFQs, Quotations) using keyword detection.
- Sends email content to **Gemini AI** to extract: Company Name, Contact Person, Phone Number.
- **Single search** (one query) and **Bulk CSV upload** (process many company names at once).
- Saves all extracted suppliers to the database and syncs to **Google Sheets** automatically.
- **CSV export** of the full supplier list.

### 🎯 AI Email Campaign Manager (`/pitch/`)
- Rich HTML email editor with **live preview**.
- **AI Enhancement**: Send a prompt and let Gemini AI generate or refine your HTML email (tries `gemini-2.0-flash` → `2.5-flash` → `1.5-flash` with fallback).
- **AI Subject Generator**: Get 3 AI-suggested subject lines instantly.
- **Template Management**: Save and reload your best email templates by name.
- **Recipient Input**: Upload a CSV (with Email, First Name, Last Name columns) or type emails manually (comma-separated).
- **Personalization**: Replaces `[Recipient]` placeholder in subject and body per recipient.
- **Email Open Tracking**: Embeds a hidden 1×1 tracking pixel per email; records open time automatically when recipients open.
- **Campaign Dashboard**: View all sent campaigns with total sent, total opened, and open rate (%). Chart.js graph for the last 10 campaigns.
- **Campaign Detail View**: Per-recipient status (Sent / Opened / Failed) with timestamps.

### 🤖 AI Pitch Generator (`/generator/`)
- Enter a **Company Name** and optional website URL.
- **Auto-Research** via SerpAPI:
  - Query 1: Branding/social media presence signals.
  - Query 2: Reviews, complaints, operational gaps.
- **AI Pitch Generation** via Gemini — produces 9 outputs in one call:
  - Pain Points summary
  - Email Subject line
  - Email Body (plain text)
  - Email Body (styled HTML)
  - WhatsApp message
  - Phone Call script
  - Visual Style Guide (brand aesthetic)
  - Image Prompt (Midjourney/DALL-E ready)
  - Video Prompt (Runway/Luma ready)
- Saves all generated pitches to the database.
- **Auto-exports** each new pitch to a dedicated **Google Sheet**.

---

## 🗄️ Database Models

### `Supplier` (extractor)
| Field | Type | Description |
|-------|------|-------------|
| `company` | CharField | Extracted company name |
| `email` | EmailField (unique) | Supplier email address |
| `name` | CharField | Contact person name |
| `number` | CharField | Phone number |
| `created_at` | DateTimeField | Auto timestamp |

### `EmailTemplate` (ai_agent_pitch)
| Field | Type | Description |
|-------|------|-------------|
| `name` | CharField (unique) | Template nickname |
| `html_content` | TextField | Full HTML content |

### `Campaign` (ai_agent_pitch)
| Field | Type | Description |
|-------|------|-------------|
| `subject` | CharField | Campaign subject line |
| `sent_at` | DateTimeField | Auto timestamp |

### `Recipient` (ai_agent_pitch)
| Field | Type | Description |
|-------|------|-------------|
| `campaign` | ForeignKey → Campaign | Parent campaign |
| `name` | CharField | Recipient display name |
| `email` | EmailField | Recipient email |
| `status` | CharField | `sent` / `opened` / `failed` |
| `opened_at` | DateTimeField | Set when tracking pixel fires |

### `LeadPitch` (pitch_generator)
| Field | Type | Description |
|-------|------|-------------|
| `company_name` | CharField | Target company |
| `website_url` | URLField | Optional website |
| `pain_points` | TextField | Identified gaps |
| `research_summary` | TextField | SerpAPI research data |
| `email_subject` | CharField | Generated subject |
| `email_body_text` | TextField | Plain text pitch |
| `email_body_html` | TextField | HTML pitch |
| `whatsapp_message` | TextField | WhatsApp version |
| `call_script` | TextField | Phone call script |
| `visual_style_guide` | TextField | Brand aesthetic keywords |
| `image_prompt` | TextField | Midjourney/DALL-E prompt |
| `video_prompt` | TextField | Runway/Luma prompt |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- PostgreSQL
- A Gmail account with an **App Password** (for IMAP and SMTP)
- API keys for: **Gemini AI**, **SerpAPI**
- A **Google Cloud service account** with Sheets API enabled (`credentials.json`)

### Installation

1. **Clone the repository:**
   ```sh
   git clone https://github.com/your-username/ai-sales-agent.git
   cd ai-sales-agent
   ```

2. **Create and activate a virtual environment:**
   ```sh
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

4. **Create a `.env` file** in the project root with the following:
   ```env
   # Django
   DJANGO_SECRET_KEY=your-super-secret-django-key
   DEBUG=True

   # PostgreSQL Database
   DB_NAME=your_db_name
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   DB_HOST=localhost
   DB_PORT=5432

   # Email Extractor (IMAP - for reading emails)
   IMAP_SERVER=imap.gmail.com
   EMAIL_USER=your_email@gmail.com
   EMAIL_PASS=your_gmail_app_password

   # Email Campaign Sender (SMTP - for sending emails)
   PITCH_EMAIL_HOST_USER=your_email@gmail.com
   PITCH_GMAIL_APP_PASSWORD=your_gmail_app_password
   DEFAULT_FROM_NAME=YourName

   # AI & Search APIs
   GEMINI_API_KEY=your_gemini_api_key
   SERPAPI_API_KEY=your_serpapi_key

   # Google Sheets Integration
   GOOGLE_CREDENTIALS_PATH=credentials.json
   GOOGLE_SHEET_ID=your_extractor_sheet_id
   PITCH_SHEET_ID=your_pitch_generator_sheet_id

   # Site URL (used for email tracking pixels)
   SITE_URL=http://127.0.0.1:8000
   ```

   > **Security Notice 🔒**: Always use **Gmail App Passwords** (not your main password). Never commit `.env` or `credentials.json` to Git.

5. **Apply migrations:**
   ```sh
   python manage.py migrate
   ```

6. **Seed email templates** (optional, loads pre-built HTML templates):
   ```sh
   python manage.py seed_templates
   ```

7. **Run the development server:**
   ```sh
   python manage.py runserver
   ```
   Visit: `http://127.0.0.1:8000/`

---

## 🎮 How to Use

### Email Supplier Extractor (`/search/`)
1. Navigate to `/search/`.
2. **Single search**: Type a company or product name → click **Search**.
3. **Bulk search**: Upload a CSV with a `Company Name` column → app processes each row.
4. Results are displayed in a table and auto-saved to the database and Google Sheets.
5. Click **Download CSV** to export all supplier records.

### AI Email Campaigns (`/pitch/`)
1. Navigate to `/pitch/`.
2. Write or paste your HTML email in the editor — or click **Enhance with AI** with a prompt.
3. Use **Generate Subject** to get 3 AI subject line ideas.
4. Add recipients: upload a CSV or type emails separated by commas.
5. Click **Send Campaign** — emails are sent, personalized, and tracked.
6. Visit `/pitch/dashboard/` to view campaign stats and open rates.
7. Click any campaign to see the per-recipient open status.

### AI Pitch Generator (`/generator/`)
1. Navigate to `/generator/create/`.
2. Enter the **Company Name** and optionally their website URL.
3. Click **Generate Pitch** — the system will research and generate content automatically.
4. View the full pitch at `/generator/result/<id>/` with all 9 outputs.
5. Data is automatically exported to your configured Google Sheet.

---

## 🌐 URL Structure

```
/                               → Redirects to /pitch/
/admin/                         → Django Admin Panel
/search/                        → Email Supplier Extractor
/search/download_csv/           → CSV Export
/search/sync-all/               → Sync all suppliers to Google Sheets
/pitch/                         → Email Campaign Composer
/pitch/dashboard/               → Campaign Analytics Dashboard
/pitch/dashboard/<id>/          → Campaign Detail (per-recipient status)
/pitch/save-template/           → Save email template (AJAX)
/pitch/load-template/<id>/      → Load saved template (AJAX)
/pitch/generate-subject/        → AI subject suggestions (AJAX)
/pitch/enhance-with-ai/         → AI HTML enhancement (AJAX)
/pitch/mark-opened/<id>/<email>/ → Email tracking pixel endpoint
/generator/create/              → AI Pitch Generator form
/generator/result/<id>/         → View generated pitch detail
```

---

## 🛠️ Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.9+, Django 5.x |
| **Database** | PostgreSQL |
| **AI / LLM** | Google Gemini API (`gemini-2.0-flash`, `2.5-flash`, `1.5-flash`) |
| **Web Research** | SerpAPI (Google Search results) |
| **Email (Read)** | `imaplib` — Gmail / Outlook IMAP |
| **Email (Send)** | Django SMTP — Gmail |
| **Spreadsheets** | Google Sheets API (`gspread`, service account) |
| **Frontend** | Django Templates, Tailwind CSS (CDN), Alpine.js (CDN) |
| **Charts** | Chart.js |
| **Config** | `python-dotenv` |

---

## 🤝 Contributing

Contributions are welcome! To contribute:

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request
