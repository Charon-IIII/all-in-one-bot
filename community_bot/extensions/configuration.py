from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


MODULES = ["moderation", "logging", "welcome", "automod", "flagged-words", "translator"]
COMMANDS = ["mod-warn", "mod-timeout", "mod-kick", "mod-ban", "mod-unban", "mod-purge", "mod-history"]
LOG_CATEGORIES = ["messages", "members", "channels", "roles", "voice", "moderation", "automod"]


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    config = app_commands.Group(name="config", description="Bot-Module und Serverkanäle konfigurieren")
    flagged_words = app_commands.Group(name="flagged-words", description="Discord AutoMod-Wortfilter konfigurieren", parent=config)

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
        module_key = name.value.replace("-", "_")
        await self.bot.store.update_settings(interaction.guild_id, modules={module_key: enabled})
        note = " Für Invite- und Wiederholungsfilter wird der Message Content Intent gebraucht; der native Wortfilter blockiert Nachrichten bereits vor dem Senden." if name.value == "automod" and enabled else ""
        if name.value == "translator":
            note = " Der Schalter ist vorbereitet; die DeepL-Erweiterung wird nach Einbindung deines Codes verfügbar."
        if module_key in {"automod", "flagged_words"}:
            cog = self.bot.get_cog("AutoMod")
            if cog is not None:
                try:
                    synced = await cog.sync_guild(interaction.guild)
                except (discord.Forbidden, discord.HTTPException) as exc:
                    await interaction.response.send_message(
                        f"Modul gespeichert, aber Discord AutoMod konnte nicht synchronisiert werden: {exc}", ephemeral=True
                    )
                    return
                if module_key == "flagged_words" and enabled and not synced:
                    await interaction.response.send_message("Modul gespeichert, aber dem Bot fehlt die Discord-Berechtigung **Server verwalten** für AutoMod-Regeln.", ephemeral=True)
                    return
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

    @config.command(name="log-route", description="Eine Logkategorie in einen eigenen Kanal leiten oder zurücksetzen")
    @app_commands.describe(category="Logkategorie", channel="Zielkanal; leer setzt die Kategorie auf den Standardkanal zurück")
    @app_commands.choices(category=[app_commands.Choice(name=x, value=x) for x in LOG_CATEGORIES])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_route(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
    ) -> None:
        await self.bot.store.update_settings(interaction.guild_id, log_channels={category.value: channel.id if channel else None})
        destination = f"{channel.mention}" if channel else "Standard-Logkanal"
        await interaction.response.send_message(f"Logs der Kategorie **{category.value}** gehen nach {destination}.", ephemeral=True)

    @flagged_words.command(name="enabled", description="Discords Commonly Flagged Words und eigene Wortfilter schalten")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_enabled(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, modules={"flagged_words": enabled})
        cog = self.bot.get_cog("AutoMod")
        try:
            if cog is not None:
                synced = await cog.sync_guild(interaction.guild)
                if enabled and not synced:
                    await interaction.response.send_message("Einstellung gespeichert, aber dem Bot fehlt die Discord-Berechtigung **Server verwalten** für AutoMod-Regeln.", ephemeral=True)
                    return
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(f"Einstellung gespeichert, aber Discord AutoMod konnte nicht aktualisiert werden: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Commonly Flagged Words und eigene Wortfilter {'aktiviert' if enabled else 'deaktiviert'}. Discord blockiert Treffer vor dem Senden.",
            ephemeral=True,
        )

    @flagged_words.command(name="add", description="Begriff oder Phrase zur eigenen AutoMod-Wortliste hinzufügen")
    @app_commands.describe(word="Begriff/Phrase (max. 60 Zeichen; Discord-Wildcard * möglich)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_add(self, interaction: discord.Interaction, word: app_commands.Range[str, 1, 60]) -> None:
        term = word.strip().casefold()
        if not term:
            await interaction.response.send_message("Der Begriff darf nicht leer sein.", ephemeral=True)
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        terms = list(settings.get("automod_flagged_words", []))
        if term in {entry.casefold() for entry in terms}:
            await interaction.response.send_message("Dieser Begriff steht bereits in der Liste.", ephemeral=True)
            return
        if len(terms) >= 1000:
            await interaction.response.send_message("Die eigene Liste hat das Discord-Limit von 1000 Begriffen erreicht.", ephemeral=True)
            return
        terms.append(term)
        await self.bot.store.update_settings(interaction.guild_id, automod_flagged_words=terms)
        cog = self.bot.get_cog("AutoMod")
        try:
            if cog is not None:
                synced = await cog.sync_guild(interaction.guild)
                if settings["modules"].get("flagged_words") and not synced:
                    await interaction.response.send_message("Begriff gespeichert, aber dem Bot fehlt die Discord-Berechtigung **Server verwalten** für AutoMod-Regeln.", ephemeral=True)
                    return
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(f"Begriff gespeichert, aber die Discord-Regel konnte nicht aktualisiert werden: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"**{discord.utils.escape_markdown(term)}** wurde gespeichert. Aktiviere den Filter mit `/config flagged-words enabled`, falls er noch aus ist.", ephemeral=True)

    @flagged_words.command(name="remove", description="Begriff aus der eigenen AutoMod-Wortliste entfernen")
    @app_commands.describe(word="Exakter gespeicherter Begriff")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_remove(self, interaction: discord.Interaction, word: app_commands.Range[str, 1, 60]) -> None:
        term = word.strip().casefold()
        settings = await self.bot.store.get_settings(interaction.guild_id)
        terms = list(settings.get("automod_flagged_words", []))
        remaining = [entry for entry in terms if entry.casefold() != term]
        if len(remaining) == len(terms):
            await interaction.response.send_message("Der Begriff wurde nicht gefunden.", ephemeral=True)
            return
        await self.bot.store.update_settings(interaction.guild_id, automod_flagged_words=remaining)
        cog = self.bot.get_cog("AutoMod")
        try:
            if cog is not None:
                synced = await cog.sync_guild(interaction.guild)
                if settings["modules"].get("flagged_words") and not synced:
                    await interaction.response.send_message("Begriff entfernt, aber dem Bot fehlt die Discord-Berechtigung **Server verwalten** für AutoMod-Regeln.", ephemeral=True)
                    return
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(f"Begriff entfernt, aber die Discord-Regel konnte nicht aktualisiert werden: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"**{discord.utils.escape_markdown(term)}** wurde entfernt.", ephemeral=True)

    @flagged_words.command(name="list", description="Status und eigene Begriffe anzeigen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_list(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        words = settings.get("automod_flagged_words", [])
        body = ", ".join(discord.utils.escape_markdown(word) for word in words) or "Keine eigenen Begriffe gesetzt."
        if len(body) > 1700:
            body = body[:1697] + "…"
        await interaction.response.send_message(
            f"**Wortfilter:** {'aktiv' if settings['modules'].get('flagged_words') else 'inaktiv'}\n"
            "Zusätzlich ist Discords Commonly Flagged Words Preset aktiv, solange der Wortfilter eingeschaltet ist.\n"
            f"**Eigene Begriffe ({len(words)}):** {body}",
            ephemeral=True,
        )

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
        overrides = settings.get("log_channels", {})
        routes = ", ".join(f"{key}: <#{value}>" for key, value in overrides.items() if value) or "keine (Standardkanal wird verwendet)"
        await interaction.response.send_message(f"**Aktive Module:** {enabled}\n**Deaktivierte Einzelbefehle:** {disabled}\n**Standard-Logkanal:** {log}\n**Kategorie-Logrouten:** {routes}\n**Welcome-Kanal:** {welcome}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Configuration(bot))
