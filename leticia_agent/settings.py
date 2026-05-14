"""Django settings for leticia_agent.

Reads everything sensitive from environment variables. See .env.example.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value or ""


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-not-for-prod")
DEBUG = env("DJANGO_DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "bot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "leticia_agent.urls"
WSGI_APPLICATION = "leticia_agent.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

DATABASE_URL = env("DATABASE_URL")
_VALID_DB_SCHEMES = ("postgres://", "postgresql://", "sqlite://")
if DATABASE_URL and DATABASE_URL.startswith(_VALID_DB_SCHEMES):
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            ssl_require=DATABASE_URL.startswith(("postgres://", "postgresql://")),
        )
    }
    if DATABASES["default"]["ENGINE"].endswith("postgresql"):
        DATABASES["default"]["OPTIONS"] = {"options": "-c search_path=leticia,public"}
else:
    # Boot-safe fallback so the web service can start before DATABASE_URL is set.
    # The app cannot do real work in this state — it will return 500s on any DB query —
    # but /health/ stays up so deploys don't crashloop.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "America/Sao_Paulo"
LANGUAGE_CODE = "pt-br"

STATIC_URL = "static/"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
    },
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# ---- Letícia config ----
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-opus-4-7")

EVOLUTION_BASE_URL = env("EVOLUTION_BASE_URL", "https://api.evolution.example")
EVOLUTION_API_KEY = env("EVOLUTION_API_KEY")
EVOLUTION_INSTANCE = env("EVOLUTION_INSTANCE")
EVOLUTION_WEBHOOK_TOKEN = env("EVOLUTION_WEBHOOK_TOKEN")  # shared secret on inbound

SLACK_BOT_TOKEN = env("SLACK_BOT_TOKEN")           # xoxb-...
SLACK_APP_TOKEN = env("SLACK_APP_TOKEN")           # xapp-1-... (Socket Mode)
SLACK_CHANNEL = env("SLACK_CHANNEL", "#leticia-teste")
SLACK_ALLOWED_USERS = [
    u.strip() for u in env("SLACK_ALLOWED_USERS", "").split(",") if u.strip()
]

LETICIA_AUTONOMY_DEFAULT = env("LETICIA_AUTONOMY_DEFAULT", "true").lower() == "true"
LETICIA_TYPING_DELAY_MIN_MS = int(env("LETICIA_TYPING_DELAY_MIN_MS", "2000"))
LETICIA_TYPING_DELAY_MAX_MS = int(env("LETICIA_TYPING_DELAY_MAX_MS", "8000"))
