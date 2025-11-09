from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    FIREBASE_PROJECT_ID: str
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    MODEL_NAME: str = "gcp_nl"  # using Google Cloud Natural Language

    @property
    def origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

settings = Settings(_env_file=os.getenv("ENV_FILE", ".env"), _env_file_encoding="utf-8")
