from __future__ import annotations

from datetime import timedelta

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
        return case_id, dm_sent

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
        case_id, dm_sent = await self.record(interaction, member, "Verwarnung", reason)
        await interaction.response.send_message(f"{member.mention} wurde verwarnt. Fall **#{case_id}**. {self.delivery_note(dm_sent)}", ephemeral=True)

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
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], reason: app_commands.Range[str, 1, 500]) -> None:
        reason = await self.clean_reason(interaction, reason)
        if reason is None:
            return
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
