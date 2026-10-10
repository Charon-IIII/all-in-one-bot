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
        active_member_ids = {guild_member.id for guild_member in interaction.guild.members}
        active_member_ids.add(target.id)
        rank = await self.bot.store.reputation_rank(interaction.guild_id, target.id, active_member_ids)
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

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            if not guild.chunked:
                try:
                    await guild.chunk(cache=True)
                except (discord.Forbidden, discord.HTTPException):
                    logging.getLogger(__name__).warning(
                        "Could not load the member list for reputation role sync in guild %s", guild.id
                    )
            settings = await self.bot.store.get_settings(guild.id)
            if settings["modules"].get("reputation", True) and not settings.get("reputation_awards_configured", False):
                # Migrate existing servers to the requested default: automatic award roles.
                await self.bot.store.update_settings(
                    guild.id,
                    reputation_awards_enabled=True,
                    reputation_awards_configured=True,
                )
            await self.refresh_leaderboard(guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        self.queue_leaderboard_refresh(member.guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        self.queue_leaderboard_refresh(member.guild.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        settings = await self.bot.store.get_settings(role.guild.id)
        award_role_ids = {
            settings.get("reputation_first_place_role_id"),
            settings.get("reputation_favorites_role_id"),
        }
        if role.id in award_role_ids and settings.get("reputation_awards_enabled", True):
            self.queue_leaderboard_refresh(role.guild.id)

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
        rows = await self.active_leaderboard_rows(guild, 10)
        settings = await self.bot.store.get_settings(guild.id)
        embed = discord.Embed(
            title="🏆 THΞ CΦRCLΞ • HALL OF APPRECIATION",
            description="A little appreciation goes a long way. Celebrate the members making this community brighter.",
            color=discord.Color.from_rgb(255, 190, 72),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if rows:
            first_role_id = settings.get("reputation_first_place_role_id")
            favorites_role_id = settings.get("reputation_favorites_role_id")
            awards_enabled = settings.get("reputation_awards_enabled", False) and settings["modules"].get("reputation", True)
            top = rows[0]
            top_value = f"<@{top['user_id']}>\n**{int(top['score'])} reputation**"
            if awards_enabled and first_role_id:
                top_value += f" · <@&{first_role_id}>"
            embed.add_field(name="👑  #1 · MOST LOVED", value=top_value, inline=False)

            favorites = rows[1:3]
            if favorites:
                favorite_lines = []
                for position, row in enumerate(favorites, 2):
                    medal = "🥈" if position == 2 else "🥉"
                    role = f" · <@&{favorites_role_id}>" if awards_enabled and favorites_role_id else ""
                    favorite_lines.append(
                        f"{medal} **#{position}** <@{row['user_id']}> — **{int(row['score'])} rep**{role}"
                    )
                embed.add_field(name="💖  COMMUNITY FAVORITES", value="\n".join(favorite_lines), inline=False)

            if len(rows) > 3:
                lines = [
                    f"✨ **#{position}** <@{row['user_id']}> — **{int(row['score'])} rep**"
                    for position, row in enumerate(rows[3:], 4)
                ]
                embed.add_field(name="🌟  TOP TEN", value="\n".join(lines), inline=False)
        else:
            embed.add_field(
                name="Your moment starts here",
                value="Give someone a little appreciation with `/rep give` or reply **thank you** to their message.",
                inline=False,
            )
        embed.set_footer(text="Every point is a thank-you from the community · Updates automatically")
        return embed

    async def active_leaderboard_rows(self, guild: discord.Guild, limit: int | None = None):
        rows = await self.bot.store.reputation_leaderboard(guild.id, None)
        active_rows = [row for row in rows if guild.get_member(int(row["user_id"])) is not None]
        return active_rows[:limit] if limit is not None else active_rows

    async def configure_award_roles(self, guild: discord.Guild, enabled: bool) -> tuple[bool, str]:
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            return False, "I need the **Manage Roles** permission to manage reputation award roles."
        if enabled and not guild.chunked:
            try:
                await guild.chunk(cache=True)
            except (discord.Forbidden, discord.HTTPException):
                return False, "I could not load the server member list. Enable **Server Members Intent** in the Developer Portal and restart the bot."

        if enabled:
            success, error = await self._ensure_award_roles(guild)
            if not success:
                return False, error

        await self.bot.store.update_settings(
            guild.id,
            reputation_awards_enabled=enabled,
            reputation_awards_configured=True,
        )
        if not await self.sync_award_roles(guild):
            return False, "The setting was saved, but I could not synchronize the award roles. Check my permissions and role hierarchy."
        if enabled:
            return True, "Reputation awards are enabled: **Most Loved** is reserved for #1, and **Community Favorite** is shared by #2 and #3."
        return True, "Reputation awards are disabled and their roles have been removed from members. The roles remain in the server if you want to enable awards again."

    async def _ensure_award_roles(self, guild: discord.Guild) -> tuple[bool, str]:
        settings = await self.bot.store.get_settings(guild.id)
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            return False, "I need the **Manage Roles** permission to create and assign reputation award roles."

        role_specs = (
            ("reputation_first_place_role_id", "Most Loved", discord.Color.from_rgb(255, 190, 72)),
            ("reputation_favorites_role_id", "Community Favorite", discord.Color.from_rgb(235, 115, 175)),
        )
        try:
            for key, name, color in role_specs:
                role_id = settings.get(key)
                role = guild.get_role(role_id) if role_id else None
                if role is None:
                    role = await guild.create_role(
                        name=name,
                        permissions=discord.Permissions.none(),
                        colour=color,
                        hoist=True,
                        mentionable=False,
                        reason="Create bot-managed reputation leaderboard award role",
                    )
                    await self.bot.store.update_settings(guild.id, **{key: role.id})
                if not role.is_assignable():
                    return False, f"I cannot manage the **{role.name}** role. Move my highest role above it."
        except discord.Forbidden:
            return False, "I could not create or manage the award roles. Check my **Manage Roles** permission and role hierarchy."
        except discord.HTTPException:
            logging.getLogger(__name__).exception("Could not set up reputation roles in guild %s", guild.id)
            return False, "Discord could not create the award roles just now. Please try again later."
        return True, ""

    async def sync_award_roles(self, guild: discord.Guild) -> bool:
        settings = await self.bot.store.get_settings(guild.id)
        awards_enabled = settings.get("reputation_awards_enabled", True)
        module_enabled = settings["modules"].get("reputation", True)
        if awards_enabled and module_enabled:
            success, error = await self._ensure_award_roles(guild)
            if not success:
                logging.getLogger(__name__).warning(
                    "Could not provision reputation award roles in guild %s: %s", guild.id, error
                )
                return False
            settings = await self.bot.store.get_settings(guild.id)
        first_role_id = settings.get("reputation_first_place_role_id")
        favorites_role_id = settings.get("reputation_favorites_role_id")
        configured_ids = {role_id for role_id in (first_role_id, favorites_role_id) if role_id}
        if not configured_ids:
            return True

        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            return False
        if not guild.chunked:
            try:
                await guild.chunk(cache=True)
            except (discord.Forbidden, discord.HTTPException):
                logging.getLogger(__name__).warning(
                    "Could not load members for reputation role sync in guild %s; enable Server Members Intent",
                    guild.id,
                )
                return False
        roles = {
            role_id: guild.get_role(role_id)
            for role_id in configured_ids
        }
        if any(role is not None and not role.is_assignable() for role in roles.values()):
            return False

        first_place: set[int] = set()
        favorites: set[int] = set()
        if awards_enabled and module_enabled:
            if any(roles.get(role_id) is None for role_id in (first_role_id, favorites_role_id)):
                return False
            rows = await self.active_leaderboard_rows(guild, 3)
            if rows:
                first_place.add(int(rows[0]["user_id"]))
                favorites.update(int(row["user_id"]) for row in rows[1:3])

        desired_by_role = {
            first_role_id: first_place,
            favorites_role_id: favorites,
        }
        role_set = {role for role in roles.values() if role is not None}
        members = {member.id: member for member in guild.members}
        for role in role_set:
            members.update({member.id: member for member in role.members})
        for user_id in first_place | favorites:
            if user_id not in members:
                try:
                    members[user_id] = await guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue

        success = True
        for member in members.values():
            for role_id, expected_ids in desired_by_role.items():
                role = roles.get(role_id)
                if role is None:
                    continue
                has_role = role in member.roles
                should_have = member.id in expected_ids
                if has_role == should_have:
                    continue
                try:
                    if should_have:
                        await member.add_roles(role, reason="Reconcile reputation leaderboard award roles")
                    else:
                        await member.remove_roles(role, reason="Reconcile reputation leaderboard award roles")
                except (discord.Forbidden, discord.HTTPException):
                    success = False
                    logging.getLogger(__name__).warning(
                        "Could not synchronize reputation role %s for member %s in guild %s",
                        role.id,
                        member.id,
                        guild.id,
                    )
        return success

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
        await self.sync_award_roles(guild)
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
