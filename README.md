# RSS -> Telegram notifier (GitHub Actions)

Checks the RSS feed every 10 minutes and sends Telegram notifications for new items.

## Setup

1. Create a Telegram bot with @BotFather and get its token.
2. Find your `chat_id` (or group id). Quick way:
   - Send a message to the bot, then call:
     `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
     Look for the `"chat": {"id": ...}` value in the JSON.
3. In your GitHub repository, go to **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your numeric chat id (or group id)

4. Commit the files in this repo to GitHub.

Workflow is scheduled every 10 minutes. You can also run manually from the Actions tab.

## Files
- `rss_bot.py` : Python one-shot script.
- `requirements.txt` : Python packages.
- `seen_items.json` : persistent list of notified item ids (updated by workflow).
- `.github/workflows/rss-notify.yml` : GitHub Actions workflow.

## Notes
- To change polling interval: edit the cron schedule in `.github/workflows/rss-notify.yml`.
- If feed structure changes, update `rss_bot.py`.
- If bot token changes, update repository secret `TELEGRAM_BOT_TOKEN`.
