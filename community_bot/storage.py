from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from typing import Any

import aiosqlite


DEFAULTS: dict[str, Any] = {
    "modules": {"moderation": True, "logging": True, "role_management": True, "welcome": False, "automod": False, "flagged_words": False, "translator": False, "reputation": True},
    "commands": {},
    "log_channel_id": None,
    "log_channels": {},
    "welcome_channel_id": None,
    "welcome_message": "Welcome {mention} to **{server}**! You are member #{count}.",
    "automod_invites": True,
    "automod_repeats": True,
    "automod_timeout_seconds": 300,
    "automod_flagged_words": [],
    "mute_role_id": None,
    "escalation_enabled": False,
    "escalation_window_days": 30,
    "escalation_levels": [
        {"threshold": 2, "action": "timeout", "duration_minutes": 30},
        {"threshold": 3, "action": "timeout", "duration_minutes": 4320},
    ],
    "escalation_alert_channel_id": None,
    "escalation_alert_threshold": 3,
    "escalation_alert_role_ids": [],
    "reputation_max_give": 5,
    "reputation_max_take": 5,
    "reputation_auto_thanks": True,
    "reputation_leaderboard_channel_id": None,
    "reputation_leaderboard_message_id": None,
    "reputation_awards_enabled": True,
    "reputation_awards_configured": False,
    "reputation_first_place_role_id": None,
    "reputation_favorites_role_id": None,
}


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

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
                created_at TEXT NOT NULL,
                dm_delivered INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_cases_guild_target ON mod_cases(guild_id, target_id, id DESC);
            CREATE TABLE IF NOT EXISTS active_role_mutes (
                guild_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY(guild_id, target_id)
            );
            CREATE INDEX IF NOT EXISTS idx_role_mutes_expiry ON active_role_mutes(expires_at);
            CREATE TABLE IF NOT EXISTS reputation_scores (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS reputation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                giver_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                source_message_id INTEGER,
                auto_day TEXT,
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_rep_source_message
                ON reputation_events(guild_id, source_message_id) WHERE source_message_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_rep_auto_pair_daily
                ON reputation_events(guild_id, giver_id, recipient_id, auto_day) WHERE auto_day IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_rep_leaderboard
                ON reputation_scores(guild_id, score DESC, user_id ASC);
            """
        )
        async with self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='reputation_scores'"
        ) as cur:
            reputation_schema = await cur.fetchone()
        if reputation_schema and "CHECK(SCORE>=0)" in "".join(str(reputation_schema[0]).upper().split()):
            # Older versions prohibited negative scores. Rebuild the table while
            # preserving existing scores so upgrades do not require a DB reset.
            await self.db.execute("BEGIN IMMEDIATE")
            await self.db.execute("DROP INDEX IF EXISTS idx_rep_leaderboard")
            await self.db.execute("ALTER TABLE reputation_scores RENAME TO reputation_scores_legacy")
            await self.db.execute(
                "CREATE TABLE reputation_scores ("
                "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, score INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY(guild_id, user_id))"
            )
            await self.db.execute(
                "INSERT INTO reputation_scores(guild_id,user_id,score) "
                "SELECT guild_id,user_id,score FROM reputation_scores_legacy"
            )
            await self.db.execute("DROP TABLE reputation_scores_legacy")
            await self.db.execute(
                "CREATE INDEX idx_rep_leaderboard "
                "ON reputation_scores(guild_id, score DESC, user_id ASC)"
            )
            await self.db.commit()
        async with self.db.execute("PRAGMA table_info(mod_cases)") as cur:
            case_columns = {row["name"] for row in await cur.fetchall()}
        if "dm_delivered" not in case_columns:
            await self.db.execute("ALTER TABLE mod_cases ADD COLUMN dm_delivered INTEGER")
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
        return {
            **DEFAULTS,
            **saved,
            "modules": {**DEFAULTS["modules"], **saved.get("modules", {})},
            "log_channels": {**DEFAULTS["log_channels"], **saved.get("log_channels", {})},
        }

    async def update_settings(self, guild_id: int, **changes: Any) -> dict[str, Any]:
        assert self.db is not None
        async with self._write_lock:
            current = await self.get_settings(guild_id)
            if "modules" in changes:
                current["modules"] = {**current["modules"], **changes.pop("modules")}
            if "log_channels" in changes:
                current["log_channels"] = {**current["log_channels"], **changes.pop("log_channels")}
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
        async with self._write_lock:
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

    async def recent_violation_count(self, guild_id: int, target_id: int, since: str) -> int:
        """Count moderation cases that represent violations, excluding unbans."""
        assert self.db is not None
        async with self.db.execute(
            "SELECT COUNT(*) FROM mod_cases WHERE guild_id=? AND target_id=? AND created_at>=? "
            "AND action NOT LIKE 'Unban%' AND action NOT LIKE 'Unmute%'",
            (guild_id, target_id, since),
        ) as cur:
            row = await cur.fetchone()
        return int(row[0])

    async def recent_violation_cases(self, guild_id: int, target_id: int, since: str, limit: int = 5) -> list[aiosqlite.Row]:
        assert self.db is not None
        async with self.db.execute(
            "SELECT * FROM mod_cases WHERE guild_id=? AND target_id=? AND created_at>=? "
            "AND action NOT LIKE 'Unban%' AND action NOT LIKE 'Unmute%' ORDER BY id DESC LIMIT ?",
            (guild_id, target_id, since, limit),
        ) as cur:
            return await cur.fetchall()

    async def set_active_role_mute(
        self, guild_id: int, target_id: int, role_id: int, expires_at: str, moderator_id: int, reason: str
    ) -> None:
        assert self.db is not None
        async with self._write_lock:
            await self.db.execute(
                "INSERT INTO active_role_mutes(guild_id,target_id,role_id,expires_at,moderator_id,reason) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(guild_id,target_id) DO UPDATE SET role_id=excluded.role_id, expires_at=excluded.expires_at, "
                "moderator_id=excluded.moderator_id, reason=excluded.reason",
                (guild_id, target_id, role_id, expires_at, moderator_id, reason),
            )
            await self.db.commit()

    async def get_active_role_mute(self, guild_id: int, target_id: int) -> aiosqlite.Row | None:
        assert self.db is not None
        async with self.db.execute(
            "SELECT * FROM active_role_mutes WHERE guild_id=? AND target_id=?", (guild_id, target_id)
        ) as cur:
            return await cur.fetchone()

    async def expired_role_mutes(self, now: str) -> list[aiosqlite.Row]:
        assert self.db is not None
        async with self.db.execute("SELECT * FROM active_role_mutes WHERE expires_at<=?", (now,)) as cur:
            return await cur.fetchall()

    async def delete_active_role_mute(self, guild_id: int, target_id: int) -> None:
        assert self.db is not None
        async with self._write_lock:
            await self.db.execute("DELETE FROM active_role_mutes WHERE guild_id=? AND target_id=?", (guild_id, target_id))
            await self.db.commit()

    async def set_case_dm_delivery(self, case_id: int, delivered: bool) -> None:
        assert self.db is not None
        async with self._write_lock:
            await self.db.execute("UPDATE mod_cases SET dm_delivered=? WHERE id=?", (int(delivered), case_id))
            await self.db.commit()

    async def change_reputation(
        self,
        guild_id: int,
        giver_id: int,
        recipient_id: int,
        amount: int,
        event_type: str,
        *,
        source_message_id: int | None = None,
        auto_day: str | None = None,
    ) -> int | None:
        """Apply a reputation change atomically; return the new score or None if rejected."""
        assert self.db is not None
        async with self._write_lock:
            await self.db.execute("BEGIN IMMEDIATE")
            cur = await self.db.execute(
                "INSERT OR IGNORE INTO reputation_events "
                "(guild_id,giver_id,recipient_id,amount,event_type,source_message_id,auto_day,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    guild_id,
                    giver_id,
                    recipient_id,
                    amount,
                    event_type,
                    source_message_id,
                    auto_day,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            if cur.rowcount == 0:
                await self.db.rollback()
                return None
            await self.db.execute(
                "INSERT INTO reputation_scores(guild_id,user_id,score) VALUES(?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET score=score+excluded.score",
                (guild_id, recipient_id, amount),
            )
            async with self.db.execute(
                "SELECT score FROM reputation_scores WHERE guild_id=? AND user_id=?",
                (guild_id, recipient_id),
            ) as cur:
                row = await cur.fetchone()
            await self.db.commit()
            return int(row[0]) if row else 0

    async def reputation_score(self, guild_id: int, user_id: int) -> int:
        assert self.db is not None
        async with self._write_lock:
            async with self.db.execute(
                "SELECT score FROM reputation_scores WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def reputation_rank(
        self, guild_id: int, user_id: int, member_ids: set[int] | None = None
    ) -> int | None:
        assert self.db is not None
        async with self._write_lock:
            async with self.db.execute(
                "SELECT user_id, score FROM reputation_scores WHERE guild_id=? "
                "ORDER BY score DESC, user_id ASC",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
            if member_ids is not None:
                rows = [row for row in rows if int(row["user_id"]) in member_ids]
            for rank, row in enumerate(rows, 1):
                if int(row["user_id"]) == user_id:
                    return rank
            return None

    async def reputation_leaderboard(
        self, guild_id: int, limit: int | None = 10
    ) -> list[aiosqlite.Row]:
        assert self.db is not None
        async with self._write_lock:
            query = (
                "SELECT user_id, score FROM reputation_scores WHERE guild_id=? "
                "ORDER BY score DESC, user_id ASC"
            )
            params: tuple[int, ...] = (guild_id,)
            if limit is not None:
                query += " LIMIT ?"
                params += (limit,)
            async with self.db.execute(query, params) as cur:
                return await cur.fetchall()
