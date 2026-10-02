from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret_key: str
    webhook_secret: str

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bcrypt_rounds: int = 12

    payment_success_rate: float = Field(default=0.8, ge=0, le=1)

    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10

    redis_url: str | None = None
    cache_ttl_seconds: int = 60

    payment_pending_timeout_minutes: int = 30
    webhook_retry_max_attempts: int = 5
    webhook_retry_base_seconds: int = 30

    log_level: str = "INFO"

    admin_email: str | None = None
    admin_password: str | None = None


settings = Settings()
