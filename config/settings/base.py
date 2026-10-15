import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from config.env import load_env

BASE_DIR = Path(__file__).resolve().parents[2]
load_env(BASE_DIR / ".env")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Run: python scripts/init_local.py (missing/short local secret).")
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles", "django.contrib.postgres",
    "accounts", "registry", "patients", "scheduling", "care", "finance", "adc_core", "portal", "assistants", "workspaces", "coordination", "notifications", "equipment",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware", "adc_core.security.PrivateResponseMiddleware", "workspaces.middleware.WorkspaceMiddleware", "adc_core.middleware.ReadOnlyDemoMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages", "adc_core.context.navigation", "guidance.context.guide_context"]}}]
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "accounts.UserAccount"
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.environ.get("POSTGRES_DB", "adc_local"),
                         "USER": os.environ.get("POSTGRES_USER", "adc_local"), "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
                         "HOST": os.environ.get("DB_HOST", "127.0.0.1"), "PORT": os.environ.get("DB_PORT", "54329"),
                         "CONN_MAX_AGE": 0, "OPTIONS": {"connect_timeout": 8}}}
if not DATABASES["default"]["PASSWORD"]:
    raise ImproperlyConfigured("POSTGRES_PASSWORD must be set; there is no SQLite fallback.")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "select_role"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
ADC_READ_ONLY = os.environ.get("ADC_READ_ONLY", "0") == "1"
ADC_VERSION = "1.0.0-rc.1"

# AI is a server-side intent classifier, not a clinical or autonomous agent.
AI_MODE = os.environ.get("AI_MODE", "demo")
if AI_MODE not in ("demo", "remote", "disabled"):
    raise ImproperlyConfigured("AI_MODE must be demo, remote or disabled.")
AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.environ.get("AI_MODEL", "")
AI_ALLOWED_HOSTS = [x.strip().lower() for x in os.environ.get("AI_ALLOWED_HOSTS", "api.openai.com").split(",") if x.strip()]
AI_TIMEOUT_SECONDS = int(os.environ.get("AI_TIMEOUT_SECONDS", "20"))
AI_TOKEN_LIMIT_FIELD = os.environ.get("AI_TOKEN_LIMIT_FIELD", "max_completion_tokens")
AI_USER_MINUTE_LIMIT = int(os.environ.get("AI_USER_MINUTE_LIMIT", "10"))
AI_USER_DAILY_LIMIT = int(os.environ.get("AI_USER_DAILY_LIMIT", "100"))
AI_GLOBAL_DAILY_LIMIT = int(os.environ.get("AI_GLOBAL_DAILY_LIMIT", "1000"))
if min(AI_USER_MINUTE_LIMIT,AI_USER_DAILY_LIMIT,AI_GLOBAL_DAILY_LIMIT) < 1:
    raise ImproperlyConfigured("AI limits must be positive.")
