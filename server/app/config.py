from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_path: Path = Path.home() / ".myagentdata" / "aisecretary" / "transactions.sqlite"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def model_post_init(self, __context) -> None:
        # Expand ~ in case the env var uses shell-style home shorthand
        self.database_path = self.database_path.expanduser().resolve()


settings = Settings()

