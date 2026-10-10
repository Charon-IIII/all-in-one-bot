from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

from .config import load_settings
from .storage import Store

EXTENSIONS = (
    "community_bot.extensions.configuration",
    "community_bot.extensions.moderation",
    "community_bot.extensions.logging_events",
    "community_bot.extensions.welcome",
    "community_bot.extensions.automod",
    "community_bot.extensions.translator",
)


class CommunityBot(commands.Bot):
    def __init__(self, settings) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.auto_moderation_execution = True
        intents.message_content = settings.message_content_intent
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.store = Store(str(settings.database_path))
        self.suppressed_message_deletes: set[int] = set()

    async def setup_hook(self) -> None:
        self.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        await self.store.open()
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        if self.settings.sync_guild_id:
            guild = discord.Object(id=self.settings.sync_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Synced slash commands for test server %s", self.settings.sync_guild_id)
        else:
            await self.tree.sync()

    async def close(self) -> None:
        await self.store.close()
        await super().close()


async def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    async with CommunityBot(settings) as bot:
        await bot.start(settings.token)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
