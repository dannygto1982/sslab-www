"""SSLAB Admin Platform - JWT Auth"""
import jwt
import time
import bcrypt
from config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_HOURS, ADMIN_USERNAME, ADMIN_PASSWORD_HASH


def verify_password(plain_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), ADMIN_PASSWORD_HASH.encode())


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": time.time() + JWT_EXPIRE_HOURS * 3600,
        "iat": time.time()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except jwt.PyJWTError:
        return None
