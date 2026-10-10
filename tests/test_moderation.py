from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiosqlite
import discord

from community_bot.extensions.moderation import Moderation
from community_bot.storage import Store


class FakeStore:
    async def add_case(self, guild_id, target_id, moderator_id, action, reason):
        self.saved = (guild_id, target_id, moderator_id, action, reason)
        return 42

    async def set_case_dm_delivery(self, case_id, delivered):
        self.dm_delivery = (case_id, delivered)


class ModerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = FakeStore()
        self.bot = SimpleNamespace(store=self.store, dispatch=Mock())
        self.cog = Moderation(self.bot)
        self.moderator = SimpleNamespace(id=10, mention="<@10>")
        self.guild = SimpleNamespace(id=20, name="Community Server")
        self.interaction = SimpleNamespace(
            guild_id=20,
            guild=self.guild,
            user=self.moderator,
        )
        self.member = SimpleNamespace(id=30, send=AsyncMock())

    def test_all_moderation_actions_require_a_reason(self):
        action_names = {"warn", "timeout", "kick", "ban", "unban", "purge"}
        commands = {command.name: command for command in Moderation.mod.commands}
        for name in action_names:
            with self.subTest(command=name):
                params = {parameter.name: parameter for parameter in commands[name].parameters}
                self.assertIn("reason", params)
                self.assertTrue(params["reason"].required)

    async def test_case_sends_member_a_dm_and_logs_moderator_reason_and_delivery(self):
        case_id, dm_sent = await self.cog.record(self.interaction, self.member, "Ban", "Regelverstoß")

        self.assertEqual(case_id, 42)
        self.assertTrue(dm_sent)
        self.assertEqual(self.store.saved, (20, 30, 10, "Ban", "Regelverstoß"))
        self.assertEqual(self.store.dm_delivery, (42, True))
        dm_embed = self.member.send.await_args.kwargs["embed"]
        fields = {field.name: field.value for field in dm_embed.fields}
        self.assertEqual(fields["Aktion"], "Ban")
        self.assertEqual(fields["Moderator"], "<@10> (`10`)")
        self.assertEqual(fields["Grund"], "Regelverstoß")
        self.assertEqual(dm_embed.footer.text, "Fall #42")
        self.bot.dispatch.assert_called_once_with(
            "mod_case", self.guild, self.member, self.moderator, "Ban", "Regelverstoß", 42, True
        )

    async def test_forbidden_dm_does_not_hide_the_action_and_is_logged(self):
        response = SimpleNamespace(status=403, reason="Forbidden", headers={})
        self.member.send.side_effect = discord.Forbidden(response, "DMs disabled")

        case_id, dm_sent = await self.cog.record(self.interaction, self.member, "Verwarnung", "Bitte bleib respektvoll")

        self.assertEqual(case_id, 42)
        self.assertFalse(dm_sent)
        self.assertEqual(self.store.dm_delivery, (42, False))
        self.bot.dispatch.assert_called_once_with(
            "mod_case", self.guild, self.member, self.moderator, "Verwarnung", "Bitte bleib respektvoll", 42, False
        )

    async def test_whitespace_only_reason_is_rejected(self):
        self.interaction.response = SimpleNamespace(send_message=AsyncMock())

        reason = await self.cog.clean_reason(self.interaction, "   \t  ")

        self.assertIsNone(reason)
        self.interaction.response.send_message.assert_awaited_once()

    async def test_existing_case_database_is_migrated_for_dm_delivery(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "old.sqlite3"
            db = await aiosqlite.connect(database_path)
            await db.execute(
                "CREATE TABLE mod_cases (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, "
                "target_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, action TEXT NOT NULL, "
                "reason TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            await db.execute(
                "INSERT INTO mod_cases(guild_id,target_id,moderator_id,action,reason,created_at) "
                "VALUES(20,30,10,'warn','existing reason','2026-01-01T00:00:00+00:00')"
            )
            await db.commit()
            await db.close()

            store = Store(str(database_path))
            await store.open()
            rows = await store.recent_cases(20, 30)
            self.assertEqual(rows[0]["reason"], "existing reason")
            self.assertIsNone(rows[0]["dm_delivered"])
            await store.set_case_dm_delivery(rows[0]["id"], False)
            rows = await store.recent_cases(20, 30)
            self.assertEqual(rows[0]["dm_delivered"], 0)
            await store.close()


if __name__ == "__main__":
    unittest.main()
