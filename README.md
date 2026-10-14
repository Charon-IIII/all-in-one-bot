# Community Bot

A modular Discord community bot built with Python, `discord.py`, and SQLite. Use `/help` for member commands and `/staff-help` for the full staff command list.

## Features

- Moderation cases with required reasons, configurable member DMs, and separately routed logs. Purge reasons are optional.
- Channel lockdowns, timed mutes, configurable warning escalation, and repeat-case staff alerts.
- Event logs, welcome messages, role management, AutoMod filters, and reputation with a live leaderboard.
- Optional DeepL translation: reply to a message with `.tr` or `.tr <language code>` to choose the source language.

## Requirements

- Python 3.11 or newer and a Discord application with a bot user.
- Base bot permissions: View Channels, Send Messages, Embed Links, and Read Message History.
- Enable **Server Members Intent** in the Discord Developer Portal. Enable **Message Content Intent** only for features that need message text, such as translation and text-based filters.
- Grant feature permissions as needed: Manage Server for Discord AutoMod; Manage Messages for purge; Manage Channels for lockdown; Moderate Members, Kick Members, and Ban Members for moderation; Manage Roles for role tools, mute roles, and reputation awards; Manage Webhooks for translation; View Audit Log for event attribution.

## Install and run

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `DISCORD_TOKEN` in `.env`, then start the bot:

```powershell
python -m community_bot
```

Keep `.env` private and never commit your bot token. SQLite data is stored at `data/community_bot.sqlite3` by default; set `DATABASE_PATH` to change it. Back up the database regularly.

## Discord setup

1. Create a Discord application and bot, enable the required intents, then invite it with the `bot` and `applications.commands` scopes.
2. Run `/config setup`, then `/config guide` in your server.
3. Set a log destination with `/config log-channel` and optionally route categories with `/config log-route`.
4. Enable only the modules you need with `/config module`. Use `/config show` to review the configuration.

## Common commands

- `/help` — member command guide; `/staff-help` — staff command reference.
- `/mod warn`, `/mod timeout`, `/mod kick`, `/mod ban` — moderation actions; provide a reason. `/mod purge` accepts an optional reason.
- `/mod lockdown` and `/mod unlock` — lock or restore a channel. Configure staff exceptions with `/config lockdown bypass-role` before locking.
- `/config moderation-logs` — configure extra moderation log destinations and member DMs.
- `/config escalation` — configure automatic escalation and staff alerts.
- `/config flagged-words` — enable Discord's Commonly Flagged Words filter and manage custom terms.
- `/rep give`, `/rep take`, `/rep score`, `/rep leaderboard` — member reputation commands.
- `.tr` or `.tr <language code>` — translate a replied-to message into English. Add `DEEPL_API_KEY` to `.env` and set `MESSAGE_CONTENT_INTENT=true` to use this feature.

See `/staff-help` for command permissions and the complete staff command list. AutoMod and text-based features also require their corresponding Discord permissions and intents.
