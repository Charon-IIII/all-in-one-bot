from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..checks import module_enabled

LOCKDOWN_PERMISSIONS = (
    "send_messages",
    "send_messages_in_threads",
    "create_public_threads",
    "create_private_threads",
)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.expire_role_mutes.start()

    async def cog_unload(self) -> None:
        self.expire_role_mutes.cancel()

    @tasks.loop(seconds=30)
    async def expire_role_mutes(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for mute in await self.bot.store.expired_role_mutes(now):
            guild = self.bot.get_guild(mute["guild_id"])
            if guild is None:
                continue
            member = guild.get_member(mute["target_id"])
            if member is None:
                try:
                    member = await guild.fetch_member(mute["target_id"])
                except discord.NotFound:
                    await self.bot.store.delete_active_role_mute(mute["guild_id"], mute["target_id"])
                    continue
                except discord.HTTPException:
                    continue
            role = guild.get_role(mute["role_id"])
            if role is None:
                await self.bot.store.delete_active_role_mute(mute["guild_id"], mute["target_id"])
                continue
            try:
                if role in member.roles:
                    await member.remove_roles(role, reason="Timed mute expired")
                await self.bot.store.delete_active_role_mute(mute["guild_id"], mute["target_id"])
                moderator = guild.me or self.bot.user
                if moderator is not None:
                    self.bot.dispatch("mod_action", guild, moderator, "Mute role automatically removed", mute["reason"], f"The mute for {member} has expired.")
            except discord.HTTPException:
                # Keep the active record so the next loop retries after permission/API errors.
                continue

    @expire_role_mutes.before_loop
    async def before_expire_role_mutes(self) -> None:
        await self.bot.wait_until_ready()

    mod = app_commands.Group(name="mod", description="Moderation and case history")

    async def record(
        self,
        interaction: discord.Interaction,
        member: discord.User | discord.Member,
        action: str,
        reason: str,
        dm_channel: discord.DMChannel | None = None,
    ) -> tuple[int, bool | None]:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        window_days = max(1, int(settings.get("escalation_window_days", 30)))
        since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        previous_count = 0
        if not action.startswith(("Unban", "Unmute")):
            previous_count = await self.bot.store.recent_violation_count(interaction.guild_id, member.id, since)
        case_id = await self.bot.store.add_case(interaction.guild_id, member.id, interaction.user.id, action, reason)
        dm_enabled = settings.get("moderation_dm_enabled", True)
        dm_sent: bool | None = None
        if dm_enabled:
            embed = discord.Embed(
                title="Moderation case recorded",
                description=f"A moderation action was recorded for you in **{discord.utils.escape_markdown(interaction.guild.name)}**.",
                color=discord.Color.orange(),
            )
            included_fields = settings.get("moderation_dm_fields", {})
            if included_fields.get("action", True):
                embed.add_field(name="Action", value=action[:1000], inline=False)
            if included_fields.get("moderator", True):
                embed.add_field(name="Moderator", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
            if included_fields.get("reason", True):
                embed.add_field(name="Reason", value=reason[:1000], inline=False)
            if included_fields.get("case_number", True):
                embed.set_footer(text=f"Case #{case_id}")
            try:
                if dm_channel is None:
                    await member.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                else:
                    await dm_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException):
                dm_sent = False
        await self.bot.store.set_case_dm_delivery(case_id, dm_sent)
        self.bot.dispatch(
            "mod_case", interaction.guild, member, interaction.user, action, reason, case_id, dm_sent, interaction.channel
        )
        if not action.startswith(("Unban", "Unmute")):
            await self.notify_repeat_case(interaction, member, action, reason, case_id, since, previous_count, settings)
        return case_id, dm_sent

    async def notify_repeat_case(
        self,
        interaction: discord.Interaction,
        member: discord.User | discord.Member,
        action: str,
        reason: str,
        case_id: int,
        since: str,
        previous_count: int,
        settings: dict,
    ) -> None:
        threshold = max(2, int(settings.get("escalation_alert_threshold", 3)))
        current_count = previous_count + 1
        channel_id = settings.get("escalation_alert_channel_id")
        if not channel_id or not previous_count < threshold <= current_count:
            return
        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        role_ids = settings.get("escalation_alert_role_ids", [])
        roles = [role for role_id in role_ids if (role := interaction.guild.get_role(role_id)) is not None]
        role_mentions = " ".join(role.mention for role in roles)
        embed = discord.Embed(
            title="Repeated violations — staff review",
            description=(
                f"{member.mention} has **{current_count}** documented moderation cases within "
                f"{max(1, int(settings.get('escalation_window_days', 30)))} Tagen.\n"
                "Please review whether further action is needed. This alert does not apply a punishment."
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(name="New case", value=f"#{case_id} · {action}\nReason: {reason[:500]}", inline=False)
        cases = await self.bot.store.recent_violation_cases(interaction.guild_id, member.id, since, limit=5)
        lines = [f"#{row['id']} · {row['action']} · <@{row['moderator_id']}> · {row['reason'][:100]}" for row in cases]
        embed.add_field(name="Recent cases", value="\n".join(lines)[:1000] or "None", inline=False)
        try:
            await channel.send(
                content=role_mentions or None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=roles, users=False, everyone=False),
            )
        except discord.HTTPException:
            pass

    @staticmethod
    def escalation_for_count(settings: dict, violation_count: int) -> tuple[str, int | None]:
        if not settings.get("escalation_enabled"):
            return "Warning", None
        selected = None
        for level in sorted(settings.get("escalation_levels", []), key=lambda entry: int(entry.get("threshold", 0))):
            if violation_count >= int(level.get("threshold", 0)):
                selected = level
        if selected is None:
            return "Warning", None
        action = selected.get("action")
        if action == "timeout":
            duration = max(30, min(int(selected.get("duration_minutes", 30)), 40320))
            return f"Timeout ({duration} minutes)", duration
        if action in {"kick", "ban"}:
            return ("Kick" if action == "kick" else "Ban"), None
        return "Warning", None

    async def apply_escalation(
        self, interaction: discord.Interaction, member: discord.Member, action: str, minutes: int | None, reason: str
    ) -> tuple[str | None, str]:
        guild = interaction.guild
        bot_member = guild.me
        actor = interaction.user
        if member.id == actor.id or (actor.id != guild.owner_id and member.top_role >= actor.top_role):
            return "Your role hierarchy does not allow this escalation.", action
        if bot_member is None or member.top_role >= bot_member.top_role:
            return "The bot's role hierarchy does not allow this escalation.", action
        try:
            if action.startswith("Timeout"):
                failure, used_role = await self.apply_timed_mute(interaction, member, minutes or 30, reason)
                if failure:
                    return failure, action
                if used_role:
                    action = f"Mute role ({minutes or 30} minutes)"
            elif action == "Kick":
                if not actor.guild_permissions.kick_members or not bot_member.guild_permissions.kick_members:
                    return "The bot or moderator is missing the Kick Members permission.", action
                await member.kick(reason=self.audit_reason(interaction, reason))
            elif action == "Ban":
                if not actor.guild_permissions.ban_members or not bot_member.guild_permissions.ban_members:
                    return "The bot or moderator is missing the Ban Members permission.", action
                await guild.ban(member, reason=self.audit_reason(interaction, reason), delete_message_seconds=0)
        except discord.HTTPException as exc:
            return f"Discord rejected the escalation ({exc}).", action
        return None, action

    async def apply_timed_mute(
        self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str
    ) -> tuple[str | None, bool]:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        role_id = settings.get("mute_role_id")
        audit_reason = self.audit_reason(interaction, reason)
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role is None:
                return "The configured mute role no longer exists.", True
            if role.is_default() or role.managed or not role.is_assignable():
                return "The configured mute role cannot be assigned by the bot. Check the role hierarchy and Manage Roles permission.", True
            bot_member = interaction.guild.me
            if bot_member is None or member.top_role >= bot_member.top_role:
                return "The bot's role hierarchy does not allow it to mute this member.", True
            await member.add_roles(role, reason=audit_reason)
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
            await self.bot.store.set_active_role_mute(
                interaction.guild_id, member.id, role.id, expires_at, interaction.user.id, reason
            )
            return None, True
        bot_member = interaction.guild.me
        if bot_member is None or not bot_member.guild_permissions.moderate_members:
            return "The bot is missing the Moderate Members permission for Discord timeouts.", False
        await member.timeout(timedelta(minutes=minutes), reason=audit_reason)
        return None, False

    @staticmethod
    async def prepare_dm(member: discord.User | discord.Member) -> discord.DMChannel | None:
        """Open the DM while a kicked/banned member still shares the server with the bot."""
        try:
            return await member.create_dm()
        except (discord.Forbidden, discord.HTTPException):
            return None

    @staticmethod
    def delivery_note(dm_sent: bool | None) -> str:
        if dm_sent is None:
            return "Member DMs are disabled by server configuration."
        return "DM sent to the member." if dm_sent else "Could not deliver the DM (the member may have DMs disabled)."

    @staticmethod
    def audit_reason(interaction: discord.Interaction, reason: str) -> str:
        return f"{interaction.user} | {reason}"[:512]

    @staticmethod
    async def clean_reason(interaction: discord.Interaction, reason: str) -> str | None:
        cleaned = reason.strip()
        if cleaned:
            return cleaned
        await interaction.response.send_message("The reason cannot be empty or contain only whitespace.", ephemeral=True)
        return None

    @mod.command(name="warn", description="Record a warning")
    @module_enabled("moderation", "mod-warn")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        window_days = max(1, int(settings.get("escalation_window_days", 30)))
        since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        prior_count = await self.bot.store.recent_violation_count(interaction.guild_id, member.id, since)
        action, minutes = self.escalation_for_count(settings, prior_count + 1)
        failure = None
        dm_channel = None
        if action in {"Kick", "Ban"} and settings.get("moderation_dm_enabled", True):
            dm_channel = await self.prepare_dm(member)
        if action != "Warning":
            failure, action = await self.apply_escalation(interaction, member, action, minutes, reason)
        if failure:
            recorded_action = f"Warning (escalation failed: {action})"
            result = f"Could not apply escalation **{action}**: {failure} The warning was still recorded."
        else:
            recorded_action = action
            result = f"Automatic action: **{action}**. " if action != "Warning" else "Warning recorded. "
        case_id, dm_sent = await self.record(interaction, member, recorded_action, reason, dm_channel)
        await interaction.response.send_message(f"{member.mention}: {result} Case **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="timeout", description="Temporarily mute a member (mute role or Discord timeout)")
    @module_enabled("moderation", "mod-timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(minutes="Duration in minutes (1–40320)")
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("This member cannot be moderated because of the role hierarchy.", ephemeral=True)
            return
        failure, used_role = await self.apply_timed_mute(interaction, member, minutes, reason)
        if failure:
            await interaction.response.send_message(failure, ephemeral=True)
            return
        action = f"Mute role ({minutes} minutes)" if used_role else f"Timeout ({minutes} minutes)"
        case_id, dm_sent = await self.record(interaction, member, action, reason)
        label = "mute role" if used_role else "Discord timeout"
        await interaction.response.send_message(f"{member.mention} received a {minutes}-minute {label}. Case **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="unmute", description="Remove a mute role and/or Discord timeout")
    @module_enabled("moderation", "mod-unmute")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        if member.id == interaction.user.id or (member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id):
            await interaction.response.send_message("This member cannot be unmuted because of the role hierarchy.", ephemeral=True)
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        active_mute = await self.bot.store.get_active_role_mute(interaction.guild_id, member.id)
        role_id = active_mute["role_id"] if active_mute else settings.get("mute_role_id")
        role = interaction.guild.get_role(role_id) if role_id else None
        bot_member = interaction.guild.me
        if member.is_timed_out() and (bot_member is None or not bot_member.guild_permissions.moderate_members or member.top_role >= bot_member.top_role):
            await interaction.response.send_message("The active Discord timeout cannot be removed because of the bot's permissions or role hierarchy.", ephemeral=True)
            return
        role_removed = False
        if role and role in member.roles:
            if role.is_default() or role.managed or not role.is_assignable():
                await interaction.response.send_message("The bot cannot remove the mute role. Check Manage Roles and the role hierarchy.", ephemeral=True)
                return
            await member.remove_roles(role, reason=self.audit_reason(interaction, reason))
            role_removed = True
        if active_mute:
            await self.bot.store.delete_active_role_mute(interaction.guild_id, member.id)
        timeout_cleared = False
        if member.is_timed_out() and bot_member and bot_member.guild_permissions.moderate_members:
            await member.timeout(None, reason=self.audit_reason(interaction, reason))
            timeout_cleared = True
        if not role_removed and not timeout_cleared:
            await interaction.response.send_message("No active mute role or Discord timeout was found for this member.", ephemeral=True)
            return
        case_id, dm_sent = await self.record(interaction, member, "Unmute", reason)
        await interaction.response.send_message(f"{member.mention} was unmuted. Case **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="kick", description="Remove a member from the server")
    @module_enabled("moderation", "mod-kick")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("This member cannot be removed because of the role hierarchy.", ephemeral=True)
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        dm_channel = await self.prepare_dm(member) if settings.get("moderation_dm_enabled", True) else None
        await member.kick(reason=self.audit_reason(interaction, reason))
        case_id, dm_sent = await self.record(interaction, member, "Kick", reason, dm_channel)
        await interaction.response.send_message(f"{member} was removed. Case **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="ban", description="Ban a member")
    @module_enabled("moderation", "mod-ban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("This member cannot be banned because of the role hierarchy.", ephemeral=True)
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        dm_channel = await self.prepare_dm(member) if settings.get("moderation_dm_enabled", True) else None
        await interaction.guild.ban(member, reason=self.audit_reason(interaction, reason), delete_message_seconds=0)
        case_id, dm_sent = await self.record(interaction, member, "Ban", reason, dm_channel)
        await interaction.response.send_message(f"{member} was banned. Case **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="unban", description="Unban a member by Discord ID")
    @module_enabled("moderation", "mod-unban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        try:
            target_id = int(user_id)
            user = await self.bot.fetch_user(target_id)
            await interaction.guild.unban(user, reason=self.audit_reason(interaction, reason))
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("Invalid ID, or this account is not banned.", ephemeral=True)
            return
        case_id, dm_sent = await self.record(interaction, user, "Unban", reason)
        await interaction.response.send_message(f"{user} was unbanned. Case **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="lockdown", description="Prevent @everyone from sending messages in a text channel")
    @module_enabled("moderation", "mod-lockdown")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(channel="Text channel to lock", reason="Why the channel is being locked")
    async def lockdown(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        reason: app_commands.Range[str, 1, 500],
    ) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        guild = interaction.guild
        bot_member = guild.me
        if bot_member is None or not channel.permissions_for(bot_member).manage_channels:
            await interaction.response.send_message("The bot needs Manage Channels access in the target channel.", ephemeral=True)
            return
        if await self.bot.store.get_channel_lockdown(guild.id, channel.id):
            await interaction.response.send_message(
                "This channel is already locked by the bot. Use `/mod unlock` to restore its saved permissions.", ephemeral=True
            )
            return

        everyone = guild.default_role
        overwrite = channel.overwrites_for(everyone)
        previous = {permission: getattr(overwrite, permission) for permission in LOCKDOWN_PERMISSIONS}
        await interaction.response.defer(ephemeral=True)
        await self.bot.store.set_channel_lockdown(
            guild.id, channel.id, everyone.id, previous, interaction.user.id, reason
        )
        for permission in LOCKDOWN_PERMISSIONS:
            setattr(overwrite, permission, False)
        try:
            await channel.set_permissions(
                everyone,
                overwrite=overwrite,
                reason=self.audit_reason(interaction, reason),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.bot.store.delete_channel_lockdown(guild.id, channel.id)
            await interaction.followup.send(f"Discord could not lock {channel.mention}: {exc}", ephemeral=True)
            return
        details = f"{channel.mention} was locked for @everyone. Saved permissions can be restored with `/mod unlock`."
        self.bot.dispatch(
            "mod_action", guild, interaction.user, "Channel lockdown enabled", reason, details, interaction.channel
        )
        await interaction.followup.send(f"Locked {channel.mention}. Use `/mod unlock` to restore its saved send permissions.", ephemeral=True)

    @mod.command(name="unlock", description="Restore the @everyone send permissions saved by the bot's lockdown")
    @module_enabled("moderation", "mod-unlock")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(channel="Text channel to unlock", reason="Why the channel is being unlocked")
    async def unlock(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        reason: app_commands.Range[str, 1, 500],
    ) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        guild = interaction.guild
        bot_member = guild.me
        if bot_member is None or not channel.permissions_for(bot_member).manage_channels:
            await interaction.response.send_message("The bot needs Manage Channels access in the target channel.", ephemeral=True)
            return
        saved = await self.bot.store.get_channel_lockdown(guild.id, channel.id)
        if saved is None:
            await interaction.response.send_message(
                "There is no saved bot lockdown for this channel, so I won't change its permissions blindly.", ephemeral=True
            )
            return
        everyone = guild.default_role
        if int(saved["everyone_role_id"]) != everyone.id:
            await interaction.response.send_message("The saved @everyone role no longer matches this server. No permissions were changed.", ephemeral=True)
            return
        overwrite = channel.overwrites_for(everyone)
        previous = json.loads(saved["previous_overwrite_json"])
        for permission in LOCKDOWN_PERMISSIONS:
            if permission in previous:
                setattr(overwrite, permission, previous[permission])
        await interaction.response.defer(ephemeral=True)
        try:
            await channel.set_permissions(
                everyone,
                overwrite=None if overwrite.is_empty() else overwrite,
                reason=self.audit_reason(interaction, reason),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.followup.send(f"Discord could not unlock {channel.mention}: {exc}", ephemeral=True)
            return
        await self.bot.store.delete_channel_lockdown(guild.id, channel.id)
        details = f"{channel.mention} was unlocked. The bot restored only the saved @everyone send/thread permissions."
        self.bot.dispatch("mod_action", guild, interaction.user, "Channel lockdown removed", reason, details, interaction.channel)
        await interaction.followup.send(f"Unlocked {channel.mention} and restored its saved send permissions.", ephemeral=True)

    @mod.command(name="lockdown-status", description="Show channels currently locked by the bot")
    @module_enabled("moderation", "mod-lockdown-status")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(channel="Optional channel to check")
    async def lockdown_status(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        if channel is not None:
            row = await self.bot.store.get_channel_lockdown(interaction.guild_id, channel.id)
            if row is None:
                await interaction.response.send_message(f"{channel.mention} is not locked by the bot.", ephemeral=True)
                return
            await interaction.response.send_message(
                f"{channel.mention} is locked by the bot. Moderator: <@{row['moderator_id']}>. Reason: {row['reason']}",
                ephemeral=True,
            )
            return
        rows = await self.bot.store.list_channel_lockdowns(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("No channels are currently locked by the bot.", ephemeral=True)
            return
        lines = [
            f"<#{row['channel_id']}> · locked by <@{row['moderator_id']}> · {str(row['reason'])[:120]}"
            for row in rows[:20]
        ]
        await interaction.response.send_message("**Bot-managed channel lockdowns**\n" + "\n".join(lines), ephemeral=True)

    @mod.command(name="purge", description="Delete recent messages in the channel")
    @module_enabled("moderation", "mod-purge")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        reason: app_commands.Range[str, 1, 500] | None = None,
    ) -> None:
        reason = reason.strip() if reason and reason.strip() else "No reason provided"
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command only works in text channels.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount, reason=f"{interaction.user} | {reason}"[:512])
        self.bot.dispatch(
            "mod_action", interaction.guild, interaction.user, "Messages purged", reason,
            f"{len(deleted)} messages in {interaction.channel.mention}", interaction.channel,
        )
        await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)

    @mod.command(name="history", description="Show a member's recent cases recorded by this bot")
    @module_enabled("moderation", "mod-history")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def history(self, interaction: discord.Interaction, member: discord.Member) -> None:
        rows = await self.bot.store.recent_cases(interaction.guild_id, member.id)
        if not rows:
            await interaction.response.send_message("No cases are saved for this member.", ephemeral=True)
            return
        lines = [f"**#{r['id']}** · {r['action']} · <@{r['moderator_id']}> · {r['reason'][:120]}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
