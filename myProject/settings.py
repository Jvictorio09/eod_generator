"""
Django settings for myProject project.
"""

import logging
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-lx9rqsw12-*$0hi!m25++ins51ne0t=(uj8=ci1iz%1&rdix9&",
)

DEBUG = _env_bool("DEBUG", default=True)

# Employee self-registration at /register/ (set false to lock down production).
ALLOW_PUBLIC_REGISTRATION = _env_bool("ALLOW_PUBLIC_REGISTRATION", default=True)

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

CSRF_TRUSTED_ORIGINS = _env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000",
)

# Railway injects RAILWAY_PUBLIC_DOMAIN when a service has a public URL.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_domain:
    if _railway_domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_railway_domain)
    _railway_origin = f"https://{_railway_domain}"
    if _railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_railway_origin)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "myApp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "myProject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.csrf",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "myProject.wsgi.application"

# Local dev: SQLite. Production: PostgreSQL via DATABASE_URL (required when DEBUG=False).
_database_url = os.getenv("DATABASE_URL", "").strip()
if _database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            _database_url,
            conn_max_age=60,
            conn_health_checks=True,
            ssl_require=_env_bool("DATABASE_SSL", default=not DEBUG),
        )
    }
    if not DEBUG:
        engine = DATABASES["default"].get("ENGINE", "")
        host = DATABASES["default"].get("HOST", "")
        if "postgresql" not in engine:
            raise ImproperlyConfigured(
                f"DATABASE_URL must point to PostgreSQL in production (got {engine})."
            )
        logger.info("Using PostgreSQL at %s (conn_max_age=60)", host or "DATABASE_URL host")
elif DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "DATABASE_URL is not set. On Railway, link your Postgres service to this web "
        "service so DATABASE_URL is injected — SQLite is not used in production."
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# WhiteNoise — gzip/brotli at collectstatic; long cache for fingerprinted assets.
WHITENOISE_MAX_AGE = 31536000
WHITENOISE_MANIFEST_STRICT = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "closeout",
    }
}

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
CSRF_FAILURE_VIEW = "myApp.views.csrf_failure"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", default=True)

# Email alerts (Gmail SMTP) — optional; in-app notifications always work.
NOTIFY_EMAIL_ENABLED = _env_bool("NOTIFY_EMAIL_ENABLED", default=False)
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend"
    if NOTIFY_EMAIL_ENABLED
    else "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "").strip()
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    EMAIL_HOST_USER or "closeout@localhost",
)
