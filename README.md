# Community Bot

A modular Discord community bot built with Python, `discord.py`, and SQLite. It is designed as a self-hosted replacement foundation for common moderation, server logging, welcome, and anti-spam workflows.

## Included modules

- **Moderation:** warn, timeout, kick, ban, and unban slash commands require a non-empty reason; purge accepts an optional reason. Member cases persist the moderator, reason, timestamp, and DM delivery status. Affected users receive an action/moderator/reason/case-number DM when their privacy settings allow it.
- **Logging:** message edits/deletions, member joins/leaves, and moderation cases to a configurable channel.
- **Welcome:** optional welcome channel and customizable message.
- **Automod:** configurable invite-link and repeated-message filters with escalating timeouts.
- **Configuration:** enable or disable modules and moderation commands, and set channels from `/config`.
- **Translator integration point:** ready for the existing DeepL bot to be brought in as an optional extension.

Features are configured per server. Slash commands are registered globally by default; set `SYNC_GUILD_ID` in `.env` while developing to update a test server immediately.

## Requirements

- Python 3.11 or newer
- A Discord application and bot token
- Discord bot permissions: View Channels, Send Messages, Embed Links, Read Message History, Manage Messages, Moderate Members, Kick Members, and Ban Members as needed by enabled features
- The **Server Members Intent** enabled in the Discord Developer Portal for welcome and member join/leave logging
- Optional: **Message Content Intent** in the Developer Portal and `MESSAGE_CONTENT_INTENT=true` in `.env` for invite/repeat automod and full message text in edit/delete logs. Without it, slash commands work and message event metadata is still logged.

## Run locally

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set DISCORD_TOKEN in .env
python -m community_bot
```

Invite the bot with the `bot` and `applications.commands` scopes and the permissions above. Use `/config` in your server to enable modules and configure log/welcome channels. The first server administrator should run `/config setup`. Use `/config command` to toggle individual moderation commands such as `mod-purge`.

## Deploy on Oracle Cloud Infrastructure Always Free

The bot is a small, always-on Python process and fits comfortably on an Always Free Ampere A1 VM for a single community server. A 1 OCPU / 6 GB Ubuntu ARM64 instance is more than enough; the actual free allocation and capacity availability depend on your tenancy and region. Oracle can reclaim idle Always Free compute instances, so retain backups of the SQLite database and configuration.

On Ubuntu ARM64, install Python 3.11+, create a dedicated service account, clone this project to `/opt/community-bot`, then create a virtual environment, install `requirements.txt`, and create `.env` with `DISCORD_TOKEN`. Protect the secret with `chmod 600 .env`. Copy `deploy/community-bot.service` to `/etc/systemd/system/community-bot.service`, then run `sudo systemctl daemon-reload`, `sudo systemctl enable --now community-bot`, and inspect startup with `sudo journalctl -u community-bot -f`. The service file assumes the project is at `/opt/community-bot` and runs as `communitybot`. Keep `.env`, SQLite files, and backups out of git.

## Data and operational notes

- SQLite data lives in `data/community_bot.sqlite3` by default; override with `DATABASE_PATH`.
- Back up the SQLite database before upgrades and periodically while running.
- Discord audit logs and channel logging are separate: this bot records events it receives and its own cases, but does not reproduce every Dyno/Arcane/YAGPDB dashboard or historical log feature.
- Do a staged rollout alongside the existing bots first. Verify permissions, log coverage, automod thresholds, and your existing role hierarchy before removing the current bots.
- The project intentionally has no bot token in source control. Rotate any token that was ever committed or shared.
