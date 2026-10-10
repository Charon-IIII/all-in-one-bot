from __future__ import annotations

import discord
from discord.ext import commands


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        settings = await self.bot.store.get_settings(member.guild.id)
        channel_id = settings.get("welcome_channel_id")
        if not settings["modules"].get("welcome") or not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        text = settings["welcome_message"]
        replacements = {
            "{mention}": member.mention,
            "{user}": discord.utils.escape_markdown(member.display_name),
            "{server}": discord.utils.escape_markdown(member.guild.name),
            "{count}": str(member.guild.member_count or "?"),
        }
        for token, value in replacements.items():
            text = text.replace(token, value)
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
