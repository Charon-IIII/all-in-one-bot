from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class RoleManagement(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    role = app_commands.Group(name="role", description="Give or remove a server role from a member")

    async def _change_role(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: discord.Role,
        reason: str,
        *,
        give: bool,
    ) -> None:
        guild = interaction.guild
        actor = interaction.user
        if guild is None or not isinstance(actor, discord.Member):
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        settings = await self.bot.store.get_settings(guild.id)
        if not settings["modules"].get("role_management", True):
            await interaction.response.send_message("Role management is disabled on this server.", ephemeral=True)
            return

        reason = reason.strip()
        if not reason:
            await interaction.response.send_message("A reason is required for role changes.", ephemeral=True)
            return
        if role.is_default() or role.managed:
            await interaction.response.send_message("That role cannot be assigned or removed manually.", ephemeral=True)
            return
        if not role.is_assignable():
            await interaction.response.send_message(
                "I cannot manage that role. Move my highest role above it and try again.", ephemeral=True
            )
            return
        if member.id == guild.owner_id and actor.id != guild.owner_id:
            await interaction.response.send_message("You cannot change the server owner's roles.", ephemeral=True)
            return
        if actor.id != guild.owner_id:
            if role >= actor.top_role:
                await interaction.response.send_message(
                    "You can only manage roles below your highest role.", ephemeral=True
                )
                return
            if member.top_role >= actor.top_role:
                await interaction.response.send_message(
                    "You can only manage roles for members below your highest role.", ephemeral=True
                )
                return

        has_role = role in member.roles
        if give and has_role:
            await interaction.response.send_message(f"{member.mention} already has {role.mention}.", ephemeral=True)
            return
        if not give and not has_role:
            await interaction.response.send_message(f"{member.mention} does not have {role.mention}.", ephemeral=True)
            return

        action = "Granted" if give else "Removed"
        audit_reason = f"{action} by {actor} ({actor.id}): {reason}"[:512]
        try:
            if give:
                await member.add_roles(role, reason=audit_reason)
            else:
                await member.remove_roles(role, reason=audit_reason)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Discord denied that role change. Check my Manage Roles permission and role hierarchy.", ephemeral=True
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message("Discord could not complete that role change. Try again later.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"{action} {role.mention} {'to' if give else 'from'} {member.mention}. Reason: {reason}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @role.command(name="give", description="Give an assignable server role to a member")
    @app_commands.describe(member="Member receiving the role", role="Role to give", reason="Why the role is being given")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def give(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: discord.Role,
        reason: app_commands.Range[str, 1, 400],
    ) -> None:
        await self._change_role(interaction, member, role, reason, give=True)

    @role.command(name="take", description="Remove an assignable server role from a member")
    @app_commands.describe(member="Member losing the role", role="Role to remove", reason="Why the role is being removed")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def take(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: discord.Role,
        reason: app_commands.Range[str, 1, 400],
    ) -> None:
        await self._change_role(interaction, member, role, reason, give=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleManagement(bot))
