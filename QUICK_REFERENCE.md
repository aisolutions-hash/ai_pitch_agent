# ⚡ QUICK REFERENCE - PostgreSQL Migration Commands

## 🚀 FASTEST WAY TO MIGRATE (TL;DR)

### 1️⃣ Backup Your Current Data
```bash
cd c:\Sales_agent
copy db.sqlite3 db.sqlite3.backup
python manage.py dumpdata > backup_data.json
```

### 2️⃣ Install PostgreSQL
**Download from:** https://www.postgresql.org/download/windows/
- Version: PostgreSQL 14 or 15
- During installation, remember the superuser password!

### 3️⃣ Install Python Driver
```bash
pip install psycopg2-binary
pip install -r requirements.txt
```

### 4️⃣ Create Database & User
```bash
psql -U postgres

# In PostgreSQL prompt, paste all of this:
CREATE DATABASE sales_db;
CREATE USER sales_user WITH PASSWORD 'YourSecurePassword123!';
ALTER ROLE sales_user SET client_encoding TO 'utf8';
ALTER ROLE sales_user SET default_transaction_isolation TO 'read committed';
GRANT ALL PRIVILEGES ON DATABASE sales_db TO sales_user;
\c sales_db
GRANT ALL PRIVILEGES ON SCHEMA public TO sales_user;
\q
```

### 5️⃣ Update .env File
```env
# Add these lines to your .env file:
DB_NAME=sales_db
DB_USER=sales_user
DB_PASSWORD=YourSecurePassword123!
DB_HOST=localhost
DB_PORT=5432
```

### 6️⃣ Run Django Migrations
```bash
python manage.py migrate
```

### 7️⃣ Restore Your Data (Optional)
```bash
python manage.py loaddata backup_data.json
```

### 8️⃣ Test It
```bash
python manage.py check
python manage.py runserver
```

---

## 📋 CONFIGURATION CHANGES SUMMARY

### What Changed in settings.py:
```python
# OLD (SQLite):
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# NEW (PostgreSQL):
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'sales_db'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'ATOMIC_REQUESTS': True,
        'CONN_MAX_AGE': 600,
    }
}
```

### What Changed in requirements.txt:
```diff
- django
- gspread
- google-auth-oauthlib
- google-api-python-client
- python-dotenv
- google-generativeai

+ django>=4.2
+ psycopg2-binary>=2.9.9  # <-- NEW: PostgreSQL driver
+ gspread>=5.12.0
+ google-auth-oauthlib>=1.0.0
+ google-api-python-client>=2.100.0
+ python-dotenv>=1.0.0
+ google-generativeai>=0.3.0
+ requests>=2.31.0
```

---

## 🔍 VERIFY EVERYTHING WORKS

### Check 1: Django Configuration
```bash
python manage.py shell

>>> from django.conf import settings
>>> print(settings.DATABASES['default']['ENGINE'])
# Should print: django.db.backends.postgresql

>>> from django.db import connection
>>> print(connection.settings_dict['NAME'])
# Should print: sales_db

>>> exit()
```

### Check 2: Database Connection
```bash
psql -U sales_user -d sales_db -h localhost

# In psql:
\dt

# Should show tables like:
# admin_logentry
# auth_group
# auth_permission
# auth_user
# django_content_type
# django_migrations
# pitch_generator_leadpitch
# ai_agent_pitch_campaign
# ai_agent_pitch_recipient
# ai_agent_pitch_emailtemplate
# extractor_supplier

\q
```

### Check 3: Test Data Create/Read
```bash
python manage.py shell

>>> from extractor.models import Supplier
>>> 
>>> # Create
>>> s = Supplier.objects.create(
...     email="test@example.com",
...     company="Test",
...     name="Tester",
...     number="9999999999"
... )
>>> 
>>> # Read
>>> Supplier.objects.filter(email="test@example.com").first()
<Supplier: Test (test@example.com)>
>>> 
>>> # Delete
>>> s.delete()
>>> 
>>> exit()
```

---

## 🛟 COMMON PROBLEMS & FIXES

### Problem: "psql: command not found"
**Fix:** Add PostgreSQL to PATH
```bash
# On Windows, add this to Environment Variables:
# System > Environment Variables > Path
# Add: C:\Program Files\PostgreSQL\15\bin
```

### Problem: "Connection refused"
**Fix:** Start PostgreSQL service
```bash
# Windows Services
services.msc
# Find: postgresql-x64-15
# Right-click > Start

# Or Command Prompt (as Admin):
net start postgresql-x64-15
```

### Problem: "role 'sales_user' does not exist"
**Fix:** Create user again
```bash
psql -U postgres

CREATE USER sales_user WITH PASSWORD 'YourPassword123!';
GRANT ALL PRIVILEGES ON DATABASE sales_db TO sales_user;
\q
```

### Problem: "permission denied for schema public"
**Fix:** Grant permissions
```bash
psql -U postgres -d sales_db

GRANT ALL PRIVILEGES ON SCHEMA public TO sales_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sales_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sales_user;
\q

# Then:
python manage.py migrate
```

### Problem: Database shows "psycopg2 not found"
**Fix:** Install driver
```bash
pip install psycopg2-binary
```

---

## 📦 FILES UPDATED

✅ **settings.py**
- Changed database engine from SQLite to PostgreSQL
- Added environment variable support for database credentials
- Added connection pooling configuration

✅ **requirements.txt**
- Added `psycopg2-binary>=2.9.9`
- Added version specifications for stability
- Added optional production packages

✅ **.gitignore**
- Removed `db.sqlite3` reference
- Added `*.db` to ignore any database files
- Added common Python ignores

---

## 🔐 SECURITY BEST PRACTICES

### Use Strong Passwords
```bash
# Bad:
DB_PASSWORD=password123

# Good:
DB_PASSWORD=K@lSoft$uPer_P@ssw0rd!x2024
```

### Use Different Credentials for Production
```env
# Production .env:
DB_USER=prod_sales_user
DB_PASSWORD=very_secure_password_randomly_generated
DB_HOST=production-db.example.com
DB_PORT=5432
```

### Never Commit Credentials to Git
```bash
# Make sure .env is in .gitignore
cat .gitignore | grep ".env"
# Should show: .env

# If accidentally committed:
git rm --cached .env
git commit -m "Remove .env from tracking"
```

---

## 📊 DATABASE PERFORMANCE TIPS

### 1. Create Indexes for Common Queries
```bash
python manage.py shell

>>> from django.db import connection
>>> with connection.cursor() as cursor:
...     cursor.execute('CREATE INDEX idx_supplier_company ON extractor_supplier(company);')
...     cursor.execute('CREATE INDEX idx_campaign_sent ON ai_agent_pitch_campaign(sent_at);')

>>> exit()
```

### 2. Monitor Database Size
```bash
psql -U sales_user -d sales_db

SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database;
```

### 3. Backup Schedule
```bash
# Run daily backup (Windows Task Scheduler)
pg_dump -U sales_user -d sales_db > backups\sales_db_$(date +\%Y\%m\%d).sql
```

---

## 🎬 WHAT'S NEXT?

1. ✅ Verify migration with all 3 checks above
2. ✅ Test all app features in browser
3. ✅ Set up automated backups
4. ✅ Monitor database for a few days
5. ✅ (Optional) Migrate to managed database service:
   - AWS RDS PostgreSQL
   - DigitalOcean Managed Databases
   - Heroku PostgreSQL
   - PlanetScale (MySQL alternative)

---

## 📞 QUICK HELP COMMANDS

```bash
# Check if PostgreSQL is running
sc query postgresql-x64-15

# Connect to database
psql -U sales_user -d sales_db

# List all databases
\l

# List all users
\du

# Backup database
pg_dump -U sales_user -d sales_db > sales_db_backup.sql

# Restore database
psql -U sales_user -d sales_db < sales_db_backup.sql

# Check Django migrations
python manage.py showmigrations

# Apply pending migrations
python manage.py migrate

# Run tests
python manage.py test

# Export data
python manage.py dumpdata > data.json

# Import data
python manage.py loaddata data.json
```

---

**Ready to migrate? Start with Step 1 above! 🚀**
