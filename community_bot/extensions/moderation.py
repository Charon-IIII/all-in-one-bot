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

    async def record(self, interaction: discord.Interaction, member: discord.Member, action: str, reason: str) -> int:
        case_id = await self.bot.store.add_case(interaction.guild_id, member.id, interaction.user.id, action, reason)
        self.bot.dispatch("mod_case", interaction.guild, member, interaction.user, action, reason, case_id)
        return case_id

    @mod.command(name="warn", description="Verwarnung dokumentieren")
    @module_enabled("moderation", "mod-warn")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben") -> None:
        case_id = await self.record(interaction, member, "warn", reason)
        await interaction.response.send_message(f"{member.mention} wurde verwarnt. Fall **#{case_id}**.", ephemeral=True)

    @mod.command(name="timeout", description="Mitglied temporär stummschalten (bis 28 Tage)")
    @module_enabled("moderation", "mod-timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(minutes="Dauer in Minuten (1–40320)")
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "Kein Grund angegeben") -> None:
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Dieses Mitglied kann aufgrund der Rollen-Hierarchie nicht moderiert werden.", ephemeral=True)
            return
        await member.timeout(timedelta(minutes=minutes), reason=f"{interaction.user}: {reason}")
        case_id = await self.record(interaction, member, f"timeout {minutes}m", reason)
        await interaction.response.send_message(f"{member.mention} erhielt {minutes} Minuten Timeout. Fall **#{case_id}**.", ephemeral=True)

    @mod.command(name="kick", description="Mitglied vom Server entfernen")
    @module_enabled("moderation", "mod-kick")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben") -> None:
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Dieses Mitglied kann aufgrund der Rollen-Hierarchie nicht entfernt werden.", ephemeral=True)
            return
        await member.kick(reason=f"{interaction.user}: {reason}")
        case_id = await self.record(interaction, member, "kick", reason)
        await interaction.response.send_message(f"{member} wurde entfernt. Fall **#{case_id}**.", ephemeral=True)

    @mod.command(name="ban", description="Mitglied bannen")
    @module_enabled("moderation", "mod-ban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben") -> None:
        if member.id == interaction.user.id or member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Dieses Mitglied kann aufgrund der Rollen-Hierarchie nicht gebannt werden.", ephemeral=True)
            return
        await interaction.guild.ban(member, reason=f"{interaction.user}: {reason}", delete_message_seconds=0)
        case_id = await self.record(interaction, member, "ban", reason)
        await interaction.response.send_message(f"{member} wurde gebannt. Fall **#{case_id}**.", ephemeral=True)

    @mod.command(name="unban", description="Mitglied anhand der Discord-ID entbannen")
    @module_enabled("moderation", "mod-unban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Kein Grund angegeben") -> None:
        try:
            target_id = int(user_id)
            user = await self.bot.fetch_user(target_id)
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("Ungültige ID oder dieses Konto ist nicht gebannt.", ephemeral=True)
            return
        case_id = await self.bot.store.add_case(interaction.guild_id, target_id, interaction.user.id, "unban", reason)
        self.bot.dispatch("mod_case", interaction.guild, user, interaction.user, "unban", reason, case_id)
        await interaction.response.send_message(f"{user} wurde entbannt. Fall **#{case_id}**.", ephemeral=True)

    @mod.command(name="purge", description="Letzte Nachrichten im Kanal löschen")
    @module_enabled("moderation", "mod-purge")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Dieser Befehl funktioniert nur in Textkanälen.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount, reason=f"Purge von {interaction.user}")
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
