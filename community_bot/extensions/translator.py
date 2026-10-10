from __future__ import annotations

import os
import logging
import time
import asyncio
from collections import defaultdict

import deepl
import discord
from discord.ext import commands


TARGET_LANGUAGE = "EN-US"
MAX_LENGTH = 2_000
COOLDOWN_SECONDS = 5
CACHE_TTL_SECONDS = 60 * 60
CACHE_MAX_ENTRIES = 2_000


class Translator(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api_key = os.getenv("DEEPL_API_KEY", "").strip()
        self.client = deepl.Translator(self.api_key) if self.api_key else None
        self.cooldowns: dict[tuple[int, int], float] = {}
        self.cache: dict[tuple[str, str], tuple[float, str, str | None]] = {}
        self.webhook_cache: dict[int, tuple[int, str]] = {}

    async def _translate(self, text: str, source_language: str | None) -> tuple[str, str | None]:
        if self.client is None:
            raise RuntimeError("DEEPL_API_KEY is not configured.")
        key = (source_language or "AUTO", text)
        cached = self.cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1], cached[2]
        result = await asyncio.to_thread(
            self.client.translate_text,
            text,
            source_lang=source_language,
            target_lang=TARGET_LANGUAGE,
        )
        value = (result.text, result.detected_source_lang or source_language)
        self.cache[key] = (now, value[0], value[1])
        if len(self.cache) > CACHE_MAX_ENTRIES:
            self.cache = {
                cached_key: cached_value
                for cached_key, cached_value in self.cache.items()
                if now - cached_value[0] < CACHE_TTL_SECONDS
            }
            while len(self.cache) > CACHE_MAX_ENTRIES:
                self.cache.pop(next(iter(self.cache)))
        return value

    async def _get_webhook(self, channel: discord.abc.GuildChannel) -> discord.Webhook:
        cached = self.webhook_cache.get(channel.id)
        if cached:
            try:
                return await self.bot.fetch_webhook(cached[0], token=cached[1])
            except (discord.NotFound, discord.Forbidden):
                self.webhook_cache.pop(channel.id, None)

        hooks = await channel.webhooks()
        webhook = next(
            (hook for hook in hooks if hook.user and self.bot.user and hook.user.id == self.bot.user.id and hook.token),
            None,
        )
        if webhook is None:
            webhook = await channel.create_webhook(name="Translator", reason="Community DeepL translations")
        if webhook.token is None:
            raise RuntimeError("Webhook token unavailable")
        self.webhook_cache[channel.id] = (webhook.id, webhook.token)
        return webhook

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        if not message.content.strip():
            return
        settings = await self.bot.store.get_settings(message.guild.id)
        if not settings["modules"].get("translator"):
            return
        parts = message.content.strip().split()
        if not parts or parts[0].casefold() != ".tr":
            return
        if len(parts) > 2:
            await message.reply("Use `.tr` for automatic language detection or `.tr <language code>` to specify the source language, such as `.tr PL` or `.tr DE`. Use a two-letter source code supported by DeepL.", mention_author=False)
            return
        source_language = parts[1].upper() if len(parts) == 2 else None
        if source_language and (len(source_language) != 2 or not source_language.isascii() or not source_language.isalpha()):
            await message.reply("Please use a two-letter source code supported by DeepL, such as `.tr PL` or `.tr DE`.", mention_author=False)
            return
        reference = message.reference
        if reference is None or reference.message_id is None:
            await message.reply("Reply to a message with `.tr` for automatic language detection or `.tr <language code>` to specify one, such as `.tr PL` or `.tr DE`.", mention_author=False)
            return

        cooldown_key = (message.guild.id, message.author.id)
        now = time.monotonic()
        remaining = COOLDOWN_SECONDS - (now - self.cooldowns.get(cooldown_key, 0))
        if remaining > 0:
            await message.reply(f"Please wait {int(remaining + 0.999)} seconds.", mention_author=False)
            return
        self.cooldowns[cooldown_key] = now

        try:
            target = await message.channel.fetch_message(reference.message_id)
            text = target.content.strip()
            if not text:
                await message.reply("That message contains no translatable text.", mention_author=False, delete_after=5)
                return
            if len(text) > MAX_LENGTH:
                await message.reply(f"That message exceeds the {MAX_LENGTH}-character limit.", mention_author=False)
                return
            if source_language and source_language.startswith("EN"):
                getattr(self.bot, "suppressed_message_deletes", set()).add(message.id)
                await message.delete()
                return
            translated, detected_language = await self._translate(text, source_language)
            if not source_language and (detected_language or "").upper().startswith("EN"):
                getattr(self.bot, "suppressed_message_deletes", set()).add(message.id)
                await message.delete()
                return
            target_channel = message.channel.parent if isinstance(message.channel, discord.Thread) else message.channel
            webhook = await self._get_webhook(target_channel)
            display_name = getattr(target.author, "global_name", None) or target.author.name
            if target.guild and isinstance(target.author, discord.Member):
                display_name = target.author.display_name
            getattr(self.bot, "suppressed_message_deletes", set()).add(message.id)
            await message.delete()
            suffix = f"\n-# {(detected_language or 'AUTO').upper()} → {TARGET_LANGUAGE} • {target.jump_url}"
            content = translated[: max(0, 2_000 - len(suffix))] + suffix
            await webhook.send(
                username=f"{display_name} • Translated"[:80],
                avatar_url=target.author.display_avatar.url,
                content=content,
                allowed_mentions=discord.AllowedMentions.none(),
                **({"thread": message.channel} if isinstance(message.channel, discord.Thread) else {}),
            )
        except (deepl.DeepLException, discord.HTTPException, RuntimeError) as exc:
            await message.reply("Translation failed. Check the language code, DeepL API key, and bot permissions.", mention_author=False)
            logging.getLogger(__name__).warning("Translator error in guild %s: %s", message.guild.id, exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Translator(bot))
