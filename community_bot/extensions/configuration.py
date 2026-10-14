from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

MODULES = ["moderation", "logging", "role-management", "welcome", "automod", "flagged-words", "translator", "reputation"]
COMMANDS = ["mod-warn", "mod-timeout", "mod-unmute", "mod-kick", "mod-ban", "mod-unban", "mod-purge", "mod-history", "mod-lockdown", "mod-unlock", "mod-lockdown-status"]
LOG_CATEGORIES = ["messages", "members", "channels", "roles", "voice", "moderation", "automod"]
ESCALATION_ACTIONS = ["timeout", "kick", "ban"]
MODERATION_DM_FIELDS = {
    "action": "action",
    "moderator": "moderator",
    "reason": "reason",
    "case-number": "case_number",
}


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    config = app_commands.Group(name="config", description="Configure bot modules and server channels")
    flagged_words = app_commands.Group(name="flagged-words", description="Configure Discord AutoMod word filters", parent=config)
    escalation = app_commands.Group(name="escalation", description="Configure escalating actions and staff alerts", parent=config)
    reputation = app_commands.Group(name="reputation", description="Configure server reputation", parent=config)
    moderation_logs = app_commands.Group(name="moderation-logs", description="Configure moderation log copies and member DMs", parent=config)
    lockdown = app_commands.Group(name="lockdown", description="Configure staff role access during channel lockdowns", parent=config)

    @config.command(name="setup", description="Enable the default modules for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        await self.bot.store.update_settings(
            interaction.guild_id,
            modules={"moderation": True, "logging": True, "welcome": False, "automod": False},
        )
        await interaction.response.send_message(
            "Basic setup saved. Next, set `/config log-channel`, optionally route categories with `/config log-route`, and use `/config guide` for a quick setup overview. Enable Welcome, AutoMod, or Translator only if you need them; Reputation is enabled by default.",
            ephemeral=True,
        )

    @config.command(name="guide", description="Show a short setup guide for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def guide(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "**Quick start**\n"
            "1. `/config setup` enables Moderation and Logging.\n"
            "2. `/config log-channel` sets the default log channel; `/config log-route` sends individual categories to separate channels. `/config moderation-logs` configures extra moderation destinations and member DMs.\n"
            "3. Use `/config module` to enable or disable Role Management, Welcome, AutoMod, Translator, or Reputation individually; use `/config reputation` to configure reputation and the leaderboard.\n"
            "4. `/config flagged-words enabled` enables Discord's Commonly Flagged Words preset; manage custom terms with `add`, `remove`, and `list`.\n"
            "5. `/config escalation show` displays the rules; configure them with `/config escalation`. AutoMod hits are logged and never counted as moderation cases.\n"
            "6. Use `/config lockdown bypass-role` to let trusted staff roles keep chatting during lockdowns; `/config lockdown show` reviews them. `/config show` displays the main settings.",
            ephemeral=True,
        )

    @config.command(name="module", description="Enable or disable a bot module on this server")
    @app_commands.describe(name="Module name", enabled="Should the module be enabled?")
    @app_commands.choices(name=[app_commands.Choice(name=x, value=x) for x in MODULES])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def module(self, interaction: discord.Interaction, name: app_commands.Choice[str], enabled: bool) -> None:
        module_key = name.value.replace("-", "_")
        await self.bot.store.update_settings(interaction.guild_id, modules={module_key: enabled})
        note = " The invite and repeat filters require the Message Content Intent; Discord's native word filter blocks messages before they are sent." if name.value == "automod" and enabled else ""
        if name.value == "translator":
            import os
            note = " Reply to a message with `.tr` for automatic language detection or `.tr <language code>` to specify a source language, such as `.tr PL` or `.tr DE`. Use a two-letter source code supported by DeepL. If `DEEPL_API_KEY` is missing from `.env`, add it there and restart the bot."
            if enabled and not os.getenv("DEEPL_API_KEY", "").strip():
                note = " Translator is enabled, but needs `DEEPL_API_KEY` in `.env` and a bot restart."
        if module_key in {"automod", "flagged_words"}:
            cog = self.bot.get_cog("AutoMod")
            if cog is not None:
                try:
                    synced = await cog.sync_guild(interaction.guild)
                except (discord.Forbidden, discord.HTTPException) as exc:
                    await interaction.response.send_message(
                        f"Module setting saved, but Discord AutoMod could not be synced: {exc}", ephemeral=True
                    )
                    return
                if module_key == "flagged_words" and enabled and not synced:
                    await interaction.response.send_message("Module setting saved, but the bot needs the **Manage Server** permission to manage AutoMod rules.", ephemeral=True)
                    return
        if module_key == "reputation":
            cog = self.bot.get_cog("Reputation")
            if cog is not None:
                settings = await self.bot.store.get_settings(interaction.guild_id)
                if enabled and not settings.get("reputation_awards_configured", False):
                    success, message = await cog.configure_award_roles(interaction.guild, True)
                    if not success:
                        note += f" Award roles could not be enabled: {message}"
                elif not await cog.sync_award_roles(interaction.guild):
                    note += " Reputation was updated, but its award roles could not be synchronized; check the bot's Manage Roles permission and role hierarchy."
                await cog.refresh_leaderboard(interaction.guild)
        await interaction.response.send_message(f"Module **{name.value}** {'enabled' if enabled else 'disabled'}.{note}", ephemeral=True)

    @config.command(name="command", description="Enable or disable an individual moderation command")
    @app_commands.describe(name="Command key, for example mod-warn", enabled="Should the command be enabled?")
    @app_commands.choices(name=[app_commands.Choice(name=x, value=x) for x in COMMANDS])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def command_toggle(self, interaction: discord.Interaction, name: app_commands.Choice[str], enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, commands={name.value: enabled})
        await interaction.response.send_message(f"Command **{name.value}** {'enabled' if enabled else 'disabled'}.", ephemeral=True)

    @config.command(name="log-channel", description="Set the default channel for server and moderation logs")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self.bot.store.update_settings(interaction.guild_id, log_channel_id=channel.id)
        await interaction.response.send_message(f"Logs will now be sent to {channel.mention}.", ephemeral=True)

    @config.command(name="log-route", description="Route one log category to a separate channel or reset it")
    @app_commands.describe(category="Log category", channel="Destination channel; leave empty to use the default log channel")
    @app_commands.choices(category=[app_commands.Choice(name=x, value=x) for x in LOG_CATEGORIES])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_route(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
    ) -> None:
        await self.bot.store.update_settings(interaction.guild_id, log_channels={category.value: channel.id if channel else None})
        destination = f"{channel.mention}" if channel else "the default log channel"
        await interaction.response.send_message(f"Logs in **{category.value}** will be sent to {destination}.", ephemeral=True)

    @moderation_logs.command(name="command-channel", description="Copy moderation logs into the channel where a command ran")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def moderation_log_command_channel(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, moderation_log_command_channel=enabled)
        await interaction.response.send_message(
            f"Moderation command log copies in the command channel are now {'enabled' if enabled else 'disabled'}. The configured moderation log route remains active.",
            ephemeral=True,
        )

    @moderation_logs.command(name="additional-channel", description="Set or clear an extra moderation log destination")
    @app_commands.describe(channel="Extra text channel; leave empty to clear this destination")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def moderation_log_additional_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        await self.bot.store.update_settings(
            interaction.guild_id, moderation_extra_log_channel_id=channel.id if channel else None
        )
        await interaction.response.send_message(
            f"Extra moderation log destination: {channel.mention if channel else 'cleared'}.", ephemeral=True
        )

    @moderation_logs.command(name="dm", description="Enable or disable moderation case DMs to affected members")
    @app_commands.describe(enabled="Send the member a DM when a case is recorded?")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def moderation_log_dm(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, moderation_dm_enabled=enabled)
        await interaction.response.send_message(
            f"Moderation case DMs to affected members are now {'enabled' if enabled else 'disabled'}.", ephemeral=True
        )

    @moderation_logs.command(name="dm-field", description="Choose which details are included in moderation case DMs")
    @app_commands.describe(field="Detail to include in member DMs", enabled="Include this detail?")
    @app_commands.choices(field=[app_commands.Choice(name=name, value=value) for name, value in MODERATION_DM_FIELDS.items()])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def moderation_log_dm_field(
        self, interaction: discord.Interaction, field: app_commands.Choice[str], enabled: bool
    ) -> None:
        await self.bot.store.update_settings(
            interaction.guild_id, moderation_dm_fields={field.value: enabled}
        )
        await interaction.response.send_message(
            f"The **{field.name}** detail is now {'included' if enabled else 'omitted'} in moderation case DMs.",
            ephemeral=True,
        )

    @moderation_logs.command(name="show", description="Show moderation log and DM delivery settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def moderation_log_show(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        fields = settings.get("moderation_dm_fields", {})
        included = ", ".join(
            name for name, key in (("action", "action"), ("moderator", "moderator"), ("reason", "reason"), ("case number", "case_number"))
            if fields.get(key, True)
        ) or "none"
        extra_channel_id = settings.get("moderation_extra_log_channel_id")
        await interaction.response.send_message(
            f"**Category route:** configured with `/config log-route moderation`\n"
            f"**Extra channel:** {f'<#{extra_channel_id}>' if extra_channel_id else 'not set'}\n"
            f"**Copy to command channel:** {'enabled' if settings.get('moderation_log_command_channel') else 'disabled'}\n"
            f"**DM to affected member:** {'enabled' if settings.get('moderation_dm_enabled', True) else 'disabled'}\n"
            f"**DM details:** {included}",
            ephemeral=True,
        )

    @lockdown.command(name="bypass-role", description="Allow or block a role from chatting during channel lockdowns")
    @app_commands.describe(role="Trusted staff role", enabled="Should members with this role bypass lockdowns?")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def lockdown_bypass_role(
        self, interaction: discord.Interaction, role: discord.Role, enabled: bool
    ) -> None:
        if role.is_default():
            await interaction.response.send_message("@everyone cannot be a lockdown bypass role.", ephemeral=True)
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        role_ids = set(settings.get("lockdown_bypass_role_ids", []))
        if enabled:
            role_ids.add(role.id)
        else:
            role_ids.discard(role.id)
        await self.bot.store.update_settings(interaction.guild_id, lockdown_bypass_role_ids=sorted(role_ids))
        await interaction.response.send_message(
            f"{role.mention} {'can' if enabled else 'can no longer'} chat during bot-managed channel lockdowns. "
            "This only affects lockdowns started after the setting is changed.",
            ephemeral=True,
        )

    @lockdown.command(name="show", description="Show roles allowed to chat during lockdowns")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def lockdown_show(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        roles = [
            role.mention
            for role_id in settings.get("lockdown_bypass_role_ids", [])
            if (role := interaction.guild.get_role(role_id)) is not None
        ]
        await interaction.response.send_message(
            "**Lockdown bypass roles:** " + (", ".join(roles) if roles else "none; all roles are blocked"),
            ephemeral=True,
        )

    @flagged_words.command(name="enabled", description="Enable or disable Discord's Commonly Flagged Words and custom filters")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_enabled(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, modules={"flagged_words": enabled})
        cog = self.bot.get_cog("AutoMod")
        try:
            if cog is not None:
                synced = await cog.sync_guild(interaction.guild)
                if enabled and not synced:
                    await interaction.response.send_message("Setting saved, but the bot needs the **Manage Server** permission to manage AutoMod rules.", ephemeral=True)
                    return
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(f"Setting saved, but Discord AutoMod could not be updated: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Commonly Flagged Words and custom filters {'enabled' if enabled else 'disabled'}. Discord blocks matching messages before they are sent.",
            ephemeral=True,
        )

    @flagged_words.command(name="add", description="Add a term or phrase to the custom AutoMod word list")
    @app_commands.describe(word="Term or phrase (max 60 characters; Discord wildcard * supported)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_add(self, interaction: discord.Interaction, word: app_commands.Range[str, 1, 60]) -> None:
        term = word.strip().casefold()
        if not term:
            await interaction.response.send_message("The term cannot be empty.", ephemeral=True)
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        terms = list(settings.get("automod_flagged_words", []))
        if term in {entry.casefold() for entry in terms}:
            await interaction.response.send_message("That term is already in the list.", ephemeral=True)
            return
        if len(terms) >= 1000:
            await interaction.response.send_message("The custom list has reached Discord's limit of 1,000 terms.", ephemeral=True)
            return
        terms.append(term)
        await self.bot.store.update_settings(interaction.guild_id, automod_flagged_words=terms)
        cog = self.bot.get_cog("AutoMod")
        try:
            if cog is not None:
                synced = await cog.sync_guild(interaction.guild)
                if settings["modules"].get("flagged_words") and not synced:
                    await interaction.response.send_message("Term saved, but the bot needs the **Manage Server** permission to manage AutoMod rules.", ephemeral=True)
                    return
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(f"Term saved, but the Discord rule could not be updated: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"Saved **{discord.utils.escape_markdown(term)}**. Enable the filter with `/config flagged-words enabled` if it is currently off.", ephemeral=True)

    @flagged_words.command(name="remove", description="Remove a term from the custom AutoMod word list")
    @app_commands.describe(word="Exact saved term")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_remove(self, interaction: discord.Interaction, word: app_commands.Range[str, 1, 60]) -> None:
        term = word.strip().casefold()
        settings = await self.bot.store.get_settings(interaction.guild_id)
        terms = list(settings.get("automod_flagged_words", []))
        remaining = [entry for entry in terms if entry.casefold() != term]
        if len(remaining) == len(terms):
            await interaction.response.send_message("That term was not found.", ephemeral=True)
            return
        await self.bot.store.update_settings(interaction.guild_id, automod_flagged_words=remaining)
        cog = self.bot.get_cog("AutoMod")
        try:
            if cog is not None:
                synced = await cog.sync_guild(interaction.guild)
                if settings["modules"].get("flagged_words") and not synced:
                    await interaction.response.send_message("Term removed, but the bot needs the **Manage Server** permission to manage AutoMod rules.", ephemeral=True)
                    return
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(f"Term removed, but the Discord rule could not be updated: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"Removed **{discord.utils.escape_markdown(term)}**.", ephemeral=True)

    @flagged_words.command(name="list", description="Show the filter status and custom terms")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def flagged_words_list(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        words = settings.get("automod_flagged_words", [])
        body = ", ".join(discord.utils.escape_markdown(word) for word in words) or "No custom terms configured."
        if len(body) > 1700:
            body = body[:1697] + "…"
        await interaction.response.send_message(
            f"**Word filter:** {'enabled' if settings['modules'].get('flagged_words') else 'disabled'}\n"
            "Discord's Commonly Flagged Words preset is also enabled while the word filter is on.\n"
            f"**Custom terms ({len(words)}):** {body}",
            ephemeral=True,
        )

    @escalation.command(name="enabled", description="Enable or disable automatic escalation for /mod warn")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_enabled(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_enabled=enabled)
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(
            f"Automatic escalation is {state}. It only applies to new `/mod warn` cases; existing bot cases are used as history.",
            ephemeral=True,
        )

    @escalation.command(name="window", description="Set the period in which moderation cases count toward escalation")
    @app_commands.describe(days="1 to 365 days")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_window(self, interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_window_days=days)
        await interaction.response.send_message(f"Escalation and case alert window: **{days} days**.", ephemeral=True)

    @escalation.command(name="level", description="Set an action for a specific number of documented violations")
    @app_commands.describe(
        threshold="Violation count at which this action applies (2 to 20)",
        action="timeout, kick, or ban",
        duration_minutes="For timeouts only: at least 30 minutes; defaults to 30 minutes",
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
        detail = f" for {level['duration_minutes']} minutes" if action.value == "timeout" else ""
        await interaction.response.send_message(f"Starting at violation **#{threshold}**, apply **{action.value}**{detail}.", ephemeral=True)

    @escalation.command(name="level-remove", description="Remove an automatic escalation level")
    @app_commands.describe(threshold="The saved violation count")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_level_remove(self, interaction: discord.Interaction, threshold: app_commands.Range[int, 2, 20]) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        levels = [level for level in settings.get("escalation_levels", []) if int(level.get("threshold", 0)) != threshold]
        if len(levels) == len(settings.get("escalation_levels", [])):
            await interaction.response.send_message("No escalation level is saved for that violation count.", ephemeral=True)
            return
        await self.bot.store.update_settings(interaction.guild_id, escalation_levels=levels)
        await interaction.response.send_message(f"Removed escalation level **#{threshold}**.", ephemeral=True)

    @escalation.command(name="alert-channel", description="Set or clear the private staff channel for repeat-case alerts")
    @app_commands.describe(channel="Text channel visible to staff only; leave empty to disable alerts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_alert_channel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_alert_channel_id=channel.id if channel else None)
        await interaction.response.send_message(f"Repeat-case alerts: {channel.mention if channel else 'disabled'}.", ephemeral=True)

    @escalation.command(name="alert-threshold", description="Choose the case count that triggers a staff alert")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_alert_threshold(self, interaction: discord.Interaction, count: app_commands.Range[int, 2, 20]) -> None:
        await self.bot.store.update_settings(interaction.guild_id, escalation_alert_threshold=count)
        await interaction.response.send_message(f"Staff alerts start at **{count} documented cases** within the escalation window.", ephemeral=True)

    @escalation.command(name="alert-role", description="Add or remove a role mention from staff alerts")
    @app_commands.describe(role="Staff role", enabled="Should this role be mentioned?")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_alert_role(self, interaction: discord.Interaction, role: discord.Role, enabled: bool) -> None:
        if role.is_default():
            await interaction.response.send_message("@everyone cannot be configured as a staff alert mention.", ephemeral=True)
            return
        settings = await self.bot.store.get_settings(interaction.guild_id)
        role_ids = set(settings.get("escalation_alert_role_ids", []))
        if enabled:
            role_ids.add(role.id)
        else:
            role_ids.discard(role.id)
        await self.bot.store.update_settings(interaction.guild_id, escalation_alert_role_ids=sorted(role_ids))
        await interaction.response.send_message(f"Role {role.mention} will {'be mentioned' if enabled else 'no longer be mentioned'} in staff alerts.", ephemeral=True)

    @escalation.command(name="mute-role", description="Set or clear the server role used for timed mutes")
    @app_commands.describe(role="Assignable mute role; leave empty to use Discord timeouts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_mute_role(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        if role and (role.is_default() or role.managed or not role.is_assignable()):
            await interaction.response.send_message(
                "This role cannot be assigned. Make sure it is not an integration role, is below the bot's highest role, and the bot has Manage Roles.",
                ephemeral=True,
            )
            return
        await self.bot.store.update_settings(interaction.guild_id, mute_role_id=role.id if role else None)
        if role:
            message = f"{role.mention} is now the mute role for `/mod timeout` and timeout escalations. Configure it to restrict the appropriate text and voice permissions."
        else:
            message = "Mute role cleared. `/mod timeout` and timeout escalations will use Discord timeouts again. Existing role mutes will expire using their saved role."
        await interaction.response.send_message(message, ephemeral=True)

    @escalation.command(name="show", description="Show escalation rules and staff alert settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def escalation_show(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        levels = settings.get("escalation_levels", [])
        level_text = "\n".join(
            f"At #{level['threshold']}: {level['action']}" + (f" ({level.get('duration_minutes', 30)} min)" if level['action'] == "timeout" else "")
            for level in levels
        ) or "No escalation levels configured"
        channel_id = settings.get("escalation_alert_channel_id")
        roles = settings.get("escalation_alert_role_ids", [])
        mute_role_id = settings.get("mute_role_id")
        await interaction.response.send_message(
            f"**Automatic escalation:** {'enabled' if settings.get('escalation_enabled') else 'disabled'}\n"
            f"**Window:** {settings.get('escalation_window_days', 30)} days\n"
            f"**Levels:**\n{level_text}\n"
            f"**Staff alerts:** {f'<#{channel_id}>' if channel_id else 'disabled'} from {settings.get('escalation_alert_threshold', 3)} cases\n"
            f"**Mentioned staff roles:** {', '.join(f'<@&{role_id}>' for role_id in roles) or 'none'}\n"
            f"**Mute role:** {f'<@&{mute_role_id}>' if mute_role_id else 'Discord timeout'}",
            ephemeral=True,
        )

    @config.command(name="welcome-channel", description="Set or clear the welcome channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.store.update_settings(interaction.guild_id, welcome_channel_id=channel.id if channel else None)
        await interaction.response.send_message(f"Welcome channel: {channel.mention if channel else 'disabled'}.", ephemeral=True)

    @config.command(name="welcome-message", description="Set the welcome message")
    @app_commands.describe(message="Placeholders: {mention}, {user}, {server}, {count}")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_message(self, interaction: discord.Interaction, message: str) -> None:
        if len(message) > 1800:
            await interaction.response.send_message("The message cannot exceed 1,800 characters.", ephemeral=True)
            return
        await self.bot.store.update_settings(interaction.guild_id, welcome_message=message)
        await interaction.response.send_message("Welcome message saved.", ephemeral=True)

    @config.command(name="show", description="Show the current bot settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def show(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        enabled = ", ".join(name.replace("_", "-") for name, active in settings["modules"].items() if active) or "none"
        disabled = ", ".join(name for name, active in settings["commands"].items() if not active) or "none"
        log = f"<#{settings['log_channel_id']}>" if settings["log_channel_id"] else "not set"
        welcome = f"<#{settings['welcome_channel_id']}>" if settings["welcome_channel_id"] else "not set"
        mute_role = f"<@&{settings['mute_role_id']}>" if settings.get("mute_role_id") else "Discord timeout"
        overrides = settings.get("log_channels", {})
        routes = ", ".join(f"{key}: <#{value}>" for key, value in overrides.items() if value) or "none (using the default channel)"
        rep_channel_id = settings.get("reputation_leaderboard_channel_id")
        rep_summary = (
            f"{'enabled' if settings['modules'].get('reputation', True) else 'disabled'}; "
            f"give/take caps {settings.get('reputation_max_give', 5)}/{settings.get('reputation_max_take', 5)}; "
            f"award roles {'enabled' if settings.get('reputation_awards_enabled', False) else 'disabled'}; "
            f"leaderboard {f'<#{rep_channel_id}>' if rep_channel_id else 'not posted'}"
        )
        extra_mod_channel_id = settings.get("moderation_extra_log_channel_id")
        mod_log_summary = (
            f"extra {f'<#{extra_mod_channel_id}>' if extra_mod_channel_id else 'none'}; "
            f"command-channel copy {'on' if settings.get('moderation_log_command_channel') else 'off'}; "
            f"member DMs {'on' if settings.get('moderation_dm_enabled', True) else 'off'}"
        )
        lockdown_roles = ", ".join(
            f"<@&{role_id}>" for role_id in settings.get("lockdown_bypass_role_ids", [])
            if interaction.guild.get_role(role_id) is not None
        ) or "none"
        await interaction.response.send_message(
            f"**Enabled modules:** {enabled}\n**Disabled commands:** {disabled}\n**Default log channel:** {log}\n"
            f"**Category log routes:** {routes}\n**Welcome channel:** {welcome}\n**Mute role:** {mute_role}\n"
            f"**Escalation:** {'enabled' if settings.get('escalation_enabled') else 'disabled'}\n"
            f"**Reputation:** {rep_summary}\n"
            f"**Moderation logs:** {mod_log_summary}\n"
            f"**Lockdown bypass roles:** {lockdown_roles}",
            ephemeral=True,
        )

    @reputation.command(name="max-give", description="Set the maximum reputation members can give per command")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reputation_max_give(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]) -> None:
        await self.bot.store.update_settings(interaction.guild_id, reputation_max_give=amount)
        await interaction.response.send_message(f"Members can give up to **{amount} reputation** per `/rep give` command.", ephemeral=True)

    @reputation.command(name="max-take", description="Set the maximum reputation members can take per command")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reputation_max_take(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]) -> None:
        await self.bot.store.update_settings(interaction.guild_id, reputation_max_take=amount)
        await interaction.response.send_message(f"Members can take up to **{amount} reputation** per `/rep take` command.", ephemeral=True)

    @reputation.command(name="auto-thanks", description="Enable or disable reputation for thank-you replies")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reputation_auto_thanks(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self.bot.store.update_settings(interaction.guild_id, reputation_auto_thanks=enabled)
        note = " Automatic thank-you detection requires Message Content Intent enabled in the Developer Portal and `MESSAGE_CONTENT_INTENT=true` in `.env`." if enabled else ""
        await interaction.response.send_message(f"Automatic thank-you reputation is {'enabled' if enabled else 'disabled'}.{note}", ephemeral=True)

    @reputation.command(name="roles", description="Enable or disable the live reputation award roles")
    @app_commands.describe(enabled="Give the current #1, #2, and #3 members their leaderboard roles")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reputation_roles(self, interaction: discord.Interaction, enabled: bool) -> None:
        cog = self.bot.get_cog("Reputation")
        if cog is None:
            await interaction.response.send_message("The reputation feature is unavailable right now.", ephemeral=True)
            return
        success, message = await cog.configure_award_roles(interaction.guild, enabled)
        if success:
            await cog.refresh_leaderboard(interaction.guild)
        await interaction.response.send_message(message, ephemeral=True)

    @reputation.command(name="leaderboard-channel", description="Set or clear the channel with the live reputation leaderboard")
    @app_commands.describe(channel="Text channel; leave empty to remove the live leaderboard")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reputation_leaderboard_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        cog = self.bot.get_cog("Reputation")
        if cog is None:
            await self.bot.store.update_settings(
                interaction.guild_id,
                reputation_leaderboard_channel_id=channel.id if channel else None,
                reputation_leaderboard_message_id=None,
            )
            await interaction.response.send_message("Leaderboard channel saved, but the reputation feature is unavailable right now.", ephemeral=True)
            return
        published = await cog.configure_leaderboard(interaction.guild, channel)
        if channel is None:
            message = "The live reputation leaderboard has been disabled."
        elif published:
            message = f"The live reputation leaderboard is now in {channel.mention} and will update when scores change."
        else:
            message = f"The leaderboard channel is saved as {channel.mention}, but I could not post there. Check my channel permissions."
        await interaction.response.send_message(message, ephemeral=True)

    @reputation.command(name="show", description="Show reputation module and leaderboard settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reputation_show(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        channel_id = settings.get("reputation_leaderboard_channel_id")
        first_role_id = settings.get("reputation_first_place_role_id")
        favorites_role_id = settings.get("reputation_favorites_role_id")
        await interaction.response.send_message(
            f"**Reputation:** {'enabled' if settings['modules'].get('reputation', True) else 'disabled'}\n"
            f"**Maximum give:** {settings.get('reputation_max_give', 5)} per command\n"
            f"**Maximum take:** {settings.get('reputation_max_take', 5)} per command\n"
            f"**Automatic thank-you awards:** {'enabled' if settings.get('reputation_auto_thanks', True) else 'disabled'}\n"
            f"**Live leaderboard:** {f'<#{channel_id}>' if channel_id else 'not configured'}\n"
            f"**Award roles:** {'enabled' if settings.get('reputation_awards_enabled', False) else 'disabled'}\n"
            f"**#1 role:** {f'<@&{first_role_id}>' if first_role_id else 'not created'}\n"
            f"**#2–#3 role:** {f'<@&{favorites_role_id}>' if favorites_role_id else 'not created'}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Configuration(bot))
