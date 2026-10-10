from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


THANKS_MESSAGE = re.compile(
    r"^\s*(?:"
    r"thanks?(?:\s+(?:a lot|so much|a bunch|again|for that|for this|for your help|for helping))?|"
    r"thank\s+you(?:\s+(?:so much|very much|a lot|kindly|for that|for this|for your help|for helping))?|"
    r"thx|ty|tysm|tyvm|thxsm|danke(?:\s+(?:sch[oö]n|dir|euch|viel))?|vielen\s+dank|merci|(?:muchas?\s+)?gracias|"
    r"much\s+appreciated|(?:i\s+)?appreciate\s+(?:it|that)|cheers|"
    r"obrigad[oa]|arigat[oó]u?|спасибо"
    r")(?:[.!?,\s🙏❤️✨]*)$",
    re.IGNORECASE,
)


class Reputation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._refresh_tasks: dict[int, asyncio.Task] = {}

    rep = app_commands.Group(name="rep", description="Give, take, and view server reputation")

    async def _settings(self, interaction: discord.Interaction) -> dict:
        return await self.bot.store.get_settings(interaction.guild_id)

    async def _enabled(self, interaction: discord.Interaction) -> bool:
        settings = await self._settings(interaction)
        if not settings["modules"].get("reputation", True):
            await interaction.response.send_message("Reputation is disabled on this server.", ephemeral=True)
            return False
        return True

    @rep.command(name="give", description="Give reputation to another member")
    @app_commands.guild_only()
    async def give(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 100],
    ) -> None:
        if not await self._enabled(interaction):
            return
        settings = await self._settings(interaction)
        maximum = max(1, min(100, int(settings.get("reputation_max_give", 5))))
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("You can give reputation to another human member only.", ephemeral=True)
            return
        if amount > maximum:
            await interaction.response.send_message(f"You can give at most **{maximum} reputation** at a time on this server.", ephemeral=True)
            return
        score = await self.bot.store.change_reputation(
            interaction.guild_id, interaction.user.id, member.id, amount, "give"
        )
        await interaction.response.send_message(
            f"Gave **{amount} reputation** to {member.mention}. Their score is now **{score}**.",
            ephemeral=True,
        )
        self.queue_leaderboard_refresh(interaction.guild_id)

    @rep.command(name="take", description="Take reputation from another member")
    @app_commands.guild_only()
    async def take(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 100],
    ) -> None:
        if not await self._enabled(interaction):
            return
        settings = await self._settings(interaction)
        maximum = max(1, min(100, int(settings.get("reputation_max_take", 5))))
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("You can take reputation from another human member only.", ephemeral=True)
            return
        if amount > maximum:
            await interaction.response.send_message(f"You can take at most **{maximum} reputation** at a time on this server.", ephemeral=True)
            return
        score = await self.bot.store.change_reputation(
            interaction.guild_id, interaction.user.id, member.id, -amount, "take"
        )
        await interaction.response.send_message(
            f"Took **{amount} reputation** from {member.mention}. Their score is now **{score}**.",
            ephemeral=True,
        )
        self.queue_leaderboard_refresh(interaction.guild_id)

    @rep.command(name="score", description="Check your reputation or another member's score")
    @app_commands.guild_only()
    async def score(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if not await self._enabled(interaction):
            return
        target = member or interaction.user
        current = await self.bot.store.reputation_score(interaction.guild_id, target.id)
        rank = await self.bot.store.reputation_rank(interaction.guild_id, target.id)
        rank_text = f"Rank: **#{rank}**" if rank is not None else "Not ranked yet."
        await interaction.response.send_message(
            f"{target.mention} has **{current} reputation**. {rank_text}", ephemeral=True
        )

    @rep.command(name="leaderboard", description="Show this server's reputation leaderboard")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        if not await self._enabled(interaction):
            return
        embed = await self.leaderboard_embed(interaction.guild)
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.webhook_id or not message.content:
            return
        if not THANKS_MESSAGE.fullmatch(message.content.strip()):
            return
        settings = await self.bot.store.get_settings(message.guild.id)
        if not settings["modules"].get("reputation", True) or not settings.get("reputation_auto_thanks", True):
            return
        reference = message.reference
        if reference is None or reference.message_id is None:
            return
        if reference.channel_id is not None and reference.channel_id != message.channel.id:
            return
        try:
            original = await message.channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        if original.author.bot or original.author.id == message.author.id or original.webhook_id:
            return
        score = await self.bot.store.change_reputation(
            message.guild.id,
            message.author.id,
            original.author.id,
            1,
            "thanks",
            source_message_id=message.id,
            auto_day=datetime.now(timezone.utc).date().isoformat(),
        )
        if score is not None:
            self.queue_leaderboard_refresh(message.guild.id)

    def queue_leaderboard_refresh(self, guild_id: int) -> None:
        task = self._refresh_tasks.get(guild_id)
        if task is None or task.done():
            self._refresh_tasks[guild_id] = asyncio.create_task(self._delayed_refresh(guild_id))

    async def _delayed_refresh(self, guild_id: int) -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(2)
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                await self.refresh_leaderboard(guild)
        except Exception:
            logging.getLogger(__name__).exception("Could not refresh the reputation leaderboard for guild %s", guild_id)
        finally:
            if self._refresh_tasks.get(guild_id) is current_task:
                self._refresh_tasks.pop(guild_id, None)

    async def leaderboard_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = await self.bot.store.reputation_leaderboard(guild.id, 10)
        embed = discord.Embed(
            title=f"{guild.name} Reputation Leaderboard"[:256],
            color=discord.Color.gold(),
        )
        if rows:
            lines = []
            previous_score = None
            rank = 0
            for position, row in enumerate(rows, 1):
                score = int(row["score"])
                if score != previous_score:
                    rank = position
                lines.append(f"**{rank}.** <@{row['user_id']}> — **{score}**")
                previous_score = score
            embed.description = "\n".join(lines)
        else:
            embed.description = "No reputation has been awarded yet."
        embed.set_footer(text="Scores update automatically when reputation changes.")
        return embed

    async def configure_leaderboard(self, guild: discord.Guild, channel: discord.TextChannel | None) -> bool:
        settings = await self.bot.store.get_settings(guild.id)
        old_channel_id = settings.get("reputation_leaderboard_channel_id")
        old_message_id = settings.get("reputation_leaderboard_message_id")
        if old_channel_id != (channel.id if channel else None) and old_channel_id and old_message_id:
            await self._delete_leaderboard_post(guild, old_channel_id, old_message_id)
        await self.bot.store.update_settings(
            guild.id,
            reputation_leaderboard_channel_id=channel.id if channel else None,
            reputation_leaderboard_message_id=None if old_channel_id != (channel.id if channel else None) else old_message_id,
        )
        if channel is None:
            return True
        return await self.refresh_leaderboard(guild)

    async def _delete_leaderboard_post(self, guild: discord.Guild, channel_id: int, message_id: int) -> None:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(message_id)
            if self.bot.user and message.author.id == self.bot.user.id:
                await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def refresh_leaderboard(self, guild: discord.Guild) -> bool:
        settings = await self.bot.store.get_settings(guild.id)
        channel_id = settings.get("reputation_leaderboard_channel_id")
        if not channel_id:
            return False
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        if not isinstance(channel, discord.TextChannel):
            return False
        embed = await self.leaderboard_embed(guild)
        message = None
        message_id = settings.get("reputation_leaderboard_message_id")
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                message = None
            except (discord.Forbidden, discord.HTTPException):
                return False
        try:
            if message is None:
                message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            else:
                await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            return False
        await self.bot.store.update_settings(guild.id, reputation_leaderboard_message_id=message.id)
        return True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reputation(bot))
