from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://orderops:orderops@localhost:5432/orderops"
    checkpoint_db_url: str = "postgresql://orderops:orderops@localhost:5432/orderops"
    admin_api_key: str = "local-demo-key-change-before-deployment"
    jwt_secret: str = "dev-jwt-secret-change-before-deployment"
    jwt_expire_minutes: int = Field(default=480, ge=1)
    risk_threshold: float = Field(default=0.8, ge=0, le=1)
    discount_bps: int = Field(default=500, ge=0, le=1000)
    offer_ttl_hours: int = Field(default=24, ge=1, le=72)
    worker_poll_seconds: float = Field(default=2, ge=0.1)
    agent_mode: Literal["rules", "ollama"] = "rules"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = ""


settings = Settings()
