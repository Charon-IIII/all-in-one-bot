from __future__ import annotations

import time
import unicodedata

import discord
from discord.ext import commands


DEFAULT_REPLACEMENT = "🚫 Nice try!"
MAX_TERMS = 50
MAX_TERM_LENGTH = 80
MAX_NICKNAME_LENGTH = 32
NAME_TRANSLATION = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s",
    # Common Cyrillic and Greek lookalikes used to disguise Latin-script words.
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h",
    "α": "a", "ε": "e", "ι": "i", "ο": "o", "ρ": "p", "τ": "t", "κ": "k", "χ": "x",
})


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold().translate(NAME_TRANSLATION)
    return "".join(character for character in normalized if character.isalnum())


class NicknameFilter(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.recent_attempts: dict[tuple[int, int, str], float] = {}

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.bot:
            return

        nickname_changed = before.nick != after.nick
        global_name_changed = before.global_name != after.global_name
        username_changed = before.name != after.name
        if not (nickname_changed or global_name_changed or username_changed):
            return

        if nickname_changed:
            attempted_name = after.nick or after.global_name or after.name
            change_kind = "server nickname"
        elif global_name_changed and after.global_name:
            attempted_name = after.global_name
            change_kind = "global display name"
        else:
            attempted_name = after.name
            change_kind = "global username"
        await self._check_name(after.guild, after, attempted_name, change_kind, check_audit=True)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        """Catch global profile-name changes, which are not guaranteed to emit a member update."""
        if after.bot or (before.name == after.name and before.global_name == after.global_name):
            return

        if before.global_name != after.global_name and after.global_name:
            attempted_name = after.global_name
            change_kind = "global display name"
        else:
            attempted_name = after.name
            change_kind = "global username"

        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member is None:
                try:
                    member = await guild.fetch_member(after.id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue
            await self._check_name(guild, member, attempted_name, change_kind, check_audit=False)

    async def _check_name(
        self,
        guild: discord.Guild,
        member: discord.Member,
        attempted_name: str,
        change_kind: str,
        *,
        check_audit: bool,
    ) -> None:
        settings = await self.bot.store.get_settings(guild.id)
        if not settings["modules"].get("nickname_filter", False):
            return

        replacement = str(settings.get("nickname_filter_replacement") or DEFAULT_REPLACEMENT).strip()
        normalized_name = normalize_name(attempted_name)
        matched_terms = [
            term
            for term in settings.get("nickname_filter_terms", [])
            if normalize_name(term) and normalize_name(term) in normalized_name
        ]
        if not matched_terms:
            return

        now = time.monotonic()
        attempt_key = (guild.id, member.id, normalized_name)
        last_attempt = self.recent_attempts.get(attempt_key)
        if last_attempt is not None and now - last_attempt < 5:
            return
        self.recent_attempts[attempt_key] = now
        self.recent_attempts = {
            key: timestamp for key, timestamp in self.recent_attempts.items() if now - timestamp < 60
        }

        logger = self.bot.get_cog("EventLogs")
        attribution = (f"{member.mention} (`{member.id}`)", "Changed their own global profile name") if not check_audit else None
        if logger is not None and check_audit:
            attribution = await logger.audit_attribution(
                guild,
                (discord.AuditLogAction.member_update,),
                member.id,
            )

        bot_member = guild.me
        failure_reason = None
        enforcement_succeeded = False
        replacement_already_set = member.nick == replacement
        if bot_member is None or not bot_member.guild_permissions.manage_nicknames:
            failure_reason = "The bot needs the Manage Nicknames permission."
        elif member.id == guild.owner_id:
            failure_reason = "Discord does not allow the bot to change the server owner's nickname."
        elif member.top_role >= bot_member.top_role:
            failure_reason = "The member's highest role is at or above the bot's highest role."
        elif replacement_already_set:
            enforcement_succeeded = True
        else:
            try:
                await member.edit(
                    nick=replacement,
                    reason=f"Nickname filter matched configured term(s): {', '.join(matched_terms)[:400]}",
                )
                enforcement_succeeded = True
            except discord.Forbidden:
                failure_reason = "Discord denied the bot's nickname change request."
            except discord.HTTPException:
                failure_reason = "Discord returned an error while changing the nickname."
        safe_replacement = discord.utils.escape_markdown(replacement)
        if enforcement_succeeded and replacement_already_set:
            enforcement = f"The configured replacement nickname **{safe_replacement}** was already in place."
        elif enforcement_succeeded:
            enforcement = f"Set the server nickname to **{safe_replacement}**."
        else:
            enforcement = f"Could not change the nickname: {failure_reason or 'unknown failure'}"

        embed = discord.Embed(
            title=f"Flagged {change_kind} — {'enforced' if enforcement_succeeded else 'action failed'}",
            color=discord.Color.orange() if enforcement_succeeded else discord.Color.red(),
        )
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Attempted display name", value=discord.utils.escape_markdown(attempted_name)[:256], inline=False)
        embed.add_field(
            name="Matched configured terms",
            value=discord.utils.escape_markdown(", ".join(matched_terms))[:1000],
            inline=False,
        )
        embed.add_field(name="Action", value=enforcement, inline=False)
        embed.add_field(
            name="Moderator / Actor",
            value=attribution[0] if attribution else "No matching actor was available in the audit log.",
            inline=False,
        )
        if attribution:
            embed.add_field(name="Action context", value=attribution[1][:1000], inline=False)
        if logger is not None:
            await logger.post(guild, embed, "automod")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NicknameFilter(bot))
