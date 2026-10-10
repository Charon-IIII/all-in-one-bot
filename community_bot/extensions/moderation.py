from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import module_enabled


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    mod = app_commands.Group(name="mod", description="Moderation und Fallhistorie")

    async def record(
        self,
        interaction: discord.Interaction,
        member: discord.User | discord.Member,
        action: str,
        reason: str,
        dm_channel: discord.DMChannel | None = None,
    ) -> tuple[int, bool]:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        window_days = max(1, int(settings.get("escalation_window_days", 30)))
        since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        previous_count = 0
        if not action.startswith("Entbannung"):
            previous_count = await self.bot.store.recent_violation_count(interaction.guild_id, member.id, since)
        case_id = await self.bot.store.add_case(interaction.guild_id, member.id, interaction.user.id, action, reason)
        embed = discord.Embed(
            title="Moderationsmaßnahme auf einem Server",
            description=f"Auf **{discord.utils.escape_markdown(interaction.guild.name)}** wurde eine Moderationsmaßnahme für dich protokolliert.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Aktion", value=action, inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Grund", value=reason[:1000], inline=False)
        embed.set_footer(text=f"Fall #{case_id}")
        try:
            if dm_channel is None:
                await member.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            else:
                await dm_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException):
            dm_sent = False
        await self.bot.store.set_case_dm_delivery(case_id, dm_sent)
        self.bot.dispatch("mod_case", interaction.guild, member, interaction.user, action, reason, case_id, dm_sent)
        if not action.startswith("Entbannung"):
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
            title="Wiederholte Regelverstöße – Staff-Prüfung",
            description=(
                f"{member.mention} hat **{current_count}** dokumentierte Moderationsfälle innerhalb von "
                f"{max(1, int(settings.get('escalation_window_days', 30)))} Tagen.\n"
                "Bitte prüft, ob eine weitere Maßnahme nötig ist. Dieser Hinweis löst selbst keine Strafe aus."
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(name="Neuer Fall", value=f"#{case_id} · {action}\nGrund: {reason[:500]}", inline=False)
        cases = await self.bot.store.recent_violation_cases(interaction.guild_id, member.id, since, limit=5)
        lines = [f"#{row['id']} · {row['action']} · <@{row['moderator_id']}> · {row['reason'][:100]}" for row in cases]
        embed.add_field(name="Letzte Fälle", value="\n".join(lines)[:1000] or "Keine", inline=False)
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
            return "Verwarnung", None
        selected = None
        for level in sorted(settings.get("escalation_levels", []), key=lambda entry: int(entry.get("threshold", 0))):
            if violation_count >= int(level.get("threshold", 0)):
                selected = level
        if selected is None:
            return "Verwarnung", None
        action = selected.get("action")
        if action == "timeout":
            duration = max(30, min(int(selected.get("duration_minutes", 30)), 40320))
            return f"Timeout ({duration} Minuten)", duration
        if action in {"kick", "ban"}:
            return ("Kick" if action == "kick" else "Ban"), None
        return "Verwarnung", None

    async def apply_escalation(
        self, interaction: discord.Interaction, member: discord.Member, action: str, minutes: int | None, reason: str
    ) -> str | None:
        guild = interaction.guild
        bot_member = guild.me
        actor = interaction.user
        if member.id == actor.id or (actor.id != guild.owner_id and member.top_role >= actor.top_role):
            return "Deine Rollen-Hierarchie erlaubt diese Eskalation nicht."
        if bot_member is None or member.top_role >= bot_member.top_role:
            return "Die Rollen-Hierarchie des Bots erlaubt diese Eskalation nicht."
        try:
            if action.startswith("Timeout"):
                if not actor.guild_permissions.moderate_members or not bot_member.guild_permissions.moderate_members:
                    return "Die Berechtigung für einen Timeout fehlt."
                await member.timeout(timedelta(minutes=minutes or 30), reason=self.audit_reason(interaction, reason))
            elif action == "Kick":
                if not actor.guild_permissions.kick_members or not bot_member.guild_permissions.kick_members:
                    return "Die Berechtigung für einen Kick fehlt."
                await member.kick(reason=self.audit_reason(interaction, reason))
            elif action == "Ban":
                if not actor.guild_permissions.ban_members or not bot_member.guild_permissions.ban_members:
                    return "Die Berechtigung für einen Ban fehlt."
                await guild.ban(member, reason=self.audit_reason(interaction, reason), delete_message_seconds=0)
        except discord.HTTPException as exc:
            return f"Discord hat die Eskalation abgelehnt ({exc})."
        return None

    @staticmethod
    async def prepare_dm(member: discord.User | discord.Member) -> discord.DMChannel | None:
        """Open the DM while a kicked/banned member still shares the server with the bot."""
        try:
            return await member.create_dm()
        except (discord.Forbidden, discord.HTTPException):
            return None

    @staticmethod
    def delivery_note(dm_sent: bool) -> str:
        return "DM an das Mitglied gesendet." if dm_sent else "DM konnte nicht zugestellt werden (möglicherweise DMs deaktiviert)."

    @staticmethod
    def audit_reason(interaction: discord.Interaction, reason: str) -> str:
        return f"{interaction.user} | {reason}"[:512]

    @staticmethod
    async def clean_reason(interaction: discord.Interaction, reason: str) -> str | None:
        cleaned = reason.strip()
        if cleaned:
            return cleaned
        await interaction.response.send_message("Der Grund darf nicht leer sein oder nur aus Leerzeichen bestehen.", ephemeral=True)
        return None

    @mod.command(name="warn", description="Verwarnung dokumentieren")
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
        if action in {"Kick", "Ban"}:
            dm_channel = await self.prepare_dm(member)
        if action != "Verwarnung":
            failure = await self.apply_escalation(interaction, member, action, minutes, reason)
        if failure:
            recorded_action = f"Verwarnung (Eskalation fehlgeschlagen: {action})"
            result = f"Eskalation **{action}** konnte nicht ausgeführt werden: {failure} Die Verwarnung wurde trotzdem gespeichert."
        else:
            recorded_action = action
            result = f"Automatische Maßnahme: **{action}**. " if action != "Verwarnung" else "Verwarnung erfasst. "
        case_id, dm_sent = await self.record(interaction, member, recorded_action, reason, dm_channel)
        await interaction.response.send_message(f"{member.mention}: {result} Fall **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="timeout", description="Mitglied temporär stummschalten (bis 28 Tage)")
    @module_enabled("moderation", "mod-timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(minutes="Dauer in Minuten (1–40320)")
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Dieses Mitglied kann aufgrund der Rollen-Hierarchie nicht moderiert werden.", ephemeral=True)
            return
        await member.timeout(timedelta(minutes=minutes), reason=self.audit_reason(interaction, reason))
        case_id, dm_sent = await self.record(interaction, member, f"Timeout ({minutes} Minuten)", reason)
        await interaction.response.send_message(f"{member.mention} erhielt {minutes} Minuten Timeout. Fall **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="kick", description="Mitglied vom Server entfernen")
    @module_enabled("moderation", "mod-kick")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Dieses Mitglied kann aufgrund der Rollen-Hierarchie nicht entfernt werden.", ephemeral=True)
            return
        dm_channel = await self.prepare_dm(member)
        await member.kick(reason=self.audit_reason(interaction, reason))
        case_id, dm_sent = await self.record(interaction, member, "Kick", reason, dm_channel)
        await interaction.response.send_message(f"{member} wurde entfernt. Fall **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="ban", description="Mitglied bannen")
    @module_enabled("moderation", "mod-ban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Dieses Mitglied kann aufgrund der Rollen-Hierarchie nicht gebannt werden.", ephemeral=True)
            return
        dm_channel = await self.prepare_dm(member)
        await interaction.guild.ban(member, reason=self.audit_reason(interaction, reason), delete_message_seconds=0)
        case_id, dm_sent = await self.record(interaction, member, "Ban", reason, dm_channel)
        await interaction.response.send_message(f"{member} wurde gebannt. Fall **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="unban", description="Mitglied anhand der Discord-ID entbannen")
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
            await interaction.response.send_message("Ungültige ID oder dieses Konto ist nicht gebannt.", ephemeral=True)
            return
        case_id, dm_sent = await self.record(interaction, user, "Entbannung", reason)
        await interaction.response.send_message(f"{user} wurde entbannt. Fall **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

    @mod.command(name="purge", description="Letzte Nachrichten im Kanal löschen")
    @module_enabled("moderation", "mod-purge")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        reason: app_commands.Range[str, 1, 500] | None = None,
    ) -> None:
        reason = reason.strip() if reason and reason.strip() else "Kein Grund angegeben"
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Dieser Befehl funktioniert nur in Textkanälen.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount, reason=f"{interaction.user} | {reason}"[:512])
        self.bot.dispatch("mod_action", interaction.guild, interaction.user, "Nachrichten gelöscht", reason, f"{len(deleted)} Nachrichten in {interaction.channel.mention}")
        await interaction.followup.send(f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True)

    @mod.command(name="history", description="Letzte Bot-Fälle eines Mitglieds anzeigen")
    @module_enabled("moderation", "mod-history")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def history(self, interaction: discord.Interaction, member: discord.Member) -> None:
        rows = await self.bot.store.recent_cases(interaction.guild_id, member.id)
        if not rows:
            await interaction.response.send_message("Für dieses Mitglied sind keine Fälle gespeichert.", ephemeral=True)
            return
        lines = [f"**#{r['id']}** · {r['action']} · <@{r['moderator_id']}> · {r['reason'][:120]}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
