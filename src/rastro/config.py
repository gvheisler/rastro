from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "rastro"
    postgres_password: str
    postgres_db: str = "rastro"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={self.postgres_user} password={self.postgres_password}"
        )


def get_settings() -> Settings:
    return Settings()
