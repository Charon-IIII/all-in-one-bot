from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


MODULES = ["moderation", "logging", "welcome", "automod", "flagged-words", "translator"]
COMMANDS = ["mod-warn", "mod-timeout", "mod-kick", "mod-ban", "mod-unban", "mod-purge", "mod-history"]
LOG_CATEGORIES = ["messages", "members", "channels", "roles", "voice", "moderation", "automod"]
ESCALATION_ACTIONS = ["timeout", "kick", "ban"]


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    config = app_commands.Group(name="config", description="Bot-Module und Serverkanäle konfigurieren")
    flagged_words = app_commands.Group(name="flagged-words", description="Discord AutoMod-Wortfilter konfigurieren", parent=config)
    escalation = app_commands.Group(name="escalation", description="Regelbasierte Strafen und Staff-Hinweise konfigurieren", parent=config)

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

    @escalation.command(name="enabled", description="Automatische Eskalation bei /mod warn an- oder ausschalten")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_enabled(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_enabled=enabled)
        state = "aktiviert" if enabled else "deaktiviert"
        await interaction.response.send_message(
            f"Automatische Eskalation {state}. Sie wirkt nur auf neue `/mod warn`-Fälle; bestehende Bot-Cases bilden die Vorgeschichte.",
            ephemeral=True,
        )

    @escalation.command(name="window", description="Zeitraum setzen, in dem Moderationsfälle für Eskalation zählen")
    @app_commands.describe(days="1 bis 365 Tage")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_window(self, interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_window_days=days)
        await interaction.response.send_message(f"Eskalations- und Fallhinweis-Zeitraum: **{days} Tage**.", ephemeral=True)

    @escalation.command(name="level", description="Maßnahme für eine bestimmte Anzahl dokumentierter Verstöße festlegen")
    @app_commands.describe(
        threshold="Verstoßnummer, ab der diese Maßnahme greift (2 bis 20)",
        action="timeout, kick oder ban",
        duration_minutes="Nur für Timeout: mindestens 30 Minuten; ohne Angabe gelten 30 Minuten",
    )
    @app_commands.choices(action=[app_commands.Choice(name=x, value=x) for x in ESCALATION_ACTIONS])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_level(
        self,
        interaction: discord.Interaction,
        threshold: app_commands.Range[int, 2, 20],
        action: app_commands.Choice[str],
        duration_minutes: app_commands.Range[int, 30, 40320] | None = None,
    ) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        levels = [level for level in settings.get("escalation_levels", []) if int(level.get("threshold", 0)) != threshold]
        level = {"threshold": threshold, "action": action.value}
        if action.value == "timeout":
            level["duration_minutes"] = duration_minutes or 30
        levels.append(level)
        levels.sort(key=lambda entry: int(entry["threshold"]))
        await self.bot.store.update_settings(interaction.guild_id, escalation_levels=levels)
        detail = f" für {level['duration_minutes']} Minuten" if action.value == "timeout" else ""
        await interaction.response.send_message(f"Ab Verstoß **#{threshold}** gilt **{action.value}**{detail}.", ephemeral=True)

    @escalation.command(name="level-remove", description="Eine automatische Eskalationsstufe entfernen")
    @app_commands.describe(threshold="Die gespeicherte Verstoßnummer")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_level_remove(self, interaction: discord.Interaction, threshold: app_commands.Range[int, 2, 20]) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        levels = [level for level in settings.get("escalation_levels", []) if int(level.get("threshold", 0)) != threshold]
        if len(levels) == len(settings.get("escalation_levels", [])):
            await interaction.response.send_message("Für diese Verstoßnummer ist keine Stufe gespeichert.", ephemeral=True)
            return
        await self.bot.store.update_settings(interaction.guild_id, escalation_levels=levels)
        await interaction.response.send_message(f"Eskalationsstufe **#{threshold}** entfernt.", ephemeral=True)

    @escalation.command(name="alert-channel", description="Privaten Staff-Kanal für wiederholte Fälle setzen oder leeren")
    @app_commands.describe(channel="Nur Staff sichtbarer Textkanal; leer deaktiviert die Hinweise")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_alert_channel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_alert_channel_id=channel.id if channel else None)
        await interaction.response.send_message(f"Wiederholungsfall-Hinweise: {channel.mention if channel else 'aus'}.", ephemeral=True)

    @escalation.command(name="alert-threshold", description="Ab welcher Fallanzahl Staff informiert wird")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_alert_threshold(self, interaction: discord.Interaction, count: app_commands.Range[int, 2, 20]) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_alert_threshold=count)
        await interaction.response.send_message(f"Staff-Hinweis ab **{count} dokumentierten Fällen** innerhalb des Eskalationszeitraums.", ephemeral=True)

    @escalation.command(name="alert-role", description="Eine Rolle bei Staff-Hinweisen erwähnen oder ausnehmen")
    @app_commands.describe(role="Staff-Rolle", enabled="Soll diese Rolle erwähnt werden?")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_alert_role(self, interaction: discord.Interaction, role: discord.Role, enabled: bool) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        role_ids = set(settings.get("escalation_alert_role_ids", []))
        if enabled:
            role_ids.add(role.id)
        else:
            role_ids.discard(role.id)
        await self.bot.store.update_settings(interaction.guild_id, escalation_alert_role_ids=sorted(role_ids))
        await interaction.response.send_message(f"Rolle {role.mention} wird bei Staff-Hinweisen {'erwähnt' if enabled else 'nicht mehr erwähnt'}.", ephemeral=True)

    @escalation.command(name="show", description="Eskalations- und Staff-Hinweisregeln anzeigen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_show(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        levels = settings.get("escalation_levels", [])
        level_text = "\n".join(
            f"Ab #{level['threshold']}: {level['action']}" + (f" ({level.get('duration_minutes', 30)} Min.)" if level['action'] == "timeout" else "")
            for level in levels
        ) or "Keine Eskalationsstufen gesetzt"
        channel_id = settings.get("escalation_alert_channel_id")
        roles = settings.get("escalation_alert_role_ids", [])
        await interaction.response.send_message(
            f"**Automatische Eskalation:** {'an' if settings.get('escalation_enabled') else 'aus'}\n"
            f"**Zeitraum:** {settings.get('escalation_window_days', 30)} Tage\n"
            f"**Stufen:**\n{level_text}\n"
            f"**Staff-Hinweise:** {f'<#{channel_id}>' if channel_id else 'aus'} ab {settings.get('escalation_alert_threshold', 3)} Fällen\n"
            f"**Erwähnte Staff-Rollen:** {', '.join(f'<@&{role_id}>' for role_id in roles) or 'keine'}",
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
        await interaction.response.send_message(f"**Aktive Module:** {enabled}\n**Deaktivierte Einzelbefehle:** {disabled}\n**Standard-Logkanal:** {log}\n**Kategorie-Logrouten:** {routes}\n**Welcome-Kanal:** {welcome}\n**Eskalation:** {'an' if settings.get('escalation_enabled') else 'aus'}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Configuration(bot))
