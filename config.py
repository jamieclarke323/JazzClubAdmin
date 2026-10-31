import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
    APP_NAME = os.environ.get("APP_NAME", "Nest")
    TIMEZONE = os.environ.get("TIMEZONE", "Europe/London")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'household.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_DURATION = timedelta(days=90)
    PREFERRED_URL_SCHEME = "https" if SESSION_COOKIE_SECURE else "http"

    ALLOW_REGISTRATION = env_bool("ALLOW_REGISTRATION", True)
    CSRF_ENABLED = True
    # Uploads (Info attachments). Photos from phones are typically 1-5 MB.
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(BASE_DIR / "instance" / "uploads"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"
    CSRF_ENABLED = False
    ALLOW_REGISTRATION = True
    UPLOAD_DIR = str(BASE_DIR / "instance" / "test-uploads")
