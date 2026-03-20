from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env")

    # PostgreSQL
    postgres_user: str
    postgres_password: str
    postgres_db: str

    # Database URL for SQLAlchemy
    database_url: str

    # Redis
    redis_url: str

    # RabbitMQ
    rabbitmq_user: str
    rabbitmq_password: str
    rabbitmq_url: str

    # Worker config
    worker_count: int = 100
    max_retries: int = 3


settings = Settings()