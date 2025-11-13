import os
from dotenv import load_dotenv

# Asegura que el .env del proyecto tenga prioridad sobre variables globales
load_dotenv(override=True)


class Config:
    # Normalizar DATABASE_URL (soporta 'postgres://' -> 'postgresql://')
    _db = os.getenv("DATABASE_URL", "sqlite:///app.db")
    if _db.startswith("postgres://"):
        _db = _db.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    # SMTP / Email settings (configure in .env)
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
