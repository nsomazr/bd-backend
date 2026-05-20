"""Django settings for the Maisha Chat backend (bd_backend)."""
from __future__ import annotations

import os
import socket
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# The dotenv file is named ".env.local" because ".env" is the project-local
# Python virtualenv directory.
_dotenv_candidates = [
    BASE_DIR / ".env.local",
    BASE_DIR / "env.local",
]
for _candidate in _dotenv_candidates:
    if _candidate.is_file():
        load_dotenv(_candidate)
        break
else:
    # Backwards-compat: load BASE_DIR/.env only if it's a file (not a venv dir).
    _legacy = BASE_DIR / ".env"
    if _legacy.is_file():
        load_dotenv(_legacy)


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in {"1", "true", "yes"}


def _detect_local_hostnames() -> list[str]:
    """Best-effort discovery of names a dev machine might be reached as."""
    names: list[str] = []
    try:
        hostname = socket.gethostname()
        if hostname:
            names.append(hostname)
            short = hostname.split(".", 1)[0]
            if short and short not in names:
                names.append(short)
    except OSError:
        pass
    # All IPv4 addresses bound on this host (covers LAN access via 192.168.x.x).
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None)
        for info in infos:
            addr = info[4][0]
            if addr and addr not in names and ":" not in addr:
                names.append(addr)
    except OSError:
        pass
    return names


_extra_hosts = _detect_local_hostnames()

ALLOWED_HOSTS = _env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,api.maishachat.or.tz",
)
# Always include this machine's detectable hostnames/IPs in dev so the backend
# is reachable as hpgp:8090, 192.168.x.x:8090, etc. without manual whitelisting.
for _h in _extra_hosts:
    if _h not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_h)
# In DEBUG, open up host validation entirely – it's just header validation and
# prevents the “Invalid HTTP_HOST” 400 wall during local development.
if DEBUG and "*" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("*")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "accounts",
    "chat",
    "llm",
    "arena",
    "rlhf",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "bd_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "bd_backend.wsgi.application"
ASGI_APPLICATION = "bd_backend.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("DB_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

AUTH_USER_MODEL = "accounts.User"

# Keep the policy minimal so signup stays low friction. We enforce the 6-char
# minimum at the serializer level; the admin still benefits from the basic
# length check via this list.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Dar_es_Salaam"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MIN", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "14"))),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

FRONTEND_DEV_PORT = os.getenv("FRONTEND_DEV_PORT", "3090")

CORS_ALLOWED_ORIGINS = _env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3090,http://127.0.0.1:3090,https://maishachat.or.tz",
)
# Auto-add http(s)://<hostname>:<frontend-port> for each detected hostname/IP.
for _h in _extra_hosts:
    for _scheme in ("http", "https"):
        origin = f"{_scheme}://{_h}:{FRONTEND_DEV_PORT}"
        if origin not in CORS_ALLOWED_ORIGINS:
            CORS_ALLOWED_ORIGINS.append(origin)

# In DEBUG, also accept any localhost-style origin via regex so wildcard ports
# (e.g. Vite's preview server on a different port) don't get rejected.
CORS_ALLOWED_ORIGIN_REGEXES = _env_list("CORS_ALLOWED_ORIGIN_REGEXES")
if DEBUG:
    CORS_ALLOWED_ORIGIN_REGEXES.extend(
        [
            r"^https?://localhost(:\d+)?$",
            r"^https?://127\.0\.0\.1(:\d+)?$",
            r"^https?://192\.168\.\d+\.\d+(:\d+)?$",
            r"^https?://10\.\d+\.\d+\.\d+(:\d+)?$",
            r"^https?://[\w.-]+\.local(:\d+)?$",
        ]
    )

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = _env_list(
    "CSRF_TRUSTED_ORIGINS",
    "https://maishachat.or.tz,https://api.maishachat.or.tz",
)
# Mirror the same dev hostnames into CSRF trusted origins so POSTs don't 403.
for _h in _extra_hosts:
    for _scheme in ("http", "https"):
        origin = f"{_scheme}://{_h}:{FRONTEND_DEV_PORT}"
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)

# Behind nginx with TLS termination
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# ---- LLM configuration -----------------------------------------------------
# Hugging Face caches go to the project models directory by default.
os.environ.setdefault(
    "HF_HOME",
    os.getenv("HF_HOME", "/home/happiness/blood_donation_ai/models"),
)
os.environ.setdefault(
    "TRANSFORMERS_CACHE",
    os.getenv("TRANSFORMERS_CACHE", "/home/happiness/blood_donation_ai/models"),
)

LLM_TORCH_DTYPE = os.getenv("TORCH_DTYPE", "auto")
LLM_DEVICE_MAP = os.getenv("LLM_DEVICE_MAP", "auto")
# auto = use CUDA when this process can open a context, else CPU.
# cpu  = never touch the GPU (safe default on shared machines).
# cuda = require GPU; falls back to CPU with a warning if unavailable.
LLM_DEVICE = os.getenv("LLM_DEVICE", "auto")
LLM_MAX_NEW_TOKENS = int(os.getenv("LLM_MAX_NEW_TOKENS", "512"))
LLM_MAX_NEW_TOKENS_CPU = int(os.getenv("LLM_MAX_NEW_TOKENS_CPU", "256"))
LLM_CPU_THREADS = int(os.getenv("LLM_CPU_THREADS", "0"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "llm": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "chat": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
