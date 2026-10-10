from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite


DEFAULTS: dict[str, Any] = {
    "modules": {"moderation": True, "logging": True, "welcome": False, "automod": False, "translator": False},
    "commands": {},
    "log_channel_id": None,
    "welcome_channel_id": None,
    "welcome_message": "Willkommen {mention} auf **{server}**! Du bist Mitglied Nummer {count}.",
    "automod_invites": True,
    "automod_repeats": True,
    "automod_timeout_seconds": 300,
}


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA foreign_keys=ON")
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                settings_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cases_guild_target ON mod_cases(guild_id, target_id, id DESC);
            """
        )
        await self.db.commit()

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        assert self.db is not None
        async with self.db.execute("SELECT settings_json FROM guild_settings WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
        saved = json.loads(row[0]) if row else {}
        return {**DEFAULTS, **saved, "modules": {**DEFAULTS["modules"], **saved.get("modules", {})}}

    async def update_settings(self, guild_id: int, **changes: Any) -> dict[str, Any]:
        assert self.db is not None
        current = await self.get_settings(guild_id)
        if "modules" in changes:
            current["modules"] = {**current["modules"], **changes.pop("modules")}
        current.update(changes)
        await self.db.execute(
            "INSERT INTO guild_settings(guild_id, settings_json, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at",
            (guild_id, json.dumps(current), datetime.now(timezone.utc).isoformat()),
        )
        await self.db.commit()
        return current

    async def add_case(self, guild_id: int, target_id: int, moderator_id: int, action: str, reason: str) -> int:
        assert self.db is not None
        cur = await self.db.execute(
            "INSERT INTO mod_cases(guild_id,target_id,moderator_id,action,reason,created_at) VALUES(?,?,?,?,?,?)",
            (guild_id, target_id, moderator_id, action, reason, datetime.now(timezone.utc).isoformat()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def recent_cases(self, guild_id: int, target_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        assert self.db is not None
        async with self.db.execute(
            "SELECT * FROM mod_cases WHERE guild_id=? AND target_id=? ORDER BY id DESC LIMIT ?",
            (guild_id, target_id, limit),
        ) as cur:
            return await cur.fetchall()
