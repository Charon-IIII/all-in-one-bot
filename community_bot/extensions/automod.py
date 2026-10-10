from __future__ import annotations

import re
import time
import logging
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord.ext import commands


INVITE_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.IGNORECASE)
PRESET_RULE_NAME = "Community Bot - Commonly Flagged Words"
CUSTOM_RULE_NAME = "Community Bot - Custom Flagged Words"


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.recent: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.sync_guild(guild)
            except (discord.Forbidden, discord.HTTPException):
                logging.exception("Failed to sync AutoMod rules for guild %s", guild.id)

    async def sync_guild(self, guild: discord.Guild) -> bool:
        """Keep Discord's server-side filters aligned with this guild's settings."""
        settings = await self.bot.store.get_settings(guild.id)
        enabled = bool(settings["modules"].get("flagged_words"))
        terms = list(dict.fromkeys(term.strip().casefold() for term in settings.get("automod_flagged_words", []) if term.strip()))
        if not guild.me or not guild.me.guild_permissions.manage_guild:
            if enabled:
                logging.warning("Flagged words are enabled for guild %s, but the bot is missing Manage Server", guild.id)
            return False
        rules = {rule.name: rule for rule in await guild.fetch_automod_rules()}
        block_action = discord.AutoModRuleAction(
            type=discord.AutoModRuleActionType.block_message,
            custom_message="Your message contains a prohibited term.",
        )

        async def ensure_rule(name: str, trigger: discord.AutoModTrigger | None, should_enable: bool) -> None:
            existing = rules.get(name)
            if existing is None:
                if not should_enable or trigger is None:
                    return
                await guild.create_automod_rule(
                    name=name,
                    event_type=discord.AutoModRuleEventType.message_send,
                    trigger=trigger,
                    actions=[block_action],
                    enabled=True,
                    reason="Synced by Community Bot",
                )
                return
            if not should_enable:
                if existing.enabled:
                    await existing.edit(enabled=False, reason="Community Bot flagged-word filter disabled")
                return
            if trigger is not None:
                if existing.enabled and existing.trigger.to_dict() == trigger.to_dict() and [action.to_dict() for action in existing.actions] == [block_action.to_dict()]:
                    return
                await existing.edit(
                    trigger=trigger,
                    actions=[block_action],
                    enabled=True,
                    reason="Community Bot flagged-word filter synced",
                )
            elif existing.enabled:
                await existing.edit(enabled=False, reason="Community Bot word list is empty")

        preset_trigger = discord.AutoModTrigger(
            type=discord.AutoModRuleTriggerType.keyword_preset,
            presets=discord.AutoModPresets(profanity=True),
        )
        custom_trigger = discord.AutoModTrigger(
            type=discord.AutoModRuleTriggerType.keyword,
            keyword_filter=terms,
        ) if terms else None
        await ensure_rule(PRESET_RULE_NAME, preset_trigger, enabled)
        await ensure_rule(CUSTOM_RULE_NAME, custom_trigger, enabled and bool(terms))
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        settings = await self.bot.store.get_settings(message.guild.id)
        if not settings["modules"].get("automod"):
            return
        if message.author.guild_permissions.manage_messages:
            return

        reason = None
        content = message.content
        if settings.get("automod_invites", True) and INVITE_RE.search(content):
            reason = "Discord invite link"
        if content.strip() and settings.get("automod_repeats", True):
            key = (message.guild.id, message.author.id)
            now = time.monotonic()
            recent = self.recent[key]
            while recent and now - recent[0][0] > 12:
                recent.popleft()
            recent.append((now, content.casefold().strip()))
            if len(recent) >= 5 and len({entry[1] for entry in list(recent)[-5:]}) <= 2:
                reason = reason or "Repeated messages"
                recent.clear()

        if reason is None:
            return
        suppressed = getattr(self.bot, "suppressed_message_deletes", set())
        suppressed.add(message.id)
        try:
            await message.delete()
        except discord.HTTPException:
            suppressed.discard(message.id)
            return
        self.bot.dispatch("automod_block", message.guild, message.author, message.channel, reason, content)
        duration = max(60, min(int(settings.get("automod_timeout_seconds", 300)), 28 * 24 * 60 * 60))
        if message.author.top_role < message.guild.me.top_role and message.guild.me.guild_permissions.moderate_members:
            try:
                await message.author.timeout(timedelta(seconds=duration), reason=f"Automod: {reason}")
            except discord.HTTPException:
                pass
        try:
            await message.channel.send(
                f"{message.author.mention}, your message was removed for {reason}.",
                delete_after=8,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))
