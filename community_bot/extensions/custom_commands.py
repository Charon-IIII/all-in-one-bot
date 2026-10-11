from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)
COMMAND_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")
MAX_CUSTOM_COMMANDS = 25
MAX_RESPONSE_LENGTH = 1800


class CustomCommands(commands.Cog):
    """Guild-specific slash commands managed by a server's bot managers."""

    custom_command_group = app_commands.Group(
        name="custom-command", description="Create and manage server-specific slash commands"
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._registered_names: dict[int, set[str]] = {}
        self._initialized = False

    async def _manager_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return False
        member = interaction.user
        if isinstance(member, discord.Member) and (
            member.id == interaction.guild.owner_id
            or member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
        ):
            return True
        settings = await self.bot.store.get_settings(interaction.guild_id)
        role_id = settings.get("custom_command_manager_role_id")
        if role_id and isinstance(member, discord.Member) and any(role.id == role_id for role in member.roles):
            return True
        if role_id:
            message = f"You need the configured bot manager role (<@&{role_id}>) to manage custom commands."
        else:
            message = "A server administrator must first set `/config custom-commands manager-role`."
        await interaction.response.send_message(message, ephemeral=True)
        return False

    @staticmethod
    def _validate_name(name: str) -> str | None:
        if not COMMAND_NAME.fullmatch(name):
            return "Use 1–32 lowercase letters, numbers, hyphens, or underscores for the slash command name."
        return None

    async def _has_name_conflict(self, guild: discord.Guild, name: str) -> bool:
        if self.bot.tree.get_command(name) is not None:
            return True
        return self.bot.tree.get_command(name, guild=guild) is not None

    def _make_command(self, guild_id: int, row) -> app_commands.Command:
        name = str(row["name"])
        description = str(row["description"])
        response_text = str(row["response"])
        ephemeral = bool(row["ephemeral"])

        async def callback(interaction: discord.Interaction) -> None:
            if interaction.guild is None or interaction.guild_id != guild_id:
                await interaction.response.send_message("This command is only available in its configured server.", ephemeral=True)
                return
            settings = await self.bot.store.get_settings(guild_id)
            if not settings["modules"].get("custom_commands", True):
                await interaction.response.send_message("Custom commands are currently disabled on this server.", ephemeral=True)
                return
            saved_command = await self.bot.store.get_custom_command(guild_id, name)
            if saved_command is None or not saved_command["enabled"]:
                await interaction.response.send_message("This custom command is currently disabled.", ephemeral=True)
                return
            substitutions = {
                "{user}": interaction.user.mention,
                "{username}": discord.utils.escape_markdown(interaction.user.display_name),
                "{server}": discord.utils.escape_markdown(interaction.guild.name),
                "{channel}": interaction.channel.mention if interaction.channel else "this channel",
            }
            content = response_text
            for placeholder, value in substitutions.items():
                content = content.replace(placeholder, value)
            if len(content) > 2000:
                await interaction.response.send_message(
                    "This command's expanded response is too long. Please tell a bot manager to shorten its template.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                content,
                ephemeral=ephemeral,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        return app_commands.Command(name=name, description=description, callback=callback)

    async def _refresh_guild(self, guild: discord.Guild, *, sync: bool) -> tuple[bool, list[str]]:
        old_names = self._registered_names.pop(guild.id, set())
        for name in old_names:
            self.bot.tree.remove_command(name, guild=guild)

        rows = await self.bot.store.custom_commands(guild.id)
        registered: set[str] = set()
        conflicts: list[str] = []
        for row in rows:
            name = str(row["name"])
            if not row["enabled"]:
                continue
            if self.bot.tree.get_command(name) is not None or self.bot.tree.get_command(name, guild=guild) is not None:
                log.error("Cannot register custom command /%s in guild %s: name conflicts with another bot command", name, guild.id)
                conflicts.append(name)
                continue
            self.bot.tree.add_command(self._make_command(guild.id, row), guild=guild)
            registered.add(name)
        self._registered_names[guild.id] = registered

        if not sync:
            return True, conflicts
        await self.bot.store.queue_custom_command_sync(guild.id)
        try:
            await self.bot.tree.sync(guild=guild)
            await self.bot.store.clear_custom_command_sync(guild.id)
            return True, conflicts
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Could not sync custom commands for guild %s", guild.id)
            return False, conflicts

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        test_guild_id = getattr(getattr(self.bot, "settings", None), "sync_guild_id", None)
        pending_syncs = await self.bot.store.pending_custom_command_syncs()
        for guild in self.bot.guilds:
            rows = await self.bot.store.custom_commands(guild.id)
            should_sync = rows or guild.id in pending_syncs or (not self._initialized and guild.id == test_guild_id)
            if should_sync and (not self._initialized or guild.id in pending_syncs):
                await self._refresh_guild(guild, sync=True)
        self._initialized = True

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        rows = await self.bot.store.custom_commands(guild.id)
        pending_syncs = await self.bot.store.pending_custom_command_syncs()
        if rows or guild.id in pending_syncs:
            await self._refresh_guild(guild, sync=True)

    @custom_command_group.command(name="create", description="Create a server-specific custom slash command")
    @app_commands.guild_only()
    @app_commands.describe(
        name="Command name, such as rules or socials",
        description="Short description shown under the command (max 100 characters)",
        response="Reply text; placeholders: {user}, {username}, {server}, {channel}",
        ephemeral="Only show the reply to the person who ran it?",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        description: app_commands.Range[str, 1, 100],
        response: app_commands.Range[str, 1, MAX_RESPONSE_LENGTH],
        ephemeral: bool = False,
    ) -> None:
        if not await self._manager_check(interaction):
            return
        name = name.strip()
        description = description.strip()
        response = response.strip()
        issue = self._validate_name(name)
        if issue or not description or not response:
            await interaction.response.send_message(issue or "Description and response cannot be empty.", ephemeral=True)
            return
        if await self.bot.store.get_custom_command(interaction.guild_id, name):
            await interaction.response.send_message(f"`/{name}` already exists. Use `/custom-command edit` to change it.", ephemeral=True)
            return
        if await self._has_name_conflict(interaction.guild, name):
            await interaction.response.send_message(f"`/{name}` is already used by a built-in bot command.", ephemeral=True)
            return
        rows = await self.bot.store.custom_commands(interaction.guild_id)
        if len(rows) >= MAX_CUSTOM_COMMANDS:
            await interaction.response.send_message(
                f"This server has reached the limit of {MAX_CUSTOM_COMMANDS} custom commands. Delete one before adding another.",
                ephemeral=True,
            )
            return

        await self.bot.store.save_custom_command(interaction.guild_id, name, description, response, ephemeral, interaction.user.id)
        synced, conflicts = await self._refresh_guild(interaction.guild, sync=True)
        if not synced:
            await interaction.response.send_message(
                f"`/{name}` was saved, but Discord could not sync it yet. Check the bot's `applications.commands` access; it will retry on restart.",
                ephemeral=True,
            )
            return
        if name in conflicts:
            await self.bot.store.delete_custom_command(interaction.guild_id, name)
            await interaction.response.send_message(f"`/{name}` conflicts with another command and was not saved.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Created `/{name}`. It is now available in this server{'; its reply is private' if ephemeral else ''}.",
            ephemeral=True,
        )

    @custom_command_group.command(name="edit", description="Edit a server-specific custom slash command")
    @app_commands.guild_only()
    @app_commands.describe(
        name="Existing custom command name",
        new_name="Optional new command name",
        description="Optional new short description",
        response="Optional new reply text; placeholders: {user}, {username}, {server}, {channel}",
        ephemeral="Optional visibility setting for the reply",
    )
    async def edit(
        self,
        interaction: discord.Interaction,
        name: str,
        new_name: str | None = None,
        description: app_commands.Range[str, 1, 100] | None = None,
        response: app_commands.Range[str, 1, MAX_RESPONSE_LENGTH] | None = None,
        ephemeral: bool | None = None,
    ) -> None:
        if not await self._manager_check(interaction):
            return
        name = name.strip()
        row = await self.bot.store.get_custom_command(interaction.guild_id, name)
        if row is None:
            await interaction.response.send_message(f"I couldn't find a custom command named `/{name}`.", ephemeral=True)
            return
        final_name = (new_name or name).strip()
        issue = self._validate_name(final_name)
        if issue:
            await interaction.response.send_message(issue, ephemeral=True)
            return
        if final_name != name:
            if await self.bot.store.get_custom_command(interaction.guild_id, final_name):
                await interaction.response.send_message(f"`/{final_name}` already exists.", ephemeral=True)
                return
            if await self._has_name_conflict(interaction.guild, final_name):
                await interaction.response.send_message(f"`/{final_name}` is already used by a built-in bot command.", ephemeral=True)
                return
        final_description = (description.strip() if description is not None else str(row["description"]))
        final_response = (response.strip() if response is not None else str(row["response"]))
        if not final_description or not final_response:
            await interaction.response.send_message("Description and response cannot be empty.", ephemeral=True)
            return
        final_ephemeral = bool(row["ephemeral"]) if ephemeral is None else ephemeral
        await self.bot.store.rename_custom_command(
            interaction.guild_id, name, final_name, final_description, final_response, final_ephemeral
        )
        synced, _ = await self._refresh_guild(interaction.guild, sync=True)
        if not synced:
            await interaction.response.send_message(
                f"Changes to `/{final_name}` were saved, but Discord could not sync them yet. They will retry on restart.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"Updated `/{final_name}`.", ephemeral=True)

    @custom_command_group.command(name="delete", description="Delete a server-specific custom slash command")
    @app_commands.guild_only()
    async def delete(self, interaction: discord.Interaction, name: str) -> None:
        if not await self._manager_check(interaction):
            return
        name = name.strip()
        deleted = await self.bot.store.delete_custom_command(interaction.guild_id, name)
        if not deleted:
            await interaction.response.send_message(f"I couldn't find a custom command named `/{name}`.", ephemeral=True)
            return
        synced, _ = await self._refresh_guild(interaction.guild, sync=True)
        if not synced:
            await interaction.response.send_message(
                f"`/{name}` was deleted from storage, but Discord could not update its command list yet. It will retry on restart.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"Deleted `/{name}` from this server.", ephemeral=True)

    @custom_command_group.command(name="toggle", description="Enable or disable a custom slash command")
    @app_commands.guild_only()
    @app_commands.describe(name="Custom command to change", enabled="Should members be able to run it?")
    async def toggle(self, interaction: discord.Interaction, name: str, enabled: bool) -> None:
        if not await self._manager_check(interaction):
            return
        name = name.strip()
        row = await self.bot.store.get_custom_command(interaction.guild_id, name)
        if row is None:
            await interaction.response.send_message(f"I couldn't find a custom command named `/{name}`.", ephemeral=True)
            return
        if bool(row["enabled"]) == enabled:
            await interaction.response.send_message(f"`/{name}` is already {'enabled' if enabled else 'disabled'}.", ephemeral=True)
            return
        await self.bot.store.set_custom_command_enabled(interaction.guild_id, name, enabled)
        synced, _ = await self._refresh_guild(interaction.guild, sync=True)
        if not synced:
            await interaction.response.send_message(
                f"`/{name}` was {'enabled' if enabled else 'disabled'} in storage, but Discord could not sync it yet. It will retry on restart.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"`/{name}` is now {'enabled' if enabled else 'disabled'}.", ephemeral=True)

    @custom_command_group.command(name="list", description="List this server's custom slash commands")
    @app_commands.guild_only()
    async def list_commands(self, interaction: discord.Interaction) -> None:
        if not await self._manager_check(interaction):
            return
        rows = await self.bot.store.custom_commands(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("No custom commands are configured yet. Create one with `/custom-command create`.", ephemeral=True)
            return
        embed = discord.Embed(title="Custom commands", color=discord.Color.blurple())
        for row in rows[:20]:
            description = discord.utils.escape_markdown(str(row["description"]))[:80]
            response_preview = discord.utils.escape_markdown(str(row["response"]).replace("\n", " "))
            if len(response_preview) > 100:
                response_preview = response_preview[:97] + "…"
            embed.add_field(
                name=f"/{row['name']} · {'enabled' if row['enabled'] else 'disabled'} · {'private' if row['ephemeral'] else 'public'}",
                value=f"{description}\n> {response_preview}",
                inline=False,
            )
        settings = await self.bot.store.get_settings(interaction.guild_id)
        manager_role_id = settings.get("custom_command_manager_role_id")
        embed.set_footer(
            text=f"Showing {min(len(rows), 20)}/{len(rows)} · {len(rows)}/{MAX_CUSTOM_COMMANDS} slots · manager role: {f'<@&{manager_role_id}>' if manager_role_id else 'admins only'}"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @custom_command_group.command(name="variables", description="Explain the placeholders available in custom command replies")
    @app_commands.guild_only()
    async def variables(self, interaction: discord.Interaction) -> None:
        if not await self._manager_check(interaction):
            return
        await interaction.response.send_message(
            "Custom command response placeholders:\n"
            "• `{user}` — mention the member who ran the command (the message will not ping them)\n"
            "• `{username}` — their display name\n"
            "• `{server}` — this server's name\n"
            "• `{channel}` — the channel where it was used\n\n"
            "Example: `Welcome {user} to {server}! Read #rules first.`\n"
            "Create commands with `/custom-command create`; members run them as normal slash commands. You can make replies public or private.",
            ephemeral=True,
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CustomCommands(bot))
