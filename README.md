# Community Bot

A modular Discord community bot built with Python, `discord.py`, and SQLite. It is designed as a self-hosted replacement foundation for common moderation, server logging, welcome, and anti-spam workflows.

## Included modules

- **Moderation:** warn, timeout, kick, ban, and unban slash commands require a non-empty reason; purge accepts an optional reason. Member cases persist the moderator, reason, timestamp, and DM delivery status. Affected users receive an action/moderator/reason/case-number DM when their privacy settings allow it.
- **Rule-based escalation:** optional case-count escalation on `/mod warn`, with a rolling time window and configurable warning/timeout/kick/ban thresholds. It starts disabled. Repeated-case staff alerts can be sent to a private channel and optionally mention configured staff roles.
- **Logging:** message edits/deletions, member joins/leaves, moderation cases, and AutoMod blocks to a configurable default channel. Messages, members, channels, roles, voice, moderation, and automod can each have their own channel.
- **Welcome:** optional welcome channel and customizable message.
- **Automod:** configurable invite-link and repeated-message filters with escalating timeouts. A separate native Discord AutoMod module blocks Discord's Commonly Flagged Words preset and your custom keyword list before messages are posted; blocks are logged.
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

Invite the bot with the `bot` and `applications.commands` scopes and the permissions above, including Manage Server for native AutoMod rules. Use `/config` in your server to enable modules and configure log/welcome channels. The first server administrator should run `/config setup`. Use `/config command` to toggle individual moderation commands such as `mod-purge`.

Set the default logging destination with `/config log-channel`, then optionally route a category with `/config log-route` (categories: `messages`, `members`, `channels`, `roles`, `voice`, `moderation`, `automod`). Passing no channel to a route resets it to the default channel. Enable `flagged-words` in `/config module`, or use `/config flagged-words enabled`; manage the custom list with `/config flagged-words add`, `remove`, and `list`. The native preset and custom list require Discord AutoMod rule permissions; Discord's preset requires Community features on the server. Discord displays its own block feedback to the member, and the bot logs the matched rule in the `automod` category.

Kulturistan's progressive sanctions can be configured with `/config escalation window`, `/config escalation level`, and `/config escalation enabled`. The starter thresholds are a 30-minute timeout on the second documented violation and a three-day timeout from the third; adjust them to match staff judgement, and add kick/ban levels only if desired. `/mod warn` applies the configured level to the next violation; direct `/mod timeout`, `/mod kick`, and `/mod ban` remain available for staff to decide severity, including immediate severe cases. Set `/config escalation alert-channel` and `/config escalation alert-threshold` for a staff review notice, then optionally add mention roles with `/config escalation alert-role`. Alerts ask staff to review and never apply an extra punishment by themselves. Counts use this bot's stored moderation cases within the configured window; cases from Dyno, Arcane, or YAGPDB are not imported.

## Deploy on Oracle Cloud Infrastructure Always Free

The bot is a small, always-on Python process and fits comfortably on an Always Free Ampere A1 VM for a single community server. A 1 OCPU / 6 GB Ubuntu ARM64 instance is more than enough; the actual free allocation and capacity availability depend on your tenancy and region. Oracle can reclaim idle Always Free compute instances, so retain backups of the SQLite database and configuration.

On Ubuntu ARM64, install Python 3.11+, create a dedicated service account, clone this project to `/opt/community-bot`, then create a virtual environment, install `requirements.txt`, and create `.env` with `DISCORD_TOKEN`. Protect the secret with `chmod 600 .env`. Copy `deploy/community-bot.service` to `/etc/systemd/system/community-bot.service`, then run `sudo systemctl daemon-reload`, `sudo systemctl enable --now community-bot`, and inspect startup with `sudo journalctl -u community-bot -f`. The service file assumes the project is at `/opt/community-bot` and runs as `communitybot`. Keep `.env`, SQLite files, and backups out of git.

## Data and operational notes

- SQLite data lives in `data/community_bot.sqlite3` by default; override with `DATABASE_PATH`.
- Back up the SQLite database before upgrades and periodically while running.
- Discord audit logs and channel logging are separate: this bot records events it receives and its own cases, but does not reproduce every Dyno/Arcane/YAGPDB dashboard or historical log feature.
- Do a staged rollout alongside the existing bots first. Verify permissions, log coverage, automod thresholds, and your existing role hierarchy before removing the current bots.
- The project intentionally has no bot token in source control. Rotate any token that was ever committed or shared.
