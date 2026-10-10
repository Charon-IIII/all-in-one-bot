from __future__ import annotations

import discord
from discord.ext import commands


class EventLogs(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def post(self, guild: discord.Guild, embed: discord.Embed, category: str = "messages") -> None:
        settings = await self.bot.store.get_settings(guild.id)
        if not settings["modules"].get("logging"):
            return
        channel_id = settings.get("log_channels", {}).get(category) or settings.get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        embed = discord.Embed(title="Nachricht gelöscht", color=discord.Color.red())
        embed.add_field(name="Autor", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
        embed.add_field(name="Kanal", value=message.channel.mention, inline=True)
        body = message.content or "Inhalt nicht verfügbar (Message Content Intent deaktiviert oder Nachricht nicht im Cache)."
        embed.add_field(name="Inhalt", value=body[:1000], inline=False)
        await self.post(message.guild, embed, "messages")

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages or messages[0].guild is None:
            return
        embed = discord.Embed(title="Nachrichten in Masse gelöscht", description=f"{len(messages)} Nachrichten in {messages[0].channel.mention}", color=discord.Color.orange())
        await self.post(messages[0].guild, embed, "messages")

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        embed = discord.Embed(title="Nachricht bearbeitet", color=discord.Color.gold(), url=after.jump_url)
        embed.add_field(name="Autor / Kanal", value=f"{before.author.mention} · {before.channel.mention}", inline=False)
        embed.add_field(name="Vorher", value=(before.content or "(leer)")[:900], inline=False)
        embed.add_field(name="Nachher", value=(after.content or "(leer)")[:900], inline=False)
        await self.post(before.guild, embed, "messages")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self.post(member.guild, discord.Embed(title="Mitglied beigetreten", description=f"{member.mention} · `{member.id}`", color=discord.Color.green()), "members")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.post(member.guild, discord.Embed(title="Mitglied verlassen", description=f"{member} · `{member.id}`", color=discord.Color.dark_grey()), "members")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        changes = []
        if before.nick != after.nick:
            changes.append(f"**Nickname:** {before.nick or before.name} → {after.nick or after.name}")
        old_roles = {role.id: role for role in before.roles if role != before.guild.default_role}
        new_roles = {role.id: role for role in after.roles if role != after.guild.default_role}
        added = [role.mention for rid, role in new_roles.items() if rid not in old_roles]
        removed = [role.mention for rid, role in old_roles.items() if rid not in new_roles]
        if added:
            changes.append("**Rollen hinzugefügt:** " + ", ".join(added))
        if removed:
            changes.append("**Rollen entfernt:** " + ", ".join(removed))
        if changes:
            await self.post(after.guild, discord.Embed(title=f"Mitglied geändert: {after}", description="\n".join(changes), color=discord.Color.blurple()), "members")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self.post(channel.guild, discord.Embed(title="Kanal erstellt", description=f"{channel.mention} · `{channel.id}`", color=discord.Color.green()), "channels")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.post(channel.guild, discord.Embed(title="Kanal gelöscht", description=f"#{channel.name} · `{channel.id}`", color=discord.Color.red()), "channels")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        before_category = getattr(before, "category", None)
        after_category = getattr(after, "category", None)
        if getattr(before_category, "id", None) != getattr(after_category, "id", None):
            changes.append(f"**Kategorie:** {before_category.name if before_category else 'Keine'} → {after_category.name if after_category else 'Keine'}")
        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                changes.append(f"**Thema vorher:** {(before.topic or '(leer)')[:300]}\n**Thema nachher:** {(after.topic or '(leer)')[:300]}")
        if changes:
            await self.post(after.guild, discord.Embed(title=f"Kanal geändert: #{after.name}", description="\n".join(changes), color=discord.Color.gold()), "channels")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        await self.post(role.guild, discord.Embed(title="Rolle erstellt", description=f"{role.mention} · `{role.id}`", color=discord.Color.green()), "roles")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self.post(role.guild, discord.Embed(title="Rolle gelöscht", description=f"{role.name} · `{role.id}`", color=discord.Color.red()), "roles")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.color != after.color:
            changes.append(f"**Farbe:** {before.color} → {after.color}")
        if before.hoist != after.hoist:
            changes.append(f"**Separat anzeigen:** {before.hoist} → {after.hoist}")
        if before.mentionable != after.mentionable:
            changes.append(f"**Erwähnbar:** {before.mentionable} → {after.mentionable}")
        if changes:
            await self.post(after.guild, discord.Embed(title=f"Rolle geändert: {after.name}", description="\n".join(changes), color=discord.Color.gold()), "roles")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if before.channel == after.channel:
            return
        if before.channel is None:
            description = f"{member.mention} ist {after.channel.mention} beigetreten."
        elif after.channel is None:
            description = f"{member.mention} hat {before.channel.mention} verlassen."
        else:
            description = f"{member.mention} wechselte von {before.channel.mention} zu {after.channel.mention}."
        await self.post(member.guild, discord.Embed(title="Sprachkanal geändert", description=description, color=discord.Color.blurple()), "voice")

    @commands.Cog.listener()
    async def on_guild_ban_add(self, guild: discord.Guild, user: discord.User) -> None:
        await self.post(guild, discord.Embed(title="Ban erkannt", description=f"{user} · `{user.id}`", color=discord.Color.red()), "moderation")

    @commands.Cog.listener()
    async def on_guild_ban_remove(self, guild: discord.Guild, user: discord.User) -> None:
        await self.post(guild, discord.Embed(title="Entbannung erkannt", description=f"{user} · `{user.id}`", color=discord.Color.green()), "moderation")

    @commands.Cog.listener()
    async def on_mod_case(self, guild, target, moderator, action: str, reason: str, case_id: int, dm_sent: bool) -> None:
        embed = discord.Embed(title=f"Moderationsfall #{case_id}: {action}", color=discord.Color.orange())
        embed.add_field(name="Mitglied", value=f"{target} (`{target.id}`)", inline=False)
        embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)
        embed.add_field(name="Grund", value=reason[:1000], inline=False)
        embed.add_field(name="DM-Benachrichtigung", value="Zugestellt" if dm_sent else "Nicht zugestellt", inline=False)
        await self.post(guild, embed, "moderation")

    @commands.Cog.listener()
    async def on_mod_action(self, guild, moderator, action: str, reason: str, details: str) -> None:
        embed = discord.Embed(title=f"Moderationsaktion: {action}", color=discord.Color.orange())
        embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)
        embed.add_field(name="Details", value=details[:1000], inline=False)
        embed.add_field(name="Grund", value=reason[:1000], inline=False)
        await self.post(guild, embed, "moderation")

    @commands.Cog.listener()
    async def on_automod_action(self, action: discord.AutoModAction) -> None:
        guild = action.guild
        member = action.member
        embed = discord.Embed(title="AutoMod: Nachricht blockiert", color=discord.Color.red())
        embed.add_field(name="Mitglied", value=f"{member} (`{action.user_id}`)" if member else f"User-ID: `{action.user_id}`", inline=False)
        if action.channel is not None:
            embed.add_field(name="Kanal", value=action.channel.mention, inline=True)
        embed.add_field(name="Treffer", value=(action.matched_keyword or "Discord Commonly Flagged Words Preset")[:300], inline=False)
        embed.add_field(name="Regel-ID", value=f"`{action.rule_id}`", inline=True)
        if action.content:
            embed.add_field(name="Nachricht", value=action.content[:900], inline=False)
        await self.post(guild, embed, "automod")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventLogs(bot))
