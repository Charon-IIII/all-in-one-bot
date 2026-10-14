from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord.ext import commands


class EventLogs(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.used_audit_entries: dict[tuple[int, str, int | None], set[int]] = {}

    async def audit_attribution(
        self,
        guild: discord.Guild,
        actions: tuple[discord.AuditLogAction, ...],
        target_id: int | None,
        *,
        channel_id: int | None = None,
        count: int | None = None,
    ) -> tuple[str, str] | None:
        """Return a moderator and reason only for a fresh, matching audit entry."""
        now = datetime.now(timezone.utc)
        key = (guild.id, ",".join(action.name for action in actions), target_id)
        used = self.used_audit_entries.setdefault(key, set())
        try:
            for action in actions:
                async for entry in guild.audit_logs(limit=10, action=action):
                    if entry.id in used or abs((now - entry.created_at).total_seconds()) > 12:
                        continue
                    entry_target_id = getattr(entry.target, "id", None)
                    is_bulk_delete = action == discord.AuditLogAction.message_bulk_delete
                    if target_id is not None and entry_target_id != target_id:
                        continue
                    extra_channel = getattr(getattr(entry, "extra", None), "channel", None)
                    if channel_id is not None and not is_bulk_delete and getattr(extra_channel, "id", None) != channel_id:
                        continue
                    extra_count = getattr(getattr(entry, "extra", None), "count", None)
                    if count is not None and extra_count is not None and extra_count != count:
                        continue
                    used.add(entry.id)
                    # Keep this lightweight for long-running bots.
                    if len(used) > 100:
                        used.clear()
                    actor = entry.user
                    if actor is None:
                        return None
                    return (f"{actor.mention} (`{actor.id}`)", entry.reason or "No reason recorded in the audit log")
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    @staticmethod
    def add_attribution(embed: discord.Embed, attribution: tuple[str, str] | None) -> None:
        if attribution:
            embed.add_field(name="Moderator / Actor", value=attribution[0], inline=False)
            embed.add_field(name="Reason", value=attribution[1][:1000], inline=False)
        else:
            embed.add_field(name="Moderator / Reason", value="No unambiguous match was found in the Discord audit log.", inline=False)

    async def post(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        category: str = "messages",
        *,
        source_channel: discord.abc.GuildChannel | discord.Thread | None = None,
    ) -> None:
        settings = await self.bot.store.get_settings(guild.id)
        if not settings["modules"].get("logging"):
            return
        channel_ids: set[int] = set()
        primary_channel_id = settings.get("log_channels", {}).get(category) or settings.get("log_channel_id")
        if primary_channel_id:
            channel_ids.add(int(primary_channel_id))
        if category == "moderation":
            additional_channel_id = settings.get("moderation_extra_log_channel_id")
            if additional_channel_id:
                channel_ids.add(int(additional_channel_id))
            if settings.get("moderation_log_command_channel") and source_channel is not None:
                channel_ids.add(source_channel.id)
        destinations: dict[int, discord.TextChannel | discord.Thread] = {}
        for channel_id in channel_ids:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel | discord.Thread):
                destinations[channel_id] = channel
        if category == "moderation" and settings.get("moderation_log_command_channel"):
            if isinstance(source_channel, discord.TextChannel | discord.Thread):
                destinations[source_channel.id] = source_channel
        for channel in destinations.values():
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        suppressed = getattr(self.bot, "suppressed_message_deletes", set())
        if message.id in suppressed:
            suppressed.discard(message.id)
            return
        embed = discord.Embed(title="Message deleted", color=discord.Color.red())
        embed.add_field(name="Author", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        body = message.content or "Content unavailable (Message Content Intent is disabled or the message was not cached)."
        embed.add_field(name="Content", value=body[:1000], inline=False)
        attribution = await self.audit_attribution(
            message.guild,
            (discord.AuditLogAction.message_delete,),
            message.author.id,
            channel_id=message.channel.id,
        )
        self.add_attribution(embed, attribution)
        await self.post(message.guild, embed, "messages")

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages or messages[0].guild is None:
            return
        embed = discord.Embed(title="Bulk message deletion", description=f"{len(messages)} messages in {messages[0].channel.mention}", color=discord.Color.orange())
        attribution = await self.audit_attribution(
            messages[0].guild,
            (discord.AuditLogAction.message_bulk_delete,),
            messages[0].channel.id,
            count=len(messages),
        )
        self.add_attribution(embed, attribution)
        await self.post(messages[0].guild, embed, "messages")

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        embed = discord.Embed(title="Message edited", color=discord.Color.gold(), url=after.jump_url)
        embed.add_field(name="Author / Channel", value=f"{before.author.mention} · {before.channel.mention}", inline=False)
        embed.add_field(name="Before", value=(before.content or "(empty)")[:900], inline=False)
        embed.add_field(name="After", value=(after.content or "(empty)")[:900], inline=False)
        await self.post(before.guild, embed, "messages")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self.post(member.guild, discord.Embed(title="Member joined", description=f"{member.mention} · `{member.id}`", color=discord.Color.green()), "members")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        embed = discord.Embed(title="Member left", description=f"{member} · `{member.id}`", color=discord.Color.dark_grey())
        attribution = await self.audit_attribution(member.guild, (discord.AuditLogAction.kick,), member.id)
        if attribution:
            embed.title = "Member kicked"
            self.add_attribution(embed, attribution)
        await self.post(member.guild, embed, "members")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick != after.nick:
            embed = discord.Embed(title="Member nickname updated", color=discord.Color.blurple())
            embed.add_field(name="Member", value=f"{after.mention} (`{after.id}`)", inline=False)
            embed.add_field(name="Before", value=before.nick or before.name, inline=True)
            embed.add_field(name="After", value=after.nick or after.name, inline=True)
            attribution = await self.audit_attribution(
                after.guild,
                (discord.AuditLogAction.member_update,),
                after.id,
            )
            self.add_attribution(embed, attribution)
            await self.post(after.guild, embed, "members")

        old_roles = {role.id: role for role in before.roles if role != before.guild.default_role}
        new_roles = {role.id: role for role in after.roles if role != after.guild.default_role}
        added = [role.mention for rid, role in new_roles.items() if rid not in old_roles]
        removed = [role.mention for rid, role in old_roles.items() if rid not in new_roles]
        if added or removed:
            embed = discord.Embed(title="Member roles updated", color=discord.Color.blurple())
            embed.add_field(name="Member", value=f"{after.mention} (`{after.id}`)", inline=False)
            if added:
                embed.add_field(name="Roles added", value=", ".join(added)[:1000], inline=False)
            if removed:
                embed.add_field(name="Roles removed", value=", ".join(removed)[:1000], inline=False)
            attribution = await self.audit_attribution(
                after.guild,
                (discord.AuditLogAction.member_role_update,),
                after.id,
            )
            self.add_attribution(embed, attribution)
            await self.post(after.guild, embed, "roles")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        embed = discord.Embed(title="Channel created", description=f"{channel.mention} · `{channel.id}`", color=discord.Color.green())
        self.add_attribution(embed, await self.audit_attribution(channel.guild, (discord.AuditLogAction.channel_create,), channel.id))
        await self.post(channel.guild, embed, "channels")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        embed = discord.Embed(title="Channel deleted", description=f"#{channel.name} · `{channel.id}`", color=discord.Color.red())
        self.add_attribution(embed, await self.audit_attribution(channel.guild, (discord.AuditLogAction.channel_delete,), channel.id))
        await self.post(channel.guild, embed, "channels")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        before_category = getattr(before, "category", None)
        after_category = getattr(after, "category", None)
        if getattr(before_category, "id", None) != getattr(after_category, "id", None):
            changes.append(f"**Category:** {before_category.name if before_category else 'None'} → {after_category.name if after_category else 'None'}")
        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                changes.append(f"**Previous topic:** {(before.topic or '(empty)')[:300]}\n**New topic:** {(after.topic or '(empty)')[:300]}")
        if changes:
            embed = discord.Embed(title=f"Channel updated: #{after.name}", description="\n".join(changes), color=discord.Color.gold())
            self.add_attribution(embed, await self.audit_attribution(after.guild, (discord.AuditLogAction.channel_update,), after.id))
            await self.post(after.guild, embed, "channels")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        embed = discord.Embed(title="Role created", description=f"{role.mention} · `{role.id}`", color=discord.Color.green())
        self.add_attribution(embed, await self.audit_attribution(role.guild, (discord.AuditLogAction.role_create,), role.id))
        await self.post(role.guild, embed, "roles")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        embed = discord.Embed(title="Role deleted", description=f"{role.name} · `{role.id}`", color=discord.Color.red())
        self.add_attribution(embed, await self.audit_attribution(role.guild, (discord.AuditLogAction.role_delete,), role.id))
        await self.post(role.guild, embed, "roles")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.color != after.color:
            changes.append(f"**Color:** {before.color} → {after.color}")
        if before.hoist != after.hoist:
            changes.append(f"**Display separately:** {before.hoist} → {after.hoist}")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionable:** {before.mentionable} → {after.mentionable}")
        if changes:
            embed = discord.Embed(title=f"Role updated: {after.name}", description="\n".join(changes), color=discord.Color.gold())
            self.add_attribution(embed, await self.audit_attribution(after.guild, (discord.AuditLogAction.role_update,), after.id))
            await self.post(after.guild, embed, "roles")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if before.channel == after.channel:
            return
        if before.channel is None:
            description = f"{member.mention} joined {after.channel.mention}."
        elif after.channel is None:
            description = f"{member.mention} left {before.channel.mention}."
        else:
            description = f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}."
        await self.post(member.guild, discord.Embed(title="Voice channel updated", description=description, color=discord.Color.blurple()), "voice")

    @commands.Cog.listener()
    async def on_guild_ban_add(self, guild: discord.Guild, user: discord.User) -> None:
        embed = discord.Embed(title="Member banned", description=f"{user} · `{user.id}`", color=discord.Color.red())
        self.add_attribution(embed, await self.audit_attribution(guild, (discord.AuditLogAction.ban,), user.id))
        await self.post(guild, embed, "moderation")

    @commands.Cog.listener()
    async def on_guild_ban_remove(self, guild: discord.Guild, user: discord.User) -> None:
        embed = discord.Embed(title="Member unbanned", description=f"{user} · `{user.id}`", color=discord.Color.green())
        self.add_attribution(embed, await self.audit_attribution(guild, (discord.AuditLogAction.unban,), user.id))
        await self.post(guild, embed, "moderation")

    @commands.Cog.listener()
    async def on_mod_case(
        self, guild, target, moderator, action: str, reason: str, case_id: int, dm_sent: bool | None, source_channel=None
    ) -> None:
        embed = discord.Embed(title=f"Moderation case #{case_id}: {action}", color=discord.Color.orange())
        embed.add_field(name="Member", value=f"{target} (`{target.id}`)", inline=False)
        embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason[:1000], inline=False)
        dm_status = "Disabled by server configuration" if dm_sent is None else "Delivered" if dm_sent else "Not delivered"
        embed.add_field(name="DM notification", value=dm_status, inline=False)
        await self.post(guild, embed, "moderation", source_channel=source_channel)

    @commands.Cog.listener()
    async def on_mod_action(self, guild, moderator, action: str, reason: str, details: str, source_channel=None) -> None:
        embed = discord.Embed(title=f"Moderation action: {action}", color=discord.Color.orange())
        embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)
        embed.add_field(name="Details", value=details[:1000], inline=False)
        embed.add_field(name="Reason", value=reason[:1000], inline=False)
        await self.post(guild, embed, "moderation", source_channel=source_channel)

    @commands.Cog.listener()
    async def on_automod_action(self, action: discord.AutoModAction) -> None:
        guild = action.guild
        member = action.member
        embed = discord.Embed(title="AutoMod: Message blocked", color=discord.Color.red())
        embed.add_field(name="Member", value=f"{member} (`{action.user_id}`)" if member else f"User ID: `{action.user_id}`", inline=False)
        if action.channel is not None:
            embed.add_field(name="Channel", value=action.channel.mention, inline=True)
        embed.add_field(name="Matched rule", value=(action.matched_keyword or "Discord Commonly Flagged Words preset")[:300], inline=False)
        embed.add_field(name="Rule ID", value=f"`{action.rule_id}`", inline=True)
        if action.content:
            embed.add_field(name="Message", value=action.content[:900], inline=False)
        await self.post(guild, embed, "automod")

    @commands.Cog.listener()
    async def on_automod_block(self, guild, member, channel, reason: str, content: str) -> None:
        embed = discord.Embed(title="AutoMod: Message blocked", color=discord.Color.red())
        embed.add_field(name="Member", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Matched rule", value=reason[:300], inline=False)
        embed.add_field(name="Message", value=content[:900], inline=False)
        await self.post(guild, embed, "automod")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventLogs(bot))
