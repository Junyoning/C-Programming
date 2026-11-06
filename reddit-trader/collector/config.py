"""환경 변수(.env)에서 설정을 읽어온다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUBREDDITS = ["wallstreetbets", "stocks", "investing", "options"]


class ConfigError(RuntimeError):
    """필수 설정이 빠졌을 때 발생."""


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    user_agent: str
    subreddits: list[str] = field(default_factory=lambda: list(DEFAULT_SUBREDDITS))
    db_path: Path = PROJECT_ROOT / "data" / "reddit.db"


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_db_path() -> Path:
    """DB 경로만 필요할 때(예: stats 명령) Reddit 키 없이 읽는다."""
    load_dotenv(PROJECT_ROOT / ".env")
    db_path = Path(os.getenv("DB_PATH", "data/reddit.db"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    required = {
        "REDDIT_CLIENT_ID": os.getenv("REDDIT_CLIENT_ID", "").strip(),
        "REDDIT_CLIENT_SECRET": os.getenv("REDDIT_CLIENT_SECRET", "").strip(),
        "REDDIT_USER_AGENT": os.getenv("REDDIT_USER_AGENT", "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ConfigError(
            f"다음 환경 변수가 비어 있습니다: {', '.join(missing)}. "
            ".env.example 을 .env 로 복사한 뒤 값을 채워주세요."
        )

    return Settings(
        client_id=required["REDDIT_CLIENT_ID"],
        client_secret=required["REDDIT_CLIENT_SECRET"],
        user_agent=required["REDDIT_USER_AGENT"],
        subreddits=_split_csv(os.getenv("SUBREDDITS")) or list(DEFAULT_SUBREDDITS),
        db_path=load_db_path(),
    )
