from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", extra="ignore")

    data_dir: Path = Path(".agent-data")
    frontend_dist: Path = Path("frontend/dist")
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver"]
    public_origin: str | None = None
    cookie_secure: bool | None = None
    session_hours: int = Field(default=24, ge=1, le=168)
    max_parallel_runs: int = Field(default=2, ge=1, le=8)
    context_token_budget: int | None = Field(default=None, ge=4_096)
    context_keep_tokens: int = Field(default=16_000, ge=800, le=120_000)

    @property
    def database_url(self) -> str:
        return "sqlite:///" + (self.data_dir.resolve() / "app.sqlite3").as_posix()
