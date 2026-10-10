from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


async def staff_member(interaction: discord.Interaction) -> bool:
    permissions = interaction.permissions
    return any(
        (
            permissions.administrator,
            permissions.manage_guild,
            permissions.moderate_members,
            permissions.kick_members,
            permissions.ban_members,
            permissions.manage_messages,
        )
    )


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="See the commands and features available to members")
    @app_commands.guild_only()
    async def help(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.store.get_settings(interaction.guild_id)
        embed = discord.Embed(
            title=f"{interaction.guild.name} Bot Help",
            description="Here are the bot features available to you on this server.",
            color=discord.Color.blurple(),
        )
        commands_text = [
            "`/help` — show this member command guide.",
        ]
        if settings["modules"].get("reputation", True):
            give_max = settings.get("reputation_max_give", 5)
            take_max = settings.get("reputation_max_take", 5)
            commands_text.extend(
                (
                    f"`/rep give <member> <amount>` — give up to **{give_max}** reputation per command.",
                    f"`/rep take <member> <amount>` — take up to **{take_max}** reputation per command; scores can go below zero.",
                    "`/rep score [member]` — check your score or another member's score.",
                    "`/rep leaderboard` — show the server's top reputation scores.",
                )
            )
        else:
            commands_text.append("Reputation commands are currently disabled on this server.")
        embed.add_field(name="Member commands", value="\n".join(commands_text), inline=False)

        if settings["modules"].get("translator"):
            embed.add_field(
                name="Translation",
                value=(
                    "Reply to a message with `.tr` to translate it into English with automatic language detection, "
                    "or use `.tr <language code>` to specify the source, for example `.tr PL` or `.tr DE`."
                ),
                inline=False,
            )
        embed.add_field(
            name="Staff commands",
            value="Staff can use `/staff-help` to see the full command list and required permissions.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="staff-help", description="Show the full bot command list for staff")
    @app_commands.guild_only()
    @app_commands.check(staff_member)
    async def staff_help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Staff Command Reference",
            description=(
                "Commands are available only when their module is enabled and you have the required Discord permissions. "
                "Use `/config show` to review this server's settings."
            ),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(
            name="Member commands",
            value=(
                "`/staff-help` — show this staff command reference.\n"
                "`/help` — member-facing command guide.\n"
                "`/rep give <member> <amount>` — award reputation (server-configured maximum).\n"
                "`/rep take <member> <amount>` — remove reputation (server-configured maximum).\n"
                "`/rep score [member]` — check reputation and rank.\n"
                "`/rep leaderboard` — view the server leaderboard.\n"
                "Reply with `.tr` or `.tr <language code>` to translate a message into English when Translator is enabled."
            ),
            inline=False,
        )
        embed.add_field(
            name="Moderation — requires Moderate Members",
            value=(
                "`/mod warn <member> <reason>` — record a warning.\n"
                "`/mod timeout <member> <minutes> <reason>` — mute a member.\n"
                "`/mod unmute <member> <reason>` — remove a mute.\n"
                "`/mod history <member>` — view saved moderation cases."
            ),
            inline=False,
        )
        embed.add_field(
            name="Member actions — requires Kick Members or Ban Members",
            value=(
                "`/mod kick <member> <reason>` — kick a member (Kick Members).\n"
                "`/mod ban <member> <reason>` and `/mod unban <user_id> <reason>` — manage bans (Ban Members)."
            ),
            inline=False,
        )
        embed.add_field(
            name="Message management — requires Manage Messages",
            value="`/mod purge <amount> [reason]` — delete recent messages; the reason is optional.",
            inline=False,
        )
        embed.add_field(
            name="Server configuration — requires Manage Server",
            value=(
                "`/config setup`, `/config guide`, `/config show` — setup and review settings.\n"
                "`/config module` and `/config command` — enable or disable modules and moderation commands.\n"
                "`/config log-channel`, `/config log-route` — configure log destinations.\n"
                "`/config flagged-words enabled|add|remove|list` — manage word filters.\n"
                "`/config escalation show|enabled|window|level|level-remove|alert-channel|alert-threshold|alert-role|mute-role` — configure moderation escalation.\n"
                "`/config reputation show|max-give|max-take|auto-thanks|leaderboard-channel` — configure reputation.\n"
                "`/config welcome-channel`, `/config welcome-message` — configure welcome messages."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
