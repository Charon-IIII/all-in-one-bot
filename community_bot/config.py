from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    token: str
    database_path: Path
    sync_guild_id: int | None
    log_level: str
    message_content_intent: bool


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing. Create a .env file based on .env.example.")
    guild_id = os.getenv("SYNC_GUILD_ID", "").strip()
    return Settings(
        token=token,
        database_path=Path(os.getenv("DATABASE_PATH", "data/community_bot.sqlite3")),
        sync_guild_id=int(guild_id) if guild_id else None,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        message_content_intent=os.getenv("MESSAGE_CONTENT_INTENT", "false").strip().lower() in {"1", "true", "yes", "on"},
    )
