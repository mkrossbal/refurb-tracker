# RSS → Telegram tracker

Polls RSS/Atom feeds (e.g. [refurb-tracker.com](https://refurb-tracker.com/) alert feeds) and sends each new item to a Telegram chat. Python 3 standard library only, no dependencies.

## 1. Create the bot

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. Send any message to your new bot (or add it to a group and post there).
3. Find your chat ID:

   ```sh
   export TELEGRAM_BOT_TOKEN=123456:ABC...
   python3 rss_telegram.py --get-chat-id
   ```

4. Check it works:

   ```sh
   export TELEGRAM_CHAT_ID=<id from step 3>
   python3 rss_telegram.py --test
   ```

Instead of exporting variables each time, you can put them in a `.env` file next to the script (it's gitignored):

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=190747136
```

## 2. Add feeds

Put one feed URL per line in `feeds.txt`. On refurb-tracker.com, set up your filter and copy the "Matching alert RSS/Atom feed URL".

## 3. Run it

```sh
python3 rss_telegram.py              # check once
python3 rss_telegram.py --loop 600   # keep running, check every 10 minutes
python3 rss_telegram.py --dry-run    # print what would be sent, don't send or save state
```

Sent item IDs are kept in `state.json`, so each item is notified once. Items already in a feed the first time it is checked **are** sent (for a narrow filter that is usually what you want). Pass `--seed` to mark them as seen silently instead, which is useful for broad feeds.

### Always-on with GitHub Actions

`.github/workflows/check-feeds.yml` runs the check every 10 minutes for free on GitHub:

1. Push this repo to GitHub.
2. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (Settings → Secrets and variables → Actions).
3. Trigger it once from the Actions tab (Run workflow) to confirm it works.

GitHub can delay scheduled runs, and it pauses schedules on repos with no activity for 60 days.

### Locally with cron

```cron
*/10 * * * * cd /path/to/repo && TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... /usr/bin/python3 rss_telegram.py >> tracker.log 2>&1
```
