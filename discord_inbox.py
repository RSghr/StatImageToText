"""
discord_inbox.py - pick up deployments posted in your private Discord "stats inbox" channel.

The register bot (Phoenix) posts one message per deployment into a channel of your private server (through a
webhook): the deployment details (a small deployment.json file, or "Key: value" lines) and, when the optional
stat modal was filled, the stat screenshots. Your own bot only READS that channel:

    python discord_inbox.py          # read the new messages, download the screenshots
    python discord_inbox.py --check  # test the bot token / channel without downloading anything

Nothing has to run all the time: Discord keeps the messages, so every Run report reads what arrived since the
last one. For each deployment:
  * screenshots  -> To_Process/discord/D<time>_<Host>_<A1>_<A2>_<A3>_<n>.png  (same naming as the Drive script)
  * details      -> history/discord_answers.csv (same columns as the Google Form, read next to it)
A later message with the same register ID replaces the earlier one (edit); status "denied" removes it.

Setup (browser panel -> Settings -> Discord inbox): the bot token (kept in .discord_token, never shared) and the
channel ID. The bot needs "Message Content Intent" (Developer Portal -> Bot) and, in that channel, View Channel +
Read Message History. Only the standard library is used.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://discord.com/api/v10"
TOKEN_FILE = HERE / ".discord_token"
SETTINGS = HERE / "settings.json"
STATE = HERE / "history" / "discord_inbox.json"
ANSWERS = HERE / "history" / "discord_answers.csv"
DEST = HERE / "To_Process" / "discord"
LOCAL_TZ = "Europe/Paris"
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_BYTES = 25 * 1024 * 1024
CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}
# same headers as the Google Form, so hd2stats reads both the same way
FIELDS = ["Timestamp", "Host Callsign", "Attendee 1 Callsign", "Attendee 2 Callsign", "Attendee 3 Callsign",
          "Operation starting date", "Operation Name", "Planet", "Enemy", "Difficulty", "Operation Success",
          "Were any of your missions affected", "Raid", "Register ID", "Source"]
KEYS = {  # accepted spellings in deployment.json / "Key: value" lines -> field
    "register_id": "id", "register": "id", "id": "id", "registerid": "id", "deploymentid": "id",
    "status": "status", "state": "status",
    "host": "host", "hostcallsign": "host",
    "members": "members", "players": "members", "squad": "members", "attendees": "members",
    "operation": "operation", "operationname": "operation", "name": "operation",
    "start": "start", "time": "start", "date": "start", "operationstart": "start", "starttime": "start",
    "planet": "planet",
    "enemy": "enemy", "front": "enemy", "faction": "enemy",
    "difficulty": "difficulty", "diff": "difficulty",
    "success": "success", "operationsuccess": "success", "completed": "success",
    "crashed": "crashed", "crash": "crashed", "crashes": "crashed", "affected": "crashed", "missionsaffected": "crashed",
    "raid": "raid",
}


class InboxError(Exception):
    pass


# ---------------------------------------------------------------- settings
def settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def channel_id() -> str:
    return re.sub(r"\D", "", str(settings().get("discord_channel") or ""))


def configured() -> bool:
    return bool(token() and channel_id())


# ---------------------------------------------------------------- Discord REST (read only)
def api(path: str, tok: str | None = None):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bot {tok or token()}",
        "User-Agent": "DiscordBot (https://github.com/RSghr/StatImageToText, 1.0)"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:                       # rate limited: wait as told, then retry
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 1))
                except Exception:  # noqa: BLE001
                    wait = 1.0
                time.sleep(min(wait, 30) + 0.2)
                continue
            msg = {401: "the bot token is wrong (Developer Portal -> Bot -> Reset Token, then paste it again)",
                   403: "the bot can't see that channel (give it View Channel + Read Message History there)",
                   404: "channel not found (check the channel ID, and that the bot is in that server)"}
            raise InboxError(msg.get(e.code, f"Discord answered {e.code}")) from None
        except urllib.error.URLError as e:
            raise InboxError(f"Discord not reachable ({e.reason})") from None
    raise InboxError("Discord kept asking to slow down - try again in a minute")


def download(url: str) -> bytes:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in CDN_HOSTS:
        raise InboxError(f"unexpected file host {host}")
    req = urllib.request.Request(url, headers={"User-Agent": "DiscordBot (StatImageToText, 1.0)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise InboxError("file too large")
    return data


def new_messages(chan: str, after: str) -> list[dict]:
    """Every message after the given ID, oldest first."""
    out, cur = [], after or "0"
    while True:
        batch = api(f"/channels/{chan}/messages?limit=100&after={cur}")
        if not batch:
            break
        batch.sort(key=lambda m: int(m["id"]))
        out += batch
        cur = batch[-1]["id"]
        if len(batch) < 100:
            break
    return out


# ---------------------------------------------------------------- reading one message
def norm_key(k: str) -> str:
    return re.sub(r"[^a-z]", "", str(k).lower())


def parse_fields(pairs) -> dict:
    d = {}
    for k, v in pairs:
        f = KEYS.get(norm_key(k))
        if f and f not in d and v not in (None, ""):
            d[f] = v
    return d


def details(msg: dict, fetch=download) -> dict:
    """The deployment details of a message: deployment.json, a ```json block, embed fields or 'Key: value' lines."""
    for a in msg.get("attachments", []):
        if a.get("filename", "").lower().endswith(".json") and a.get("size", 0) < 200_000:
            try:
                return parse_fields(json.loads(fetch(a["url"]).decode("utf-8")).items())
            except Exception:  # noqa: BLE001
                pass
    content = msg.get("content") or ""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
    if m:
        try:
            return parse_fields(json.loads(m.group(1)).items())
        except ValueError:
            pass
    pairs = []
    for e in msg.get("embeds", []):
        pairs += [(f.get("name", ""), f.get("value", "")) for f in e.get("fields", [])]
    for line in content.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            pairs.append((k.strip(" *_-"), v.strip(" *_")))
    return parse_fields(pairs)


def images(msg: dict) -> list[dict]:
    out = []
    for a in msg.get("attachments", []):
        ext = Path(a.get("filename", "")).suffix.lower()
        if str(a.get("content_type", "")).startswith("image/") or ext in IMG_EXT:
            out.append(a)
    return out


def members_of(d: dict) -> list[str]:
    m = d.get("members", [])
    if isinstance(m, str):
        m = [x for x in re.split(r"[,;\n]+", m)]
    names = [re.sub(r"^\s*[-*\d.)]+\s*", "", str(x)).strip() for x in m]
    names = [n for n in names if n]
    host = str(d.get("host") or "").strip()
    if host and (not names or names[0].lower() != host.lower()):
        names = [host] + [n for n in names if n.lower() != host.lower()]
    return names[:4]


def start_text(v) -> str:
    """Discord timestamp text for the 'Operation starting date' column (hd2stats reads <t:unix:F>)."""
    s = str(v or "").strip()
    if re.fullmatch(r"\d{9,11}(\.\d+)?", s):
        return f"<t:{int(float(s))}:F>"
    m = re.search(r"<t:(\d{9,11})", s)
    return f"<t:{m.group(1)}:F>" if m else s


def local_time(iso: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo(LOCAL_TZ)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return t.replace(tzinfo=None)


def safe(name: str) -> str:
    q = re.findall(r'["“”]([^"“”]{2,})["“”]', name)
    name = q[0] if q else name
    return re.sub(r"[^A-Za-z0-9-]", "", name)[:24] or "X"


def yes_no(v) -> str:
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return str(v or "").strip()


# ---------------------------------------------------------------- the sync
def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"last_id": "0", "records": {}}


def save_state(st: dict):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")


def write_answers(records: dict):
    ANSWERS.parent.mkdir(exist_ok=True)
    rows = sorted(records.values(), key=lambda r: r["Timestamp"])
    with open(ANSWERS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def remove_files(rec: dict):
    for name in rec.get("files", []):
        try:
            (DEST / name).unlink()
        except OSError:
            pass


def sync(say=print, fetch_messages=None, fetch=download) -> dict:
    """Read the new messages, update the answers file and the screenshots. Returns counts."""
    chan = channel_id()
    if not configured():
        return {"skipped": True}
    st = load_state()
    msgs = (fetch_messages or new_messages)(chan, st.get("last_id", "0"))
    added = updated = removed = shots = 0
    problems = []
    DEST.mkdir(parents=True, exist_ok=True)
    for msg in msgs:
        st["last_id"] = msg["id"]
        d = details(msg, fetch)
        names = members_of(d)
        key = str(d.get("id") or f"msg{msg['id']}")
        old = st["records"].get(key)
        if str(d.get("status", "")).strip().lower() in ("denied", "rejected", "deleted", "cancelled", "canceled"):
            if old:
                remove_files(old)
                del st["records"][key]
                removed += 1
            continue
        if not names and not images(msg):
            continue                                      # chat / unrelated message
        if not names:
            problems.append(f"message {msg['id']}: screenshots but no member list - skipped")
            continue
        posted = local_time(msg["timestamp"]) if not old else dt.datetime.fromisoformat(old["posted"])
        dep = "D" + posted.strftime("%Y%m%d%H%M%S")
        rec = {"posted": posted.isoformat(), "message": msg["id"],
               "Timestamp": posted.strftime("%Y-%m-%d %H:%M:%S"), "Register ID": key, "Source": "Discord",
               "Operation starting date": start_text(d.get("start")), "Operation Name": d.get("operation", ""),
               "Planet": d.get("planet", ""), "Enemy": d.get("enemy", ""), "Difficulty": d.get("difficulty", ""),
               "Operation Success": yes_no(d.get("success", "")),
               "Were any of your missions affected": yes_no(d.get("crashed", "")), "Raid": yes_no(d.get("raid", "")),
               "files": old.get("files", []) if old else []}
        for i, label in enumerate(["Host Callsign", "Attendee 1 Callsign", "Attendee 2 Callsign", "Attendee 3 Callsign"]):
            rec[label] = names[i] if i < len(names) else ""
        imgs = images(msg)
        if imgs:                                          # new screenshots replace the old ones of this deployment
            if old:
                remove_files(old)
            files = []
            stem = "_".join([dep] + [safe(n) for n in names])
            for n, a in enumerate(imgs, 1):
                ext = Path(a.get("filename", "")).suffix.lower()
                ext = ext if ext in IMG_EXT else ".png"
                name = f"{stem}_{n}{ext}"
                try:
                    (DEST / name).write_bytes(fetch(a["url"]))
                    files.append(name)
                    shots += 1
                except Exception as e:  # noqa: BLE001
                    problems.append(f"{key}: screenshot {n} not downloaded ({e})")
            rec["files"] = files
        st["records"][key] = rec
        if old:
            updated += 1
        else:
            added += 1
    write_answers(st["records"])
    save_state(st)
    res = dict(messages=len(msgs), added=added, updated=updated, removed=removed, screenshots=shots,
               deployments=len(st["records"]), problems=problems)
    say(f"Discord inbox: {len(msgs)} new message(s) - {added} deployment(s) added, {updated} updated, "
        f"{removed} removed, {shots} screenshot(s) downloaded ({len(st['records'])} from Discord in total)")
    for p in problems:
        say("  ! " + p)
    return res


def check(tok: str | None = None, chan: str | None = None) -> dict:
    """Connection test for the panel: bot name, channel name, can it read messages?"""
    tok, chan = tok or token(), re.sub(r"\D", "", chan or channel_id())
    if not tok:
        raise InboxError("no bot token saved yet")
    if not chan:
        raise InboxError("no channel ID saved yet")
    me = api("/users/@me", tok)
    ch = api(f"/channels/{chan}", tok)
    last = api(f"/channels/{chan}/messages?limit=5", tok)
    note = ""
    if last and all(not m.get("content") and not m.get("attachments") and not m.get("embeds") for m in last):
        note = ("the bot sees messages but not what's in them: switch on 'Message Content Intent' "
                "(Developer Portal -> your app -> Bot), then test again")
    return {"bot": me.get("username", "?"), "channel": "#" + str(ch.get("name", "?")),
            "recent": len(last), "warning": note}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if not configured():
        print("Discord inbox not set up (browser panel -> Settings -> Discord inbox) - skipped.")
        return 0
    try:
        if "--check" in argv:
            r = check()
            print(f"Bot {r['bot']} reads {r['channel']} ({r['recent']} recent message(s)). {r['warning']}")
        else:
            sync()
    except InboxError as e:
        print(f"Discord inbox: {e}")
        return 0                     # never stop the report because of Discord
    return 0


if __name__ == "__main__":
    sys.exit(main())
