from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord.ext import commands


INVITE_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.IGNORECASE)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.recent: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        settings = await self.bot.store.get_settings(message.guild.id)
        if not settings["modules"].get("automod"):
            return
        if message.author.guild_permissions.manage_messages:
            return

        reason = None
        content = message.content
        if settings.get("automod_invites", True) and INVITE_RE.search(content):
            reason = "Discord invite link"
        if content.strip() and settings.get("automod_repeats", True):
            key = (message.guild.id, message.author.id)
            now = time.monotonic()
            recent = self.recent[key]
            while recent and now - recent[0][0] > 12:
                recent.popleft()
            recent.append((now, content.casefold().strip()))
            if len(recent) >= 5 and len({entry[1] for entry in list(recent)[-5:]}) <= 2:
                reason = reason or "Repeated messages"
                recent.clear()

        if reason is None:
            return
        try:
            await message.delete()
        except discord.HTTPException:
            return
        duration = max(60, min(int(settings.get("automod_timeout_seconds", 300)), 28 * 24 * 60 * 60))
        if message.author.top_role < message.guild.me.top_role and message.guild.me.guild_permissions.moderate_members:
            try:
                await message.author.timeout(timedelta(seconds=duration), reason=f"Automod: {reason}")
            except discord.HTTPException:
                pass
        try:
            await message.channel.send(
                f"{message.author.mention}, deine Nachricht wurde wegen {reason} entfernt.",
                delete_after=8,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))
