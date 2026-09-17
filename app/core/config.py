from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AdServe"
    app_env: str = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str
    test_database_url: str
    redis_url: str
    test_redis_url: str
    kafka_bootstrap_servers: str
    kafka_events_topic: str
    # Rate limiting (see app/core/rate_limit.py). Configurable rather than
    # hardcoded specifically so load tests and scripts/simulate_traffic.py
    # can raise it: every request from those comes from one machine and so
    # shares a single per-IP bucket, which otherwise throttles the load
    # generator instead of the server. See STUDY_NOTES.md §30.4.
    auction_rate_limit: int = 100
    auction_rate_window_seconds: int = 10


settings = Settings()
