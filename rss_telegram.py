#!/usr/bin/env python3
"""Poll RSS/Atom feeds and send new entries to a Telegram chat.

Standard library only. Configure with environment variables or a .env file next to this script:
  TELEGRAM_BOT_TOKEN  token from @BotFather
  TELEGRAM_CHAT_ID    chat to notify (run with --get-chat-id to find it)

Feeds are listed in feeds.txt (one URL per line, # for comments) or passed
with --feed. Seen entry IDs are stored in state.json so each item is only
sent once.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "rss-telegram-tracker/1.0"
MAX_SEEN_PER_FEED = 500


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_feed(data):
    """Return a list of entries as dicts: id, title, link, summary, image."""
    root = ET.fromstring(data)
    entries = []
    if root.tag == ATOM + "feed":
        for e in root.findall(ATOM + "entry"):
            link = ""
            for l in e.findall(ATOM + "link"):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            content = e.findtext(ATOM + "content") or e.findtext(ATOM + "summary") or ""
            entries.append(_entry(e.findtext(ATOM + "id"), e.findtext(ATOM + "title"), link, content))
    else:  # RSS 2.0
        for item in root.iter("item"):
            link = item.findtext("link") or ""
            entries.append(_entry(item.findtext("guid") or link, item.findtext("title"),
                                  link, item.findtext("description") or ""))
    return entries


def _entry(entry_id, title, link, content):
    title = (title or "").strip()
    img = re.search(r'<img[^>]+src="([^"]+)"', content)
    return {
        "id": (entry_id or link or title).strip(),
        "title": title,
        "link": link.strip(),
        "summary": html_to_text(content),
        "image": html.unescape(img.group(1)) if img else None,
    }


def html_to_text(s):
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<s>(.*?)</s>", r"was \1", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", l).strip() for l in s.splitlines()]
    return "\n".join(l for l in lines if l and not l.startswith("Product page on"))


def telegram(token, method, params):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError("Telegram %s failed: %s" % (method, e.read().decode(errors="replace")))


def format_message(entry, feed_title):
    esc = html.escape
    parts = ["🔔 <b>%s</b>" % esc(entry["title"])]
    if entry["summary"]:
        summary = entry["summary"]
        # The title is usually repeated at the top of the content; drop it.
        summary = "\n".join(l for l in summary.splitlines() if l.lstrip("–- ") not in entry["title"])
        parts.append(esc(summary[:700]))
    if entry["link"]:
        parts.append('<a href="%s">Open listing</a>' % esc(entry["link"], quote=True))
    if feed_title:
        parts.append("<i>%s</i>" % esc(feed_title))
    return "\n\n".join(parts)


def notify(token, chat_id, entry, feed_title):
    text = format_message(entry, feed_title)
    if entry["image"] and len(text) <= 1024:
        try:
            return telegram(token, "sendPhoto", {"chat_id": chat_id, "photo": entry["image"],
                                                 "caption": text, "parse_mode": "HTML"})
        except RuntimeError as e:
            print("sendPhoto failed, falling back to text: %s" % e, file=sys.stderr)
    return telegram(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def load_feeds(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def check_feed(url, state, token, chat_id, seed=False, dry_run=False):
    data = http_get(url)
    root_title = ""
    try:
        root = ET.fromstring(data)
        root_title = (root.findtext(ATOM + "title") or root.findtext("channel/title") or "").strip()
    except ET.ParseError:
        pass
    entries = parse_feed(data)
    first_run = url not in state
    seen = state.get(url, [])
    seen_set = set(seen)
    new = [e for e in entries if e["id"] not in seen_set]

    for e in reversed(new):  # oldest first
        if seed and first_run:
            print("seed: %s" % e["title"])
        elif dry_run:
            print("would send: %s\n%s\n" % (e["title"], format_message(e, root_title)))
        else:
            notify(token, chat_id, e, root_title)
            print("sent: %s" % e["title"])
            time.sleep(1)  # stay well under Telegram rate limits
        seen.append(e["id"])

    state[url] = seen[-MAX_SEEN_PER_FEED:]
    print("%s %s: %d entries, %d new" % (time.strftime("%Y-%m-%d %H:%M"), url, len(entries), len(new)))
    return len(new)


def run_once(feeds, state_path, token, chat_id, seed, dry_run):
    state = load_state(state_path)
    errors = 0
    for url in feeds:
        try:
            check_feed(url, state, token, chat_id, seed=seed, dry_run=dry_run)
        except Exception as e:  # keep going with other feeds
            errors += 1
            print("error checking %s: %s" % (url, e), file=sys.stderr)
        finally:
            if not dry_run:
                save_state(state_path, state)
    return errors


def get_chat_id(token):
    updates = telegram(token, "getUpdates", {}).get("result", [])
    chats = {}
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if not chats:
        print("No chats found. Send any message to your bot in Telegram, then run this again.")
    for cid, name in chats.items():
        print("%s\t%s" % (cid, name))


def load_dotenv(path):
    """Set variables from a KEY=value file without overriding the environment."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(here, ".env"))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--feed", action="append", help="feed URL (repeatable); overrides feeds file")
    p.add_argument("--feeds-file", default=os.path.join(here, "feeds.txt"))
    p.add_argument("--state", default=os.environ.get("STATE_FILE", os.path.join(here, "state.json")))
    p.add_argument("--loop", type=int, metavar="SECONDS", help="keep running, checking every N seconds")
    p.add_argument("--seed", action="store_true",
                   help="on a feed's first check, mark existing entries as seen without notifying")
    p.add_argument("--dry-run", action="store_true", help="print messages instead of sending")
    p.add_argument("--test", action="store_true", help="send a test message and exit")
    p.add_argument("--get-chat-id", action="store_true", help="list chats that have messaged the bot")
    args = p.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not args.dry_run and not token:
        p.error("TELEGRAM_BOT_TOKEN is not set")

    if args.get_chat_id:
        return get_chat_id(token)
    if not args.dry_run and not chat_id:
        p.error("TELEGRAM_CHAT_ID is not set (use --get-chat-id to find it)")
    if args.test:
        telegram(token, "sendMessage", {"chat_id": chat_id, "text": "✅ RSS tracker is connected."})
        print("Test message sent.")
        return 0

    feeds = args.feed or load_feeds(args.feeds_file)
    if not feeds:
        p.error("no feeds: pass --feed URL or add URLs to %s" % args.feeds_file)

    if not args.loop:
        return 1 if run_once(feeds, args.state, token, chat_id, args.seed, args.dry_run) else 0
    while True:
        run_once(feeds, args.state, token, chat_id, args.seed, args.dry_run)
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())
