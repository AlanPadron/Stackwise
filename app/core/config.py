from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "Stackwise"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    CORS_ORIGINS: List[str] = ["*"]

    # Security Limits for ZIPs
    MAX_ZIP_SIZE_MB: int = 10
    MAX_FILES_COUNT: int = 500
    MAX_UNCOMPRESSED_SIZE_MB: int = 50

    class Config:
        env_file = ".env"

settings = Settings()
