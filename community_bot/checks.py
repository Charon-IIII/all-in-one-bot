from __future__ import annotations

from discord import app_commands


def module_enabled(name: str, command_key: str | None = None):
    async def predicate(interaction):
        if interaction.guild_id is None:
            return False
        settings = await interaction.client.store.get_settings(interaction.guild_id)
        if settings["modules"].get(name, False) and (command_key is None or settings["commands"].get(command_key, True)):
            return True
        raise app_commands.CheckFailure(f"Das Modul **{name}** ist auf diesem Server deaktiviert.")

    return app_commands.check(predicate)
