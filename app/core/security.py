from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
import bcrypt
from app.core.config import settings

ALGORITHM = "HS256"

# bcrypt only considers the first 72 bytes and raises on longer input.
def _bcrypt_bytes(password: str) -> bytes:
    return password.encode('utf-8')[:72]

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(_bcrypt_bytes(plain_password), hashed_password.encode('utf-8'))

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(_bcrypt_bytes(password), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload if payload else None
    except JWTError:
        return None
