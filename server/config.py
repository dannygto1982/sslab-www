"""SSLAB Admin Platform - Configuration"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "sslab_admin.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# JWT
SECRET_KEY = os.environ.get("SSLAB_SECRET", "sslab-admin-secret-key-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = "$2b$12$lmNvW.QuEvX.22SPDXqBJu5TtpqY/EO8vvrBMy5JWNuErfoRNb5hK"

# Heartbeat timeout (seconds) - terminal offline after this
HEARTBEAT_TIMEOUT = 600  # 10 minutes (will reduce after new APK deployed)

# Server
HOST = "0.0.0.0"
PORT = 8080

# Ensure directories exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
