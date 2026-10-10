from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


MODULES = ["moderation", "logging", "welcome", "automod", "translator"]
COMMANDS = ["mod-warn", "mod-timeout", "mod-kick", "mod-ban", "mod-unban", "mod-purge", "mod-history"]


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    config = app_commands.Group(name="config", description="Bot-Module und Serverkanäle konfigurieren")

    @config.command(name="setup", description="Standardmodule für diesen Server aktivieren")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        await self.bot.store.update_settings(
            interaction.guild_id,
            modules={"moderation": True, "logging": True, "welcome": False, "automod": False},
        )
        await interaction.response.send_message(
            "Grundsetup gespeichert. Setze mit `/config log-channel` einen Logkanal; Welcome und Automod kannst du danach gezielt aktivieren.",
            ephemeral=True,
        )

    @config.command(name="module", description="Ein Bot-Modul für diesen Server an- oder ausschalten")
    @app_commands.describe(name="Modulname", enabled="Soll das Modul aktiv sein?")
    @app_commands.choices(name=[app_commands.Choice(name=x, value=x) for x in MODULES])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def module(self, interaction: discord.Interaction, name: app_commands.Choice[str], enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, modules={name.value: enabled})
        note = " Für Automod muss zusätzlich MESSAGE_CONTENT_INTENT=true gesetzt und der Message Content Intent im Developer Portal aktiviert sein." if name.value == "automod" and enabled else ""
        if name.value == "translator":
            note = " Der Schalter ist vorbereitet; die DeepL-Erweiterung wird nach Einbindung deines Codes verfügbar."
        await interaction.response.send_message(f"Modul **{name.value}** {'aktiviert' if enabled else 'deaktiviert'}.{note}", ephemeral=True)

    @config.command(name="command", description="Einen einzelnen Moderationsbefehl an- oder ausschalten")
    @app_commands.describe(name="Befehlsschlüssel, zum Beispiel mod-warn", enabled="Soll der Befehl aktiv sein?")
    @app_commands.choices(name=[app_commands.Choice(name=x, value=x) for x in COMMANDS])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def command_toggle(self, interaction: discord.Interaction, name: app_commands.Choice[str], enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, commands={name.value: enabled})
        await interaction.response.send_message(f"Befehl **{name.value}** {'aktiviert' if enabled else 'deaktiviert'}.", ephemeral=True)

    @config.command(name="log-channel", description="Kanal für Server- und Moderationslogs festlegen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self.bot.store.update_settings(interaction.guild_id, log_channel_id=channel.id)
        await interaction.response.send_message(f"Logs gehen ab jetzt nach {channel.mention}.", ephemeral=True)

    @config.command(name="welcome-channel", description="Begrüßungskanal setzen oder leeren")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.store.update_settings(interaction.guild_id, welcome_channel_id=channel.id if channel else None)
        await interaction.response.send_message(f"Begrüßungskanal: {channel.mention if channel else 'aus'}.", ephemeral=True)

    @config.command(name="welcome-message", description="Begrüßungstext festlegen")
    @app_commands.describe(message="Platzhalter: {mention}, {user}, {server}, {count}")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_message(self, interaction: discord.Interaction, message: str) -> None:
        if len(message) > 1800:
            await interaction.response.send_message("Der Text darf höchstens 1800 Zeichen lang sein.", ephemeral=True)
            return
        await self.bot.store.update_settings(interaction.guild_id, welcome_message=message)
        await interaction.response.send_message("Begrüßungstext gespeichert.", ephemeral=True)

    @config.command(name="show", description="Aktuelle Bot-Einstellungen anzeigen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def show(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        enabled = ", ".join(name for name, active in settings["modules"].items() if active) or "keine"
        disabled = ", ".join(name for name, active in settings["commands"].items() if not active) or "keine"
        log = f"<#{settings['log_channel_id']}>" if settings["log_channel_id"] else "nicht gesetzt"
        welcome = f"<#{settings['welcome_channel_id']}>" if settings["welcome_channel_id"] else "nicht gesetzt"
        await interaction.response.send_message(f"**Aktive Module:** {enabled}\n**Deaktivierte Einzelbefehle:** {disabled}\n**Logkanal:** {log}\n**Welcome-Kanal:** {welcome}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Configuration(bot))
