from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SQL_DIR = ROOT / "sql"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "rastro"
    postgres_password: str
    postgres_db: str = "rastro"
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    readonly_user: str = "rastro_ro"
    readonly_password: str

    def _dsn(self, user: str, password: str) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={user} password={password}"
        )

    @property
    def dsn(self) -> str:
        return self._dsn(self.postgres_user, self.postgres_password)

    @property
    def readonly_dsn(self) -> str:
        return self._dsn(self.readonly_user, self.readonly_password)


def get_settings() -> Settings:
    return Settings()
