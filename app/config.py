from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    groq_api_key: str = ""
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    database_url: str = "postgresql://infragpt:infragpt@db:5432/infragpt"
    redis_url: str = "redis://redis:6379/0"
    redis_cache_ttl: int = 300  # 5 min cache for identical questions
    rate_limit_requests: int = 20
    rate_limit_window: int = 60  # per minute

    class Config:
        env_file = ".env"

settings = Settings()
