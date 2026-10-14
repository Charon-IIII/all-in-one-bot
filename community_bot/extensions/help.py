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
            title="Staff Toolkit",
            description=(
                "Choose a section below to find the right command. Commands require the listed Discord permissions "
                "and their bot module must be enabled. Use `/config show` to review this server's setup."
            ),
            color=discord.Color.from_rgb(75, 105, 190),
        )
        embed.add_field(
            name="💬 Member tools · available to everyone",
            value=(
                "`/help` — show the member command guide.\n"
                "`/rep give <member> <amount>` · `/rep take <member> <amount>` — change reputation within the configured limits.\n"
                "`/rep score [member]` — view a score and rank; `/rep leaderboard` — view the standings.\n"
                "Reply `.tr` or `.tr <language code>` to a message to translate it into English when Translator is enabled."
            ),
            inline=False,
        )
        embed.add_field(
            name="🛡️ Moderation · requires Moderate Members",
            value=(
                "`/mod warn <member> <reason>` — record a warning.\n"
                "`/mod timeout <member> <minutes> <reason>` — mute a member.\n"
                "`/mod unmute <member> <reason>` — remove a mute.\n"
                "`/mod history <member>` — review saved cases and reasons."
            ),
            inline=False,
        )
        embed.add_field(
            name="🚪 Member actions · requires Kick Members or Ban Members",
            value=(
                "`/mod kick <member> <reason>` — remove a member from the server.\n"
                "`/mod ban <member> <reason>` · `/mod unban <user_id> <reason>` — manage bans."
            ),
            inline=False,
        )
        embed.add_field(
            name="🧹 Message cleanup · requires Manage Messages",
            value="`/mod purge <amount> [reason]` — delete recent messages; the reason is optional.",
            inline=False,
        )
        embed.add_field(
            name="🔒 Channel lockdown · requires Manage Channels",
            value=(
                "`/mod lockdown <channel> <reason>` — block @everyone from sending messages or creating threads; saves the previous channel permissions.\n"
                "`/mod unlock <channel> <reason>` — restore the saved @everyone send/thread permissions.\n"
                "`/mod lockdown-status [channel]` — review active bot-managed lockdowns."
            ),
            inline=False,
        )
        embed.add_field(
            name="🎭 Role management · requires Manage Roles",
            value=(
                "`/role give <member> <role> <reason>` — grant an assignable role.\n"
                "`/role take <member> <role> <reason>` — remove an assignable role.\n"
                "Use `/config module role-management` to toggle this feature. Changes are recorded in the `roles` log category; member and role hierarchy limits apply."
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Core setup · requires Manage Server",
            value=(
                "`/config setup` · `/config guide` · `/config show` — initialize and review the server setup.\n"
                "`/config module <name> <enabled>` — toggle a whole feature.\n"
                "`/config command <name> <enabled>` — toggle an individual moderation command."
            ),
            inline=False,
        )
        embed.add_field(
            name="📋 Logging · requires Manage Server",
            value=(
                "`/config log-channel <channel>` — set the default destination.\n"
                "`/config log-route <category> [channel]` — route a category separately or reset it to default.\n"
                "`/config moderation-logs command-channel` and `additional-channel` — copy moderation entries to the command channel or another fixed channel.\n"
                "`/config moderation-logs dm` and `dm-field` — control case DMs to affected members and choose whether action, moderator, reason, and case number are included."
            ),
            inline=False,
        )
        embed.add_field(
            name="🤖 AutoMod · requires Manage Server",
            value=(
                "`/config flagged-words enabled` — toggle Discord's commonly flagged words preset.\n"
                "`/config flagged-words add|remove|list` — manage custom blocked terms.\n"
                "Invite and repeat filters are toggled with `/config module` and need Message Content Intent."
            ),
            inline=False,
        )
        embed.add_field(
            name="📈 Escalation · requires Manage Server",
            value=(
                "`/config escalation show|enabled|window` — review and toggle escalation.\n"
                "`/config escalation level|level-remove` — set or remove a threshold and action.\n"
                "`/config escalation alert-channel|alert-threshold|alert-role` — configure staff alerts.\n"
                "`/config escalation mute-role` — select the server's mute role."
            ),
            inline=False,
        )
        embed.add_field(
            name="⭐ Reputation · requires Manage Server",
            value=(
                "`/config reputation show|max-give|max-take|auto-thanks` — tune member reputation.\n"
                "`/config reputation leaderboard-channel` — set or clear the live board.\n"
                "Award roles are created and assigned automatically by default: #1 **Most Loved**, #2–#3 **Community Favorite**.\n"
                "`/config reputation roles <enabled>` — turn automatic awards off or back on; needs Manage Roles."
            ),
            inline=False,
        )
        embed.add_field(
            name="👋 Welcome · requires Manage Server",
            value=(
                "`/config welcome-channel <channel>` — select the welcome destination.\n"
                "`/config welcome-message <message>` — customize the welcome text."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
