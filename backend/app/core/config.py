import os
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Configuration
    PROJECT_NAME: str = "Amex ConciergeAI"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = Field(default="development")

    # Database Configuration
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="postgres")
    POSTGRES_SERVER: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DB: str = Field(default="amex_concierge")
    DATABASE_URL: Optional[str] = None

    # Redis Configuration
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Integrations
    AMADEUS_API_KEY: str = Field(default="mock_amadeus_key")
    AMADEUS_API_SECRET: str = Field(default="mock_amadeus_secret")
    TWILIO_ACCOUNT_SID: str = Field(default="mock_twilio_sid")
    TWILIO_AUTH_TOKEN: str = Field(default="mock_twilio_token")
    TWILIO_PHONE_NUMBER: str = Field(default="+1234567890")

    # Security
    JWT_SECRET: str = Field(default="super_secret_jwt_signing_key_change_me_in_production")
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: Optional[str], info) -> str:
        if isinstance(v, str) and v:
            return v
        data = info.data
        user = data.get("POSTGRES_USER")
        password = data.get("POSTGRES_PASSWORD")
        server = data.get("POSTGRES_SERVER")
        port = data.get("POSTGRES_PORT")
        db = data.get("POSTGRES_DB")
        return f"postgresql+asyncpg://{user}:{password}@{server}:{port}/{db}"


# Global settings instance
settings = Settings()
