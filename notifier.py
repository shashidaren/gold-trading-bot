#!/usr/bin/env python3
"""notifier.py — read-only Telegram pings from the dashboard's market-context layer.

WHAT THIS IS
    The phone-side half of the 2026-10-16 dashboard read layer (pressure.py). The
    dashboard answers "which way is the tape pushed, and would the engine take
    this bar?" — but only while you are looking at it. This module pushes the two
    answers that matter to Telegram, rate-limited and de-duplicated:

      🎯 setup ping  — the engine's own 8 entry gates are ALL green on the last
                       closed bar (rising edge only): the closest thing this repo
                       has to "a good time to BUY/SELL" that is not an opinion.
                       The message carries the engine's live state too (blocked?
                       cooldown? already in a trade?), because 19 setups in the
                       last 24 h passed the gates and were still skipped.
      🌡️ tape ping   — the pressure composite the dashboard shows flipped into
                       its strong band (>= 70% one way, re-armed only after the
                       tape returns to the middle 40-60 band or flips over).

    Suppression rule: if the engine itself just opened the trade (status.json,
    entry within the last few minutes), the setup ping stays quiet — the engine
    already sends its own "GOLD BUY SETUP #N" message and a duplicate adds noise,
    not information.

WHAT THIS IS NOT
    It is NOT a strategy input and NOT advice. Nothing here is imported by
    engine.py or trade_filter.py; nothing here writes a trades/log/skip/status
    file (the only write is its own state dot-file, which exists purely to
    de-duplicate pings across restarts); no number it reads may become an entry
    condition (docs/HANDOFF.md §6.7). The tape composite is measured to be
    collinear with side — the message says so in its own footer, every time
    (docs/ANALYSIS-2026-10-16-dashboard-pressure.md §calibration; the same
    verdict is re-printed live by tools/pressure_report.py).

RUN PATHS (pick ONE, or pings can double)
    1. Default: the dashboard's background thread (dashboard.py start_notifier_thread).
       Zero new services: a dashboard.py change is DASH_CHANGED for autosync —
       the dashboard restarts, the thread comes with it, the engine never does.
       Env switch: GOLD_NOTIFIER=0 disables.
    2. Standalone: python3 notifier.py --loop  (own process/timer; then set
       GOLD_NOTIFIER=0 for the dashboard thread).

CLI (safe on any checkout — reads are the same files the dashboard reads):
    python3 notifier.py --once --dry-run     # evaluate now, print instead of send
    python3 notifier.py --once               # evaluate + send (needs creds)
    python3 notifier.py --loop               # daemon, default 60 s poll
    python3 notifier.py --test               # send one test message, exit 1 on fail
    python3 notifier.py --status             # print config + state
    --root DIR reads DIR/{forward_test_log,trades,skipped_trades}.csv + status.json
    and keeps its state in DIR/.pressure_notifier_state.json (same file the
    dashboard thread uses, so the two paths agree on what was already pinged).

CREDENTIALS (never committed): TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from the
environment, else parsed from <GOLD_DATA_DIR>/.env the same way tools/autosync.sh
does. Without credentials the module stays silent and dry-prints.

HONESTY MECHANICS (all pinned by tools/smoke_test.py Scenario V)
    * evaluate() is pure: (data, status, state, now) -> (messages, state, notes).
      No wall clock, no network, no file IO — the smoke test drives it with
      synthetic build()-shaped dicts and fixed timestamps.
    * Never fires on the first bar after a fresh state (restart protection).
    * Never fires on a stale feed (age > GOLD_NOTIFIER_FEED_MAX_AGE, default
      240 s) — a closed market must not re-ping Friday's tape.
    * Each closed bar is evaluated exactly once (as_of de-duplication).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pressure as P  # noqa: E402  — the single source of every read here

# ─────────────────────────────────────────────────────────────────────────────
# Config (env-overridable; defaults are deliberately quiet)
# ─────────────────────────────────────────────────────────────────────────────

DATA_DIR = os.getenv("GOLD_DATA_DIR", "/opt/gold")
ENV_FILE = os.path.join(DATA_DIR, ".env")
DEFAULT_STATE_PATH = os.path.join(DATA_DIR, ".pressure_notifier_state.json")
STATE_PATH = os.getenv("GOLD_NOTIFIER_STATE", DEFAULT_STATE_PATH)

POLL_INTERVAL_SECONDS = max(30, int(os.getenv("GOLD_NOTIFIER_INTERVAL", "60") or 60))

# tape trigger: fire when the composite enters the strong band (>= 70% one way —
# the same 70 the dashboard's "Tape pushed ... hard" label uses), re-arm only
# after it returns to the middle (|buy-50| <= 10) or flips to the other side.
TAPE_STRONG_PCT = float(os.getenv("GOLD_NOTIFIER_TAPE_STRONG", "70") or 70)
TAPE_REARM_PCT = float(os.getenv("GOLD_NOTIFIER_TAPE_REARM", "10") or 10)

# rate limits (minutes): per trigger+side, and between any two pings at all
SETUP_GAP_MIN = float(os.getenv("GOLD_NOTIFIER_SETUP_GAP", "20") or 20)
TAPE_GAP_MIN = float(os.getenv("GOLD_NOTIFIER_TAPE_GAP", "45") or 45)
GLOBAL_GAP_MIN = float(os.getenv("GOLD_NOTIFIER_GLOBAL_GAP", "5") or 5)

# a feed older than this is a closed/stalled market, not a signal
FEED_MAX_AGE_SECONDS = float(os.getenv("GOLD_NOTIFIER_FEED_MAX_AGE", "240") or 240)

# if the engine opened a trade this recently, its own Telegram message covers it
ENGINE_ENTRY_SUPPRESS_MIN = float(os.getenv("GOLD_NOTIFIER_ENGINE_SUPPRESS_MIN", "5") or 5)

COMPONENT_SHORT = {
    "flow": "flow",
    "momentum": "momo",
    "trend": "EMA50−EMA200",
    "slope": "EMA50 slope",
    "rsi": "RSI",
}


# ─────────────────────────────────────────────────────────────────────────────
# State (the only thing this module ever writes, and only its own dot-file)
# ─────────────────────────────────────────────────────────────────────────────

def default_state():
    return {
        "version": 1,
        "last_as_of": None,                      # last evaluated bar timestamp
        "setup_was_ready": {"BUY": False, "SELL": False},
        "tape_armed": {"BUY": True, "SELL": True},
        "last_ping": {},                         # "setup:BUY" -> iso timestamp
        "last_ping_any": None,
    }


def load_state(path=None):
    path = path or STATE_PATH
    st = default_state()
    try:
        with open(path) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            st.update(loaded)
            for key in ("setup_was_ready", "tape_armed", "last_ping"):
                if not isinstance(st.get(key), dict):
                    st[key] = default_state()[key]
    except (OSError, ValueError):
        pass  # missing/corrupt -> fresh state (in memory; see save_state)
    return st


def save_state(state, path=None):
    """Best-effort persist. A read-only data dir is legal: the loop keeps
    working in memory (restart protection is then per-process, that is all)."""
    path = path or STATE_PATH
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        print(f"notifier: state not persisted ({exc}) — continuing in memory")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Telegram (stdlib only — this module must import wherever the dashboard does)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_env_file(path):
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip().strip("\"'").strip()
    except OSError:
        pass
    return out


def telegram_credentials():
    """(token, chat_id) from env, else from <DATA_DIR>/.env like autosync.sh."""
    env = os.environ
    file = _parse_env_file(ENV_FILE) if not env.get("TELEGRAM_BOT_TOKEN") else {}
    token = env.get("TELEGRAM_BOT_TOKEN") or file.get("TELEGRAM_BOT_TOKEN")
    chat = env.get("TELEGRAM_CHAT_ID") or file.get("TELEGRAM_CHAT_ID")
    return (token, chat) if token and chat else (None, None)


class TelegramSender:
    def __init__(self, token, chat_id):
        self.token, self.chat_id = token, chat_id

    def send(self, text):
        data = json.dumps({"chat_id": str(self.chat_id), "text": text,
                           "parse_mode": "Markdown"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:  # network is never a reason to crash a loop
            print(f"notifier: telegram send failed: {exc}")
            return False


def sender_from_env():
    token, chat = telegram_credentials()
    return TelegramSender(token, chat) if token and chat else None


# ─────────────────────────────────────────────────────────────────────────────
# Message rendering (pure; tolerates a half-empty build() dict)
# ─────────────────────────────────────────────────────────────────────────────

def _m(value, nd=2):
    return "—" if value is None else f"{value:.{nd}f}"


def _engine_state_line(side, portfolio, status):
    """One honest line about whether the ENGINE can actually act on this."""
    if status.get("trade_active"):
        return (f"Engine: already in a {status.get('trade_type') or 'trade'} "
                f"(#{status.get('current_trade_num') or '?'}) — one position at a time, "
                f"this setup passes unused")
    blocked = (portfolio.get("sides_blocked") or {}).get(side)
    if blocked:
        return f"Engine: BLOCKED — {blocked}"
    if portfolio.get("cooldown_minutes_left"):
        note = portfolio.get("cooldown_note") or "SL cooldown"
        return (f"Engine: BLOCKED — SL cooldown {portfolio['cooldown_minutes_left']}"
                f" min left ({note})")
    if portfolio.get("breaker_on"):
        return (f"Engine: BREAKER ON — {portfolio.get('daily_sls')}"
                f"/{P.MAX_DAILY_LOSSES} daily SLs, trend-side-only")
    return "Engine: free to trade — its own entry alert follows if it takes the bar"


def render_setup_message(side, data, status):
    s = data.get("setup") or {}
    d = s.get(side) or {}
    p = data.get("pressure") or {}
    level_name = "floor" if side == "BUY" else "ceiling"
    dist = d.get("level_dist_atr")
    loc = (f"{dist:.2f} ATR from the {level_name}" if dist is not None else "—")
    tape = (f"tape BUY {p['buy_pct']:.0f}% / SELL {p['sell_pct']:.0f}%"
            if p.get("buy_pct") is not None else "tape n/a")
    return "\n".join([
        f"🎯 GOLD {side} setup ready — {d.get('passed', '?')}/{d.get('total', '?')} "
        f"entry gates pass on the last closed bar",
        f"{s.get('as_of') or '—'} UTC · close `{_m(s.get('close'))}` · "
        f"{level_name} `{_m(d.get('level'))}` · {loc}",
        f"RSI {_m(s.get('rsi'), 1)} · ATR {_m(s.get('atr'))} · {tape}",
        _engine_state_line(side, data.get("portfolio") or {}, status or {}),
        "Read-only ping from the dashboard layer — context, not a signal (paper bot).",
    ])


def render_tape_message(side, data):
    p = data.get("pressure") or {}
    s = data.get("setup") or {}
    comps = " · ".join(
        f"{COMPONENT_SHORT.get(c.get('key'), c.get('key'))} {c.get('raw', '—')}"
        for c in p.get("components") or [])
    parts = []
    for s_side in ("BUY", "SELL"):
        sd = s.get(s_side) or {}
        if sd.get("total"):
            parts.append(f"{s_side} {sd.get('passed')}/{sd.get('total')}")
    misses = s.get("nearest_miss") or {}
    miss = misses.get(side)
    miss_line = f" — first missing {side} gate: {miss}" if miss else ""
    setup_line = " · ".join(parts) if parts else "setup n/a"
    return "\n".join([
        f"🌡️ GOLD {str(p.get('label') or 'tape').lower()} — "
        f"BUY {_m(p.get('buy_pct'), 1)}% / SELL {_m(p.get('sell_pct'), 1)}% "
        f"(last {p.get('window', '?')} closed bars)",
        comps or "components n/a",
        f"Setup read: {setup_line}{miss_line}",
        "Context, not a signal — calibration: the composite tracks the side the "
        "trend gate already allows (docs/ANALYSIS-2026-10-16-dashboard-pressure.md).",
    ])


# ─────────────────────────────────────────────────────────────────────────────
# evaluate() — the pure decision core (no clock, no network, no files)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ts(value):
    return P.parse_ts(value) if value else None


def _minutes_since(ts, now):
    return None if ts is None else (now - ts).total_seconds() / 60.0


def _gap_ok(state, key, now, gap_min):
    last = _parse_ts((state.get("last_ping") or {}).get(key))
    return last is None or (now - last).total_seconds() / 60.0 >= gap_min


def _global_gap_ok(state, now):
    last = _parse_ts(state.get("last_ping_any"))
    return last is None or (now - last).total_seconds() / 60.0 >= GLOBAL_GAP_MIN


def _mark_ping(state, key, now):
    state.setdefault("last_ping", {})[key] = now.strftime("%Y-%m-%d %H:%M:%S")
    state["last_ping_any"] = now.strftime("%Y-%m-%d %H:%M:%S")


def evaluate(data, status, state, now):
    """Decide what to ping for the newest closed bar.

    `data` is pressure.build()'s dict, `status` the parsed status.json (or {}),
    `state` this module's own state, `now` a naive-UTC datetime. Returns
    (messages, new_state, notes): messages are {"key", "text"} dicts in send
    order; notes are human-readable skip reasons (for --status / the journal).
    Pure: same inputs -> same outputs, nothing touched on disk.
    """
    notes = []
    st = default_state()
    st.update(state or {})

    feed = data.get("feed") or {}
    if not feed.get("ok"):
        return [], st, [f"feed not readable ({feed.get('reason')}) — skipped"]
    age = feed.get("age_seconds")
    if age is None or age > FEED_MAX_AGE_SECONDS:
        return [], st, [f"feed stale ({age}s > {FEED_MAX_AGE_SECONDS:.0f}s) — skipped"]

    as_of = (data.get("setup") or {}).get("as_of") or (data.get("pressure") or {}).get("as_of")
    if not as_of:
        return [], st, ["no bar timestamp — skipped"]
    if st.get("last_as_of") == as_of:
        return [], st, ["bar already evaluated"]
    first_bar = st.get("last_as_of") is None
    st["last_as_of"] = as_of
    # The global gap spaces pings ACROSS evaluations; two triggers firing on the
    # same bar (tape + setup) are one event and both go out together.
    global_ok = _global_gap_ok(st, now)

    messages = []

    # ── tape trigger: strong-band entry, re-armed through the middle ──────────
    p = data.get("pressure") or {}
    buy = p.get("buy_pct")
    if buy is not None:
        if abs(buy - 50.0) <= TAPE_REARM_PCT:            # middle band re-arms both
            st["tape_armed"] = {"BUY": True, "SELL": True}
        for side, strong in (("BUY", buy >= TAPE_STRONG_PCT),
                             ("SELL", buy <= 100.0 - TAPE_STRONG_PCT)):
            if not strong:
                continue
            if not first_bar and st["tape_armed"].get(side) \
                    and _gap_ok(st, f"tape:{side}", now, TAPE_GAP_MIN) \
                    and global_ok:
                messages.append({"key": f"tape:{side}",
                                 "text": render_tape_message(side, data)})
                _mark_ping(st, f"tape:{side}", now)
                st["tape_armed"][side] = False
                st["tape_armed"]["SELL" if side == "BUY" else "BUY"] = True
            elif first_bar:
                notes.append(f"tape {side} strong on the first bar — recorded, not pinged")
            elif not st["tape_armed"].get(side):
                pass  # still in the strong band, already pinged: stay quiet
            else:
                notes.append(f"tape {side} strong but rate-limited")
        if not (buy >= TAPE_STRONG_PCT or buy <= 100.0 - TAPE_STRONG_PCT):
            pass  # leaning/flat: nothing to do, arming handled by the middle band

    # ── setup trigger: rising edge of all-gates-ready, per side ────────────────
    s = data.get("setup") or {}
    if s.get("ok"):
        for side in ("BUY", "SELL"):
            ready = bool((s.get(side) or {}).get("ready"))
            was_ready = bool((st.get("setup_was_ready") or {}).get(side))
            st["setup_was_ready"][side] = ready
            if not ready or was_ready:
                continue
            if first_bar:
                notes.append(f"{side} ready on the first bar — recorded, not pinged")
                continue
            entry_ts = _parse_ts(status.get("entry_time")) if status.get("trade_active") else None
            mins = _minutes_since(entry_ts, now)
            if mins is not None and 0 <= mins <= ENGINE_ENTRY_SUPPRESS_MIN:
                notes.append(f"{side} setup ready suppressed — the engine opened it "
                             f"{mins:.0f} min ago (its own alert fires)")
                continue
            if not (_gap_ok(st, f"setup:{side}", now, SETUP_GAP_MIN) and global_ok):
                notes.append(f"{side} setup ready ping rate-limited")
                continue
            messages.append({"key": f"setup:{side}",
                             "text": render_setup_message(side, data, status or {})})
            _mark_ping(st, f"setup:{side}", now)

    return messages, st, notes


# ─────────────────────────────────────────────────────────────────────────────
# Run paths
# ─────────────────────────────────────────────────────────────────────────────

def _read_status(path=None):
    try:
        with open(path or P.STATUS_FILE_PATH) as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _use_root(root):
    """Point pressure's reads and our state at a checkout dir (CLI/tests)."""
    root = os.path.abspath(root)
    P.LOG_FILE_PATH = os.path.join(root, "forward_test_log.csv")
    P.TRADES_FILE_PATH = os.path.join(root, "trades.csv")
    P.SKIP_FILE_PATH = os.path.join(root, "skipped_trades.csv")
    P.STATUS_FILE_PATH = os.path.join(root, "status.json")
    return os.path.join(root, ".pressure_notifier_state.json")


def run_once(root=None, dry_run=False, sender=None, state_path=None, now=None):
    """One evaluation cycle. Never raises on data problems (a ping loop must
    outlive a torn CSV tail); returns a summary dict for the CLI / tests.
    `now` (naive UTC) is injectable so tests can evaluate a synthetic tape
    without a wall clock; the live paths leave it None."""
    if root:
        state_path = state_path or _use_root(root)
    state_path = state_path or STATE_PATH
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    data = P.build(now=now)
    status = _read_status()
    state = load_state(state_path)
    messages, state, notes = evaluate(data, status, state, now)

    sent, printed = [], []
    for msg in messages:
        if dry_run or sender is None:
            prefix = "DRY" if dry_run else "NO-CREDS"
            print(f"[{prefix}] would send ({msg['key']}):\n{msg['text']}\n")
            printed.append(msg["key"])
        elif sender.send(msg["text"]):
            sent.append(msg["key"])
        else:
            notes.append(f"send failed: {msg['key']}")
    # ALWAYS persist, not only when something fired: the first bar after a fresh
    # state must record itself (restart protection) or the module could never
    # get past "first bar" and would stay silent forever.
    save_state(state, state_path)
    return {"as_of": state.get("last_as_of"), "sent": sent, "printed": printed,
            "notes": notes, "state": state}


def loop(interval=None, dry_run=False, sender=None):
    interval = interval or POLL_INTERVAL_SECONDS
    sender = sender if sender is not None else sender_from_env()
    if sender is None and not dry_run:
        print("notifier: no Telegram credentials — looping in dry-print mode "
              "(set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID or GOLD_DATA_DIR/.env)")
    while True:
        started = time.monotonic()
        try:
            run_once(dry_run=dry_run, sender=sender)
        except Exception as exc:  # a torn tail / missing file must not kill the loop
            print(f"notifier: run failed: {exc}")
        time.sleep(max(1.0, interval - (time.monotonic() - started)))


def _test_message():
    return ("🔔 gold notifier test — Telegram pings are wired up "
            f"(triggers: setup-ready, tape-flip). Sent "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Read-only Telegram pings from the dashboard market-context layer "
                    "(setup-ready + tape-flip). Never trades, never writes data files.")
    ap.add_argument("--loop", action="store_true", help="keep polling (default: one shot)")
    ap.add_argument("--once", action="store_true", help="one evaluation (the default)")
    ap.add_argument("--dry-run", action="store_true", help="print messages instead of sending")
    ap.add_argument("--test", action="store_true", help="send one test message; exit 1 on failure")
    ap.add_argument("--status", action="store_true", help="print config + current state, then exit")
    ap.add_argument("--root", default=None,
                    help="read DIR/{forward_test_log,trades,skipped_trades}.csv + status.json")
    ap.add_argument("--interval", type=int, default=None, help="poll seconds for --loop")
    args = ap.parse_args(argv)

    if args.status:
        st = load_state()
        token, chat = telegram_credentials()
        print(f"credentials: {'configured' if token else 'MISSING (env or ' + ENV_FILE + ')'}")
        print(f"state file:  {STATE_PATH}")
        print(f"triggers:    setup-ready (gap {SETUP_GAP_MIN:.0f}m), tape>="
              f"{TAPE_STRONG_PCT:.0f}% (gap {TAPE_GAP_MIN:.0f}m), "
              f"global gap {GLOBAL_GAP_MIN:.0f}m, feed max age {FEED_MAX_AGE_SECONDS:.0f}s")
        print(f"last bar:    {st.get('last_as_of')}")
        print(f"tape armed:  {st.get('tape_armed')}")
        print(f"last pings:  {json.dumps(st.get('last_ping', {}), indent=2)}")
        return 0

    if args.test:
        sender = sender_from_env()
        if sender is None:
            print("notifier --test: no credentials configured")
            return 1
        return 0 if sender.send(_test_message()) else 1

    if args.loop:
        loop(interval=args.interval, dry_run=args.dry_run)
        return 0
    summary = run_once(root=args.root, dry_run=args.dry_run)
    if not (summary["sent"] or summary["printed"]):
        print(f"notifier: nothing to send ({'; '.join(summary['notes']) or 'no trigger'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
