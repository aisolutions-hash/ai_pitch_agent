# MyMainProject/settings.py

import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- .env file loading ---
# Load the .env file from the project root directory
env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path)
# -------------------------

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'default-django-secret-key-for-local')
DEBUG =True

ALLOWED_HOSTS = []

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',  # <-- ADMIN PART RE-ADDED
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # My Apps
    'extractor',
    'ai_agent_pitch',
    'pitch_generator',
    'dashboard',
    'scraper',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sales_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Central templates folder
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sales_project.wsgi.application'

# Database Configuration - PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
        'ATOMIC_REQUESTS': True,  # Ensures atomicity of database transactions
        'CONN_MAX_AGE': 600,  # Connection pooling
    }
}

# Optional: Connection pool configuration (if using django-db-geventpool)
# DATABASES['default'].setdefault('CONN_MAX_AGE', None)  # Disable connection aging

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    { 'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator', },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'  # For production (collectstatic)
STATICFILES_DIRS = [
    BASE_DIR / 'static',  # Project-level static files
]

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ==================================================================
# CUSTOM APP SETTINGS (Loaded from .env)
# ==================================================================

# --- Mapping User's Credentials to Django Standard Names ---
# The logic uses your custom names from .env to set standard names
GMAIL_USER = os.getenv('EMAIL_USER')
GMAIL_APP_PASSWORD = os.getenv('EMAIL_PASS')
GMAIL_IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.gmail.com')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PITCH_EMAIL_HOST_USER = os.getenv('PITCH_EMAIL_HOST_USER')
PITCH_GMAIL_APP_PASSWORD = os.getenv('PITCH_GMAIL_APP_PASSWORD')

# --- Email (SMTP) Configuration (Used by ai_agent_pitch) ---
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = PITCH_EMAIL_HOST_USER                 # <-- Uses mapped GMAIL_USER
EMAIL_HOST_PASSWORD = PITCH_GMAIL_APP_PASSWORD     # <-- Uses mapped GMAIL_APP_PASSWORD
DEFAULT_FROM_EMAIL = PITCH_EMAIL_HOST_USER
DEFAULT_FROM_NAME = os.getenv('DEFAULT_FROM_NAME', 'KalisoftAI')
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8000')


# --- Google Sheets Configuration ---

# Shared Credentials (used by both apps)
GOOGLE_CREDENTIALS_PATH = os.getenv('GOOGLE_CREDENTIALS_PATH')
if GOOGLE_CREDENTIALS_PATH:
    GOOGLE_CREDENTIALS_FILE = os.path.normpath(GOOGLE_CREDENTIALS_PATH)
else:
    GOOGLE_CREDENTIALS_FILE = str(BASE_DIR / 'credentials.json')

# App 1: Extractor Sheet
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# App 2: Pitch Generator Sheet
PITCH_SHEET_ID = os.getenv('PITCH_SHEET_ID')

# App 3: LinkedIn Scraper Sheet
LINKEDIN_SHEET_ID = os.getenv('LINKEDIN_SHEET_ID')

# --- Other API Keys (Accessed via os.getenv in other files if needed) ---
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
API_KEYS = os.getenv('API_KEYS')

# --- Redundant/Empty Keys (Kept for completeness but not used) ---

# --- Google Cloud Storage Configuration ---
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', '')
GCS_PROJECT_ID = os.getenv('GCS_PROJECT_ID', '')
GCS_KEY_PATH = os.getenv('GCS_KEY_PATH', '')

# Normalize the path for Windows
if GCS_KEY_PATH:
    GCS_KEY_PATH = os.path.normpath(GCS_KEY_PATH)

# Bucket folder structure for contacts
GCS_CONTACTS_FOLDER = 'contacts/'
