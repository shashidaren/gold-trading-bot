#!/usr/bin/env python3
"""box_alert.py — a Telegram notice when the box-watch conditions line up.

Owner ask (2026-10-21): "maybe also include a telegram message once we get good
indicators."

WHAT IT SENDS
    The dashboard's 📦 Boxes & Timing verdict, at the moment it turns into a
    `candidate`: a FRESH close beyond a box edge with every condition green
    (feed, session, risk state, volatility, geometry) and no do-not-chase
    extension. The message carries the levels, the costed payoff, the retest
    state, the measured chop read — and the measured base rate, because the
    message is a *notice that the conditions line up*, not a forecast.

WHAT IT IS NOT
    * Not a signal and not an edge. Measured on this repo's own tape, 0 of 8 box
      breakout/fade geometries cleared the driftless reference
      (docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md), and neither the
      chop read nor the retest read separates outcomes
      (docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md §2/§3). The cooldown and
      the daily cap are SPAM CONTROL, not expectancy claims.
    * Not a trading path. It places no order, imports no engine module, and never
      writes to trades.csv / status.json / forward_test_log.csv. The only file it
      writes is its own dedupe state (default: $GOLD_DATA_DIR/box_alert_state.json).
    * The decision itself lives in `pressure.box_alert()`, so this tool, the
      dashboard preview and the tests cannot disagree about what "lines up" means.

USAGE
    python3 tools/box_alert.py --once --dry-run    # what would it say right now?
    python3 tools/box_alert.py --once              # decide, and send if it fires
    python3 tools/box_alert.py --loop              # decide every --interval seconds
    python3 tools/box_alert.py --test              # send a test message (checks the bot)
    python3 tools/box_alert.py --quiet             # one digest line (tools/autosync.sh)
    python3 tools/box_alert.py --json              # machine-readable decision

ENVIRONMENT
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   required to send (the engine's own pair)
    GOLD_BOX_ALERTS=0                       disable without uninstalling the unit
    GOLD_BOX_ALERT_COOLDOWN_MIN (90)        min between messages on the SAME box edge
    GOLD_BOX_ALERT_GLOBAL_COOLDOWN_MIN (30) min between ANY two messages
    GOLD_BOX_ALERT_DAILY_CAP (6)            max messages per UTC day
    GOLD_DATA_DIR / GOLD_LOG_FILE / GOLD_STATUS_FILE / GOLD_TRADES_FILE /
    GOLD_SKIP_FILE                          same overrides the dashboard honours
    GOLD_BOX_ALERT_STATE                    dedupe state file
    GOLD_ENV_FILE ($GOLD_DATA_DIR/.env)     where the settings above are read from
                                            when the process environment lacks them

    The settings above are read from the process environment first, then from the
    env file: /opt/gold/.env, the same file engine.py load_dotenv()s and the unit's
    EnvironmentFile= reads. So a cron job (tools/autosync.sh's digest) or a shell
    sees what the sidecar sees, with no `set -a; . ./.env` step. Only those keys are
    taken from the file (never the feed's API key), and a real environment variable
    always wins. The first version read the environment only, and autosync keeps
    the pair in private shell variables, so the 2026-10-21 18:00 UTC digest said
    "not configured" in the very message that pair had just delivered.

LIVENESS
    --loop stamps a heartbeat into its own state file every tick. The digest line
    uses it to separate "the Telegram pair is there" from "the notifier is running".
    Without it a box with no unit installed would read as a healthy notifier that
    has sent nothing yet. --dry-run never writes it.

Install: deploy/boxalert.service (docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md §5).
Read-only, stdlib only. It never exits non-zero for a decision it declined to send.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pressure as P  # noqa: E402

DATA_DIR = os.getenv("GOLD_DATA_DIR", "/opt/gold")
LOG_FILE = os.getenv("GOLD_LOG_FILE", os.path.join(DATA_DIR, "forward_test_log.csv"))
STATUS_FILE = os.getenv("GOLD_STATUS_FILE", os.path.join(DATA_DIR, "status.json"))
TRADES_FILE = os.getenv("GOLD_TRADES_FILE", os.path.join(DATA_DIR, "trades.csv"))
SKIP_FILE = os.getenv("GOLD_SKIP_FILE", os.path.join(DATA_DIR, "skipped_trades.csv"))
STATE_FILE = os.getenv("GOLD_BOX_ALERT_STATE", os.path.join(DATA_DIR, "box_alert_state.json"))
ENV_FILE = os.getenv("GOLD_ENV_FILE", os.path.join(DATA_DIR, ".env"))
# The only settings taken from ENV_FILE (when the process environment lacks them).
ENV_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GOLD_BOX_ALERTS",
            "GOLD_BOX_ALERT_COOLDOWN_MIN", "GOLD_BOX_ALERT_GLOBAL_COOLDOWN_MIN",
            "GOLD_BOX_ALERT_DAILY_CAP", "GOLD_BOX_ALERT_STATE")
DEFAULT_INTERVAL = 60          # seconds between decisions in --loop
HEARTBEAT_STALE_S = 300        # a --loop heartbeat older than max(this, 3 ticks) = not running
TAIL_ROWS = 9000               # what the dashboard's box panel reads
SEND_TIMEOUT = 10              # seconds; a dead API must not wedge the loop


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─────────────────────────────────────────────────────────── settings (env + .env file)
def read_env_file(path=ENV_FILE):
    """KEY=VALUE pairs from a systemd-EnvironmentFile / dotenv style file. Never raises.

    Blank lines and `#` / `;` comments are skipped, an `export ` prefix is tolerated and
    one pair of matching surrounding quotes is stripped. There is no variable expansion
    and no inline-comment stripping, which matches systemd. A later line wins, as it
    does for systemd and python-dotenv. A missing or unreadable file gives {}.
    """
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except (OSError, TypeError):
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def apply_env_file(path=ENV_FILE, environ=None, keys=ENV_KEYS):
    """Fill the box-alert settings the environment LACKS from the env file.

    The process environment always wins, as with engine.py's load_dotenv(). Only
    `keys` are copied: this tool has no business holding the feed's API key. Returns
    the NAMES filled, never the values.
    """
    environ = os.environ if environ is None else environ
    values = read_env_file(path)
    filled = []
    for key in keys:
        if values.get(key) and not environ.get(key):
            environ[key] = values[key]
            filled.append(key)
    return filled


def alert_limits(env=None):
    """The notification limits in force: env overrides over pressure.py's defaults.

    Spam control, not expectancy. GOLD_BOX_ALERT_GLOBAL_COOLDOWN_MIN was documented
    from the start but never read until 2026-10-21; it is read here with the other two.
    A malformed value falls back to the default instead of killing the notice.
    """
    env = os.environ if env is None else env

    def num(key, default, cast):
        try:
            value = cast(env.get(key) or default)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    return {"cooldown_minutes": num("GOLD_BOX_ALERT_COOLDOWN_MIN",
                                    P.BOX_ALERT_COOLDOWN_MINUTES, float),
            "global_cooldown_minutes": num("GOLD_BOX_ALERT_GLOBAL_COOLDOWN_MIN",
                                           P.BOX_ALERT_GLOBAL_COOLDOWN_MINUTES, float),
            "daily_cap": num("GOLD_BOX_ALERT_DAILY_CAP", P.BOX_ALERT_DAILY_CAP, int)}


# ──────────────────────────────────────────────────────────── the read (no writes)
def read_decision(log_file=LOG_FILE, status_file=STATUS_FILE, trades_file=TRADES_FILE,
                  spread=None, now=None):
    """pressure.box_read() + pressure.box_alert() on the live files.

    Portfolio and feed health come from the same readers the dashboard uses, so
    the alert and the panel cannot disagree about a cooldown or a stale tape.
    """
    now = now or utcnow()
    rows = P.tail_rows(log_file, TAIL_ROWS, window_bytes=1024 * 1024)
    if not rows:
        return {"fire": False, "blockers": [f"no rows in {log_file}"], "text": "",
                "key": None, "now": now, "spread_usd": None}
    trades = P.read_rows(trades_file)
    try:
        portfolio = P.portfolio_read(trades, now=now, log_rows=rows)
    except Exception as exc:                       # never let a ledger read kill the notice
        portfolio = None
        print(f"box_alert: portfolio read failed ({exc})", file=sys.stderr)
    feed = P.feed_read(rows, now=now)
    geom = P.box_geometry(rows, spread=spread) if spread else P.box_geometry(rows)
    regime = P.box_regime(rows)
    status = P.box_status(geom, portfolio=portfolio, feed=feed, now=now,
                          spread=spread or P.BOX_SPREAD_USD, regime=regime)
    # box_status() builds its alert with pressure.py's default limits, which is what the
    # dashboard previews. Re-run the SAME pure decision on the same read with the limits
    # in force (the env knobs), so the limiter and the message's own "max 1 per ..."
    # footer agree with them. Whether it fires, and why not, cannot change: the limits
    # only ride along in the result.
    try:
        alert = P.box_alert(status, **alert_limits())
    except Exception as exc:                       # never let a rebuild kill the notice
        print(f"box_alert: alert rebuild failed ({exc})", file=sys.stderr)
        alert = status.get("alert")
    out = dict(alert or {"fire": False, "blockers": ["no alert read"]})
    out["now"] = now
    out["verdict"] = status.get("verdict")
    out["spread_usd"] = status.get("spread_usd")
    out["as_of"] = geom.get("as_of") if geom.get("ok") else None
    out["chop"] = status.get("chop")
    out["retest"] = status.get("retest")
    return out


# ───────────────────────────────────────────────────────────── dedupe state (only write)
def load_state(path=STATE_FILE):
    """{"sent": {key: iso}, "day": "YYYY-MM-DD", "count": n, "history": [...]}"""
    try:
        with open(path) as f:
            state = json.load(f)
        if isinstance(state, dict):
            state.setdefault("sent", {})
            state.setdefault("history", [])
            state.setdefault("last_sent", None)
            return state
    except (OSError, ValueError):
        pass
    return {"sent": {}, "day": None, "count": 0, "last_sent": None, "history": []}


def save_state(state, path=STATE_FILE):
    """Atomic-ish write of OUR OWN file. Nothing else in the repo is touched."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=1, default=str)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        print(f"box_alert: could not write {path}: {exc}", file=sys.stderr)
        return False


def touch_heartbeat(path=STATE_FILE, now=None, interval=DEFAULT_INTERVAL):
    """--loop's liveness mark, written into OUR OWN state file.

    The file is re-read first, so a send booked a moment earlier is never lost.
    Mirrors the lesson of 2026-09-29: the only reliable sign that a sidecar is alive
    is the sidecar's own fresh output. "The pair is configured" and "a unit is
    installed" are both claims about the setup, not about a running loop.
    """
    now = now or utcnow()
    state = load_state(path)
    state["loop"] = {"heartbeat": now.strftime("%Y-%m-%d %H:%M:%S"),
                     "interval_s": max(5, int(interval))}
    return save_state(state, path)


def loop_health(state, now=None):
    """("running" | "stopped" | "never", last heartbeat or None) from --loop's mark.

    `stopped` = a heartbeat older than max(HEARTBEAT_STALE_S, 3 ticks). `never` = no
    --loop has ever run (with this version) against this state file.
    """
    now = now or utcnow()
    loop = state.get("loop") if isinstance(state.get("loop"), dict) else {}
    beat = P.parse_ts(loop.get("heartbeat"))
    if beat is None:
        return "never", None
    try:
        interval = max(5, int(loop.get("interval_s") or DEFAULT_INTERVAL))
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL
    stale_after = max(HEARTBEAT_STALE_S, 3 * interval)
    return ("running" if (now - beat).total_seconds() <= stale_after else "stopped"), beat


def suppressed(decision, state, now=None):
    """Thin wrapper: the limiter itself is pressure.box_alert_suppressed (pure), so
    the sidecar, the dashboard preview and a replay share one implementation."""
    return P.box_alert_suppressed(decision, state, now=now)


def record_send(state, decision, now=None):
    """Thin wrapper around pressure.box_alert_record."""
    return P.box_alert_record(state, decision, now=now)


# ────────────────────────────────────────────────────────────────────────── the send
def send_telegram(text, token=None, chat_id=None, timeout=SEND_TIMEOUT):
    """One POST to the Telegram Bot API. Returns (ok, detail). Stdlib only.

    No parse_mode: the message is plain text on purpose, so a level like
    `4132.21_5` can never be mangled by Markdown escaping.
    """
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"
    payload = json.dumps({"chat_id": str(chat_id), "text": text,
                          "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        if body.get("ok"):
            return True, "sent"
        return False, f"telegram said: {body.get('description', 'unknown error')}"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return False, f"telegram request failed: {exc}"


def alerts_enabled(env=None):
    env = os.environ if env is None else env
    return (env.get("GOLD_BOX_ALERTS") or "1").strip().lower() not in ("0", "false", "no", "off")


# ───────────────────────────────────────────────────────────────────────────── CLI
def digest_line(state, decision=None, now=None, env=None, env_file=None):
    """One line for the autosync digest: no secrets, no traceback.

    It answers four questions in order. Is it switched off? Is the Telegram pair
    there (environment or env file)? Is the notifier actually running (its --loop
    heartbeat)? What has it sent? `env` defaults to os.environ. main() has already
    filled os.environ from the env file. `env_file` only names where it looked.
    """
    env = os.environ if env is None else env
    now = now or utcnow()
    day = now.strftime("%Y-%m-%d")
    today = int(state.get("count") or 0) if state.get("day") == day else 0
    last = state.get("history", [])[-1] if state.get("history") else None
    if not alerts_enabled(env):
        return "box alerts: disabled (GOLD_BOX_ALERTS=0)"
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
        where = f" in the environment or {env_file}" if env_file else ""
        return f"box alerts: not configured (no TELEGRAM_BOT_TOKEN/CHAT_ID{where})"
    tail = f"last {last['ts'][5:16]} UTC {last['side']}" if last else "none sent yet"
    sent = f"{today} sent today · {tail}"
    health, beat = loop_health(state, now)
    if health == "never":
        # The pair alone is not a notifier: without a running --loop nothing is sent.
        return ("box alerts: Telegram pair found · notifier not running "
                "(optional: install deploy/boxalert.service)"
                + (f" · {sent}" if (last or today) else ""))
    if health == "stopped":
        return f"box alerts: notifier STOPPED (last heartbeat {beat:%m-%d %H:%M} UTC) · {sent}"
    if decision and decision.get("fire"):
        sent += " · a candidate is live now"
    return f"box alerts: running · {sent}"


def decide_once(args, now=None, sender=send_telegram, state_path=None):
    """One decision → maybe one message. Returns (exit_code, printable_summary)."""
    now = now or utcnow()
    state_path = state_path or args.state
    decision = read_decision(log_file=args.log, status_file=args.status,
                             trades_file=args.trades, spread=args.spread, now=now)
    state = load_state(state_path)
    if not decision.get("fire"):
        why = decision.get("blockers") or ["no candidate"]
        return 0, {**_summary(decision, state, now), "action": "no alert",
                   "reason": "; ".join(why[:4])}
    block = suppressed(decision, state, now=now)
    if block:
        return 0, {**_summary(decision, state, now), "action": "suppressed", "reason": block}
    if args.dry_run:
        return 0, {**_summary(decision, state, now), "action": "would send (dry run)"}
    if not alerts_enabled():
        return 0, {**_summary(decision, state, now), "action": "disabled (GOLD_BOX_ALERTS=0)"}
    ok, detail = sender(decision["text"])
    if not ok:
        # A failed send is not recorded, so the next tick retries — but it never
        # raises: a dead Telegram API must not take the loop (or a digest) down.
        return 0, {**_summary(decision, state, now), "action": "SEND FAILED", "reason": detail}
    save_state(record_send(state, decision, now=now), state_path)
    return 0, {**_summary(decision, state, now), "action": "sent", "reason": detail}


def _summary(decision, state, now):
    return {"ts": now.strftime("%Y-%m-%d %H:%M:%S"),
            "side": decision.get("side"), "box": decision.get("box"),
            "verdict": (decision.get("verdict") or {}).get("headline"),
            "as_of": str(decision.get("as_of") or ""),
            "sent_today": int(state.get("count") or 0) if state.get("day") == now.strftime("%Y-%m-%d") else 0,
            "text": decision.get("text", "")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="decide once and exit (default)")
    ap.add_argument("--loop", action="store_true", help="decide every --interval seconds")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                    help=f"seconds between decisions in --loop (default {DEFAULT_INTERVAL})")
    ap.add_argument("--dry-run", action="store_true",
                    help="never send; print the decision and the message it would send")
    ap.add_argument("--test", action="store_true",
                    help="send a one-line test message (proves the bot/chat work)")
    ap.add_argument("--quiet", action="store_true",
                    help="print only the one-line digest used by tools/autosync.sh")
    ap.add_argument("--json", action="store_true", help="print the decision as JSON")
    ap.add_argument("--state", default=None,
                    help=f"dedupe + heartbeat state file (default $GOLD_BOX_ALERT_STATE, "
                         f"else {os.path.join(DATA_DIR, 'box_alert_state.json')})")
    ap.add_argument("--env-file", default=ENV_FILE,
                    help=f"settings file read for keys the environment lacks (default {ENV_FILE}; "
                         f"/dev/null = environment only)")
    ap.add_argument("--log", default=LOG_FILE, help=f"1-min log (default {LOG_FILE})")
    ap.add_argument("--status", default=STATUS_FILE, help=f"status.json (default {STATUS_FILE})")
    ap.add_argument("--trades", default=TRADES_FILE, help=f"trades.csv (default {TRADES_FILE})")
    ap.add_argument("--spread", type=float, default=None,
                    help=f"round-trip cost $/oz (default {P.BOX_SPREAD_USD})")
    args = ap.parse_args(argv)

    # First, before any setting is read: take what the environment lacks from the env
    # file, the one engine.py and the unit's EnvironmentFile= use. Then resolve the state
    # path, so a GOLD_BOX_ALERT_STATE set only in that file still counts.
    apply_env_file(args.env_file)
    if not args.state:
        args.state = (os.getenv("GOLD_BOX_ALERT_STATE")
                      or os.path.join(DATA_DIR, "box_alert_state.json"))

    if args.test:
        ok, detail = send_telegram(
            "📦 gold box watch: test message from box_alert.py "
            f"({utcnow().strftime('%Y-%m-%d %H:%M')} UTC). Display only — no order is placed.")
        print(f"test message: {'sent' if ok else 'FAILED'} ({detail})")
        return 0 if ok else 1

    if args.quiet:
        decision = None
        try:
            decision = read_decision(log_file=args.log, status_file=args.status,
                                     trades_file=args.trades, spread=args.spread)
        except Exception as exc:
            print(f"box alerts: report failed to run ({exc})")
            return 0
        print(digest_line(load_state(args.state), decision, env_file=args.env_file))
        return 0

    if args.loop:
        lim = alert_limits()
        print(f"box_alert: looping every {args.interval}s (spacing "
              f"{lim['global_cooldown_minutes']:g} min, per edge {lim['cooldown_minutes']:g} min, "
              f"cap {lim['daily_cap']}/day; Telegram pair "
              f"{'found' if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID') else 'MISSING'}"
              f"{'' if alerts_enabled() else '; DISABLED by GOLD_BOX_ALERTS'}) — "
              f"display only, no order is placed", flush=True)
        while True:
            # Stamp first, so the mark exists seconds after a (re)start - autosync restarts
            # the unit and then reads this in the same run. A send later in this tick re-reads
            # the file, so the stamp survives it.
            if not args.dry_run:                        # --dry-run promises no state write
                try:
                    touch_heartbeat(args.state, interval=args.interval)
                except Exception as exc:                # liveness must not kill the sidecar
                    print(f"box_alert: heartbeat failed: {exc}", file=sys.stderr, flush=True)
            try:
                rc, out = decide_once(args)
                if out["action"] != "no alert":
                    print(f"{out['ts']} {out['action']}: {out.get('reason', '')} "
                          f"[{out.get('side')} {out.get('box')}]", flush=True)
            except Exception as exc:                    # a bad bar must not kill the sidecar
                print(f"box_alert: decision failed: {exc}", file=sys.stderr, flush=True)
            time.sleep(max(5, args.interval))

    rc, out = decide_once(args)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"{out['ts']} · {out['action']}"
              + (f" — {out['reason']}" if out.get("reason") else "")
              + (f"\n{out['side']} @ {out['box']} · verdict: {out['verdict']}"
                 if out.get("side") else ""))
        if out.get("text") and (args.dry_run or out["action"] == "sent"):
            print("\n--- message ---\n" + out["text"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
