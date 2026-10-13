#!/usr/bin/env python3
"""XM quote + contract-spec logger for GOLD - a READ-ONLY Wine sidecar.
(port of bitcoin-trading-bot's tools/mt5_quotes.py, PR #10, minus the shadow candles: gold's
engine already consumes this same broker's feed, so there is no parity question to answer)

Why this exists (docs/ANALYSIS-2026-10-13-btc-port-assessment.md item 9, HANDOFF §6): every
costed number in this repo - tools/strategy_lab.py, `win_rate_report.py --spread`, the snapshot's
net_pnl_usd_at_cost - charges a FLAT, ASSUMED $0.20 per side. The paper engine books no spread at
all, 215 of 575 trades are scratches that would each pay one, and the ledger is -$319.51 gross but
-$549.51 at the assumed cost. Real GOLD spreads also widen in Asia/rollover and at news while the
model is flat. This daemon measures what the broker actually quotes and offers, without touching
engine.py, DATA_SOURCE or the forward-test sample.

What it writes (all under MT5_QUOTES_DIR, default Z:/opt/gold/xm_data):

  quotes-YYYY-MM-DD.csv   one row per MT5_QUOTES_INTERVAL seconds (default 30), UTC day files:
        ts_utc        window start on the box clock, aligned to the interval (UTC)
        bid, ask      the POINT SAMPLE: first valid quote of the window (~1 s after the boundary,
                      so the :00 / :30 rows are the quote a minute-close signal would be filled at)
        spread        ask - bid of the point sample (USD per oz; x0.01 lot x contract = $/trade)
        spread_min/max  envelope over every poll in the window (default every 5 s), so a spike
                      between two rows is not invisible
        n_ok, n_bad   valid / invalid polls in the window
        tick_age_s    age of the point sample's tick when polled (staleness: a closed market
                      shows up here and as the STALE flag)
        srv_offset_s  broker-server-time offset from UTC in force (seconds)
        flags         ';'-joined: STALE NOQUOTE BADQUOTE NOOFFSET LATE
  symbol_spec.json        latest contract-spec snapshot (allow-listed, decoded)
  symbol_spec_history.jsonl   one line each time the spec CHANGES (swap, stops level, ...)

Rows are written through closures too (weekend, daily break): they carry STALE (a frozen tick), so
the report separates "the market was shut" from "the logger died" - and the logged srv_offset_s is
a free, empirical record of the broker's DST behaviour (the large-N history converter needs it).

TIME. MT5 'time' fields are BROKER SERVER time encoded as epoch seconds, not UTC (gold shows it:
status.json mt5_last_candle_ts renders 3 h ahead of the engine's UTC clock). There is no API for
the server's zone; the only way to learn it is to compare a FRESH tick with the local clock:
tick.time - now = offset - age. XM's server time is GMT+2 in winter and GMT+3 in summer on the EU
rule (last Sunday of March/October; next change Sun 2026-10-25), so the offset CHANGES twice a year.
This tool estimates a whole-hour offset from every fresh tick, uses the current estimate, and
records it on every row.

PRIVACY. The repo is PUBLIC and tools/autosync.sh commits xm_data/. MT5's account_info() carries
login, name, balance, equity and server; terminal_info() carries Windows user paths. This tool NEVER
dumps those objects: it copies an explicit allow-list of non-identifying fields (SYMBOL_FIELDS /
ACCOUNT_FIELDS / TERMINAL_FIELDS) and prints no login. The account tier, which XM does not expose,
is an operator-chosen free-text label (MT5_QUOTES_LABEL). Locked by tools/smoke_test.py Scenario Q.

READ-ONLY. It never sends, checks, modifies or lists orders or positions. The only calls it makes
are symbol_select (Market Watch), symbol_info(_tick), account_info, terminal_info and the pure
calculators order_calc_profit/order_calc_margin. Scenario Q walks this file's AST and fails if any
trading API name is referenced, and drives it against a fake terminal that records any such call.

Run (manual test - mirrors the mt5-balance alias and tools/mt5_feed.py):
  export WINEPREFIX=~/.mt5
  xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_quotes.py --spec
  xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_quotes.py --once
Or as a service (deploy/mt5quotes.service; note the -gold suffix on the installed name):
  sudo systemctl enable --now mt5quotes-gold

Modes:  (none) run forever | --spec print the spec snapshot, write nothing |
        --once one cycle (start-up, one poll, flush, spec) then exit

Env overrides: MT5_QUOTES_SYMBOL (GOLD), MT5_QUOTES_DIR, MT5_QUOTES_INTERVAL (30 s, row cadence),
MT5_QUOTES_POLL (5 s, sub-sample cadence; must divide the interval), MT5_QUOTES_LABEL (free text,
e.g. "XM Standard demo").

Only the stdlib and the MetaTrader5 package are needed (no numpy/pandas imports here). The file
imports cleanly WITHOUT MetaTrader5 so tests and tools can use its pure functions.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:          # Linux box, CI, smoke test: importable, just not runnable
    mt5 = None

SCHEMA_VERSION = 1
TS_FMT = "%Y-%m-%d %H:%M:%S"

QUOTE_FIELDS = ["ts_utc", "bid", "ask", "spread", "spread_min", "spread_max",
                "n_ok", "n_bad", "tick_age_s", "srv_offset_s", "flags"]

QUOTES_PREFIX = "quotes-"
SPEC_FILE = "symbol_spec.json"
SPEC_HISTORY_FILE = "symbol_spec_history.jsonl"

# --- tunables ---------------------------------------------------------------------------
DEFAULT_SYMBOL = "GOLD"
DEFAULT_DIR = "Z:/opt/gold/xm_data"          # Wine's Z: is the Linux root
LAG_S = 1.0                  # sample just after the boundary so the new minute's quotes exist
STALE_TICK_S = 120           # a point-sample tick older than this is flagged STALE (closed market)
OFFSET_MAX_AGE_S = 300       # residual (tick age + clock skew) allowed when learning the offset
OFFSET_CONFIRM = 2           # a CHANGED offset must be seen on this many consecutive fresh ticks
MAX_OFFSET_H = 14            # implausible beyond +-14 h
SPEC_EVERY_S = 6 * 3600      # re-read the contract spec this often (changes are history-logged)
REINIT_AFTER_S = 60          # no valid quote this long -> shutdown()/initialize() again
DEAD_AFTER_S = 900           # ...and this long -> exit(2) so systemd restarts a clean process
HEARTBEAT_S = 3600           # one stdout line per hour
ERR_LOG_EVERY_S = 300        # repeated identical errors are printed at most this often

# --- what is allowed into a public repo (explicit allow-lists, never a dump) -------------
SYMBOL_FIELDS = (
    "name", "description", "path", "currency_base", "currency_profit", "currency_margin",
    "digits", "point", "spread_float", "trade_calc_mode", "trade_mode", "trade_exemode",
    "filling_mode", "order_mode", "expiration_mode", "order_gtc_mode",
    "trade_stops_level", "trade_freeze_level",
    "trade_contract_size", "trade_tick_size", "trade_tick_value",
    "trade_tick_value_profit", "trade_tick_value_loss",
    "volume_min", "volume_max", "volume_step", "volume_limit",
    "swap_mode", "swap_long", "swap_short", "swap_rollover3days",
    "swap_sunday", "swap_monday", "swap_tuesday", "swap_wednesday",
    "swap_thursday", "swap_friday", "swap_saturday",
    "margin_initial", "margin_maintenance", "margin_hedged", "margin_hedged_use_leg",
    "start_time", "expiration_time",
)
ACCOUNT_FIELDS = (                      # NOT login, name, server, balance, equity, profit, margin
    "trade_mode", "margin_mode", "leverage", "currency", "currency_digits",
    "limit_orders", "margin_so_mode", "margin_so_call", "margin_so_so",
    "trade_allowed", "trade_expert", "fifo_close", "company",
)
TERMINAL_FIELDS = (                     # NOT path, data_path, commondata_path (Windows user names)
    "build", "connected", "trade_allowed", "tradeapi_disabled", "maxbars", "company", "name",
)
TERMINAL_VOLATILE = ("connected",)      # live state, excluded from the change hash

# --- decoders for the numeric enums/bitmasks (documented MT5 values) ---------------------
FILLING_BITS = {1: "FOK", 2: "IOC", 4: "BOC"}            # SYMBOL_FILLING_* flags
ORDER_MODE_BITS = {1: "MARKET", 2: "LIMIT", 4: "STOP", 8: "STOP_LIMIT", 16: "SL", 32: "TP",
                   64: "CLOSE_BY"}
EXPIRATION_BITS = {1: "GTC", 2: "DAY", 4: "SPECIFIED", 8: "SPECIFIED_DAY"}
EXEMODE = {0: "REQUEST", 1: "INSTANT", 2: "MARKET", 3: "EXCHANGE"}
SYMBOL_TRADE_MODE = {0: "DISABLED", 1: "LONG_ONLY", 2: "SHORT_ONLY", 3: "CLOSE_ONLY", 4: "FULL"}
CALC_MODE = {0: "FOREX", 1: "FUTURES", 2: "CFD", 3: "CFD_INDEX", 4: "CFD_LEVERAGE",
             5: "FOREX_NO_LEVERAGE"}
SWAP_MODE = {0: "DISABLED", 1: "POINTS", 2: "CURRENCY_SYMBOL", 3: "CURRENCY_MARGIN",
             4: "CURRENCY_DEPOSIT", 5: "INTEREST_CURRENT", 6: "INTEREST_OPEN",
             7: "REOPEN_CURRENT", 8: "REOPEN_BID"}
ACCOUNT_TRADE_MODE = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
ACCOUNT_MARGIN_MODE = {0: "RETAIL_NETTING", 1: "EXCHANGE", 2: "RETAIL_HEDGING"}
WEEKDAY = {0: "SUN", 1: "MON", 2: "TUE", 3: "WED", 4: "THU", 5: "FRI", 6: "SAT"}

# The trading API this sidecar must never touch (Scenario Q walks the AST for these names).
FORBIDDEN_API = ("order_send", "order_check", "positions_get", "positions_total", "orders_get",
                 "orders_total", "history_orders_get", "history_deals_get", "history_orders_total",
                 "history_deals_total", "login", "market_book_add")


# =========================================================================================
# small pure helpers
# =========================================================================================
def utc_str(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(TS_FMT)


def parse_utc(text):
    return datetime.strptime(text.strip(), TS_FMT).replace(tzinfo=timezone.utc).timestamp()


def _env_num(name, default, cast=int):
    try:
        return cast(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def jsonable(v):
    """numpy/ctypes scalars -> plain python so json.dumps never raises."""
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return str(v)


def clean_label(text):
    """Operator-chosen free text (e.g. 'XM Standard demo'): one line, bounded."""
    return " ".join(str(text or "").split())[:80]


def estimate_offset(tick_time_srv, now_epoch, max_age_s=OFFSET_MAX_AGE_S):
    """Broker-server offset from UTC in seconds (a whole number of hours), or None.

    tick.time is server time as epoch seconds, so  tick.time - now = offset - age  with a
    small age. Round to the hour; accept only when the residual (= tick age + clock skew) is
    small.

    CALLER MUST PASS A FRESH TICK ONLY. A tick that is exactly N hours old is indistinguishable
    from a fresh tick on a server N hours behind, so a stale feed (weekend close, the daily
    break) could silently move the offset. XmLogger therefore feeds this function only ticks
    whose time ADVANCED since the previous poll (a frozen tick is stale by definition) - on gold
    that is not an edge case, it is every weekend.
    """
    if not tick_time_srv:
        return None
    d = float(tick_time_srv) - float(now_epoch)
    off = int(round(d / 3600.0)) * 3600
    if abs(off) > MAX_OFFSET_H * 3600 or abs(d - off) > max_age_s:
        return None
    return off


def tick_age_s(tick_time_srv, offset_s, now_epoch):
    """Age of a tick in seconds, or None when the offset is not known."""
    if offset_s is None or not tick_time_srv:
        return None
    return float(now_epoch) - (float(tick_time_srv) - offset_s)


def decode_bits(value, table):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return [name for bit, name in sorted(table.items()) if v & bit]


def decode_enum(value, table):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return table.get(v, "?%d" % v)


def last_csv_row(path, fields):
    """Last well-formed row of a CSV without reading the whole file, or None."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    for ln in reversed([x for x in data.splitlines() if x.strip()]):
        try:
            parts = next(csv.reader([ln]))
        except (csv.Error, StopIteration):
            continue
        if len(parts) == len(fields) and parts != list(fields):
            return dict(zip(fields, parts))
    return None


class CsvAppender:
    """Append-only CSV: header on create, schema-drift protection, torn-line repair.

    * Opened with newline="" and lineterminator="\\n": the Wine (Windows) Python would
      otherwise translate to CRLF and the Linux readers would see a trailing \\r.
    * If the header on disk is not exactly `fields` the file is MOVED ASIDE and a fresh one
      started - appending misaligned rows is how trades.csv silently broke once.
    * If the last line has no newline (killed mid-write) a newline is added first so the
      torn row stays isolated and the next row is intact; readers skip malformed lines.
    """

    def __init__(self, path, fields, log=print):
        self.path, self.fields, self.log = path, list(fields), log
        self._ready = False

    def _prepare(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
            with open(self.path, "r", newline="", encoding="utf-8", errors="replace") as f:
                header = f.readline().rstrip("\r\n")
            if header.split(",") != self.fields:
                aside = "%s.old-%s" % (self.path, time.strftime("%Y%m%dT%H%M%S", time.gmtime()))
                os.replace(self.path, aside)
                self.log("mt5_quotes: WARNING schema drift in %s - moved to %s, starting a "
                         "fresh file" % (os.path.basename(self.path), os.path.basename(aside)))
            else:
                with open(self.path, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    last = f.read(1)
                if last != b"\n":
                    with open(self.path, "ab") as f:
                        f.write(b"\n")
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f, lineterminator="\n").writerow(self.fields)
        self._ready = True

    def append(self, rows):
        if not rows:
            return
        if (not self._ready or not os.path.exists(self.path)
                or os.path.getsize(self.path) == 0):
            self._ready = False
            self._prepare()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            for r in rows:
                w.writerow([r.get(k, "") for k in self.fields])
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass


def atomic_write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)          # atomic: readers (and git add) never see a partial file


# =========================================================================================
# contract-spec snapshot
# =========================================================================================
def _pick(obj, fields):
    return {k: (jsonable(getattr(obj, k, None)) if obj is not None else None) for k in fields}


def spec_hash(spec):
    """Stable hash of the parts of a snapshot that are contract facts (not live state)."""
    term = {k: v for k, v in (spec.get("terminal") or {}).items() if k not in TERMINAL_VOLATILE}
    core = {"symbol": spec.get("symbol"), "symbol_info": spec.get("symbol_info"),
            "account": spec.get("account"), "terminal": term}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def build_spec(mt5mod, symbol, label="", now=None):
    """Allow-listed, decoded contract snapshot. Never raises; missing pieces become None."""
    now = time.time() if now is None else now
    err = []

    def call(name, *args):
        fn = getattr(mt5mod, name, None)
        if fn is None:
            err.append("%s: not available" % name)
            return None
        try:
            return fn(*args)
        except Exception as e:                      # a failing probe must not kill the logger
            err.append("%s: %s" % (name, e))
            return None

    si = call("symbol_info", symbol)
    acct = call("account_info")
    term = call("terminal_info")
    tick = call("symbol_info_tick", symbol)

    sym = _pick(si, SYMBOL_FIELDS)
    spec = {
        "schema": SCHEMA_VERSION,
        "symbol": symbol,
        "captured_utc": utc_str(now),
        "label": clean_label(label),
        "symbol_info": sym,
        "spread_points_now": jsonable(getattr(si, "spread", None)) if si is not None else None,
        "account": _pick(acct, ACCOUNT_FIELDS),
        "terminal": _pick(term, TERMINAL_FIELDS),
    }
    spec["decoded"] = {
        "account_kind": decode_enum(spec["account"].get("trade_mode"), ACCOUNT_TRADE_MODE),
        "margin_mode": decode_enum(spec["account"].get("margin_mode"), ACCOUNT_MARGIN_MODE),
        "symbol_trade_mode": decode_enum(sym.get("trade_mode"), SYMBOL_TRADE_MODE),
        "execution_mode": decode_enum(sym.get("trade_exemode"), EXEMODE),
        # SYMBOL flag bits (FOK=1, IOC=2) are NOT the order enum (FOK=0, IOC=1, RETURN=2).
        "filling_allowed_flags": decode_bits(sym.get("filling_mode"), FILLING_BITS),
        "order_types_allowed": decode_bits(sym.get("order_mode"), ORDER_MODE_BITS),
        "expiration_allowed": decode_bits(sym.get("expiration_mode"), EXPIRATION_BITS),
        "calc_mode": decode_enum(sym.get("trade_calc_mode"), CALC_MODE),
        "swap_mode": decode_enum(sym.get("swap_mode"), SWAP_MODE),
        "swap_triple_day": decode_enum(sym.get("swap_rollover3days"), WEEKDAY),
    }

    probes = {}
    bid = jsonable(getattr(tick, "bid", None)) if tick is not None else None
    if bid:
        buy = getattr(mt5mod, "ORDER_TYPE_BUY", 0)
        # pure calculators (no order is created): P/L of 0.01 lot for a +$1 move is exactly $1.00
        # when the contract is 100 oz - i.e. the engine's "profit = price difference" arithmetic
        # (0.01 lot = 1 oz) equals the broker's. If this is not 1.0 every $ in the ledger is mis-scaled.
        probes["calc_profit_usd_0.01lot_plus_1usd"] = jsonable(
            call("order_calc_profit", buy, symbol, 0.01, bid, bid + 1.0))
        probes["calc_margin_usd_0.01lot"] = jsonable(call("order_calc_margin", buy, symbol, 0.01, bid))
        probes["price_used"] = bid
    spec["probes"] = probes
    if si is None:
        err.append("symbol_info returned None for %s" % symbol)
    if acct is None:
        err.append("account_info returned None")
    if err:
        spec["errors"] = err[:6]
    spec["hash"] = spec_hash(spec)
    return spec


# =========================================================================================
# quote window aggregation
# =========================================================================================
class QuoteWindow:
    """Accumulates the polls of one interval into a single CSV row."""

    def __init__(self, grid_epoch):
        self.grid = grid_epoch
        self.first = None            # (poll_epoch, bid, ask, age, offset): the point sample
        self.smin = None
        self.smax = None
        self.n_ok = 0
        self.n_none = 0              # the terminal returned no tick at all
        self.n_invalid = 0           # a tick came back but bid/ask were zero or crossed

    @property
    def n_bad(self):
        return self.n_none + self.n_invalid

    def add_ok(self, poll_epoch, bid, ask, age, offset):
        sp = ask - bid
        if self.first is None:
            self.first = (poll_epoch, bid, ask, age, offset)
        self.smin = sp if self.smin is None else min(self.smin, sp)
        self.smax = sp if self.smax is None else max(self.smax, sp)
        self.n_ok += 1

    def add_bad(self, kind):
        if kind == "bad":
            self.n_invalid += 1
        else:
            self.n_none += 1

    def row(self, digits, poll_s, stale_s=STALE_TICK_S):
        d = max(int(digits), 2)
        fmt = "%." + str(d) + "f"
        out = {"ts_utc": utc_str(self.grid), "n_ok": self.n_ok, "n_bad": self.n_bad}
        flags = []
        if self.first is None:
            flags.append("BADQUOTE" if self.n_invalid else "NOQUOTE")
            out.update(bid="", ask="", spread="", spread_min="", spread_max="",
                       tick_age_s="", srv_offset_s="")
        else:
            poll_epoch, bid, ask, age, offset = self.first
            out["bid"], out["ask"] = fmt % bid, fmt % ask
            out["spread"] = fmt % round(ask - bid, d)
            out["spread_min"] = fmt % round(self.smin, d)
            out["spread_max"] = fmt % round(self.smax, d)
            out["tick_age_s"] = "" if age is None else "%.1f" % age
            out["srv_offset_s"] = "" if offset is None else int(offset)
            if offset is None:
                flags.append("NOOFFSET")
            if age is not None and age > stale_s:
                flags.append("STALE")
            if poll_epoch - self.grid > poll_s + 1.5:
                flags.append("LATE")
            if self.n_invalid:
                flags.append("BADQUOTE")
        out["flags"] = ";".join(flags)
        return out


# =========================================================================================
# the logger
# =========================================================================================
class XmLogger:
    """All state and I/O lives here; the terminal module, the sleep function and the clock are
    injected, so the smoke test drives it with a fake terminal and a fake clock (no sleeping,
    no Wine)."""

    def __init__(self, mt5mod, symbol, out_dir, interval=30, poll=5, lag=LAG_S,
                 stale_s=STALE_TICK_S, label="", log=None, spec_every_s=SPEC_EVERY_S, sleep=None):
        self.mt5, self.symbol, self.out_dir = mt5mod, symbol, out_dir
        self.log = log or (lambda m: print(m, flush=True))
        self.sleep = sleep or time.sleep      # resolved now, not at import (patchable in tests)
        self.interval, self.poll, self.lag = int(interval), int(poll), float(lag)
        if self.poll < 1 or self.interval < self.poll or self.interval % self.poll:
            self.log("mt5_quotes: interval %s / poll %s are not compatible (poll must divide the "
                     "interval) - using 30 / 5" % (interval, poll))
            self.interval, self.poll = 30, 5
        self.stale_s = stale_s
        self.label, self.spec_every_s = clean_label(label), spec_every_s

        self.window = None
        self.started_at = None
        self.last_stamp = None          # newest quote-row grid epoch already written
        self.offset = None
        self._pending_offset = None     # (candidate, consecutive count) for a CHANGED offset
        self._prev_tick_time = None     # server time of the previous valid tick (freshness gate)
        self.digits = 2
        self.last_ok_poll = None
        self.last_reinit = -1e18
        self.next_spec_at = 0.0
        self.last_spec_hash = None
        self.next_heartbeat = 0.0
        self.last_spread = None
        self.rows_written = 0
        self._appenders = {}
        self._err_seen = {}

    # ---- plumbing ------------------------------------------------------------------
    def _err(self, key, msg, now):
        """Print an error at most once per ERR_LOG_EVERY_S per key."""
        if now - self._err_seen.get(key, -1e18) >= ERR_LOG_EVERY_S:
            self._err_seen[key] = now
            self.log("mt5_quotes: %s" % msg)

    def _appender(self, path, fields):
        a = self._appenders.get(path)
        if a is None:
            a = self._appenders[path] = CsvAppender(path, fields, log=self.log)
        return a

    def quotes_path(self, epoch):
        return os.path.join(self.out_dir, "%s%s.csv" % (
            QUOTES_PREFIX, datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")))

    def grid(self, now):
        """Window a poll at `now` belongs to; 0.5 s of slack for a timer that wakes early."""
        return int((now - self.lag + 0.5) // self.interval) * self.interval

    def next_poll_time(self, now):
        """Next instant on the poll grid (lag + k*poll) strictly after `now`."""
        return (math.floor((now - self.lag) / self.poll) + 1) * self.poll + self.lag

    def off_txt(self):
        return "unknown" if self.offset is None else "%+gh" % (self.offset / 3600.0)

    # ---- start-up ------------------------------------------------------------------
    def learn_digits(self):
        try:
            d = getattr(self.mt5.symbol_info(self.symbol), "digits", None)
        except Exception:
            d = None
        if isinstance(d, int) and 0 <= d <= 8:
            self.digits = d

    def resume(self, now):
        """Resume point: a restart never duplicates a row."""
        last_q = last_csv_row(self.quotes_path(now), QUOTE_FIELDS)
        if last_q:
            try:
                self.last_stamp = parse_utc(last_q["ts_utc"])
            except ValueError:
                pass

    def learn_offset(self, now, tries=10, clock=None):
        """Poll until one fresh tick yields the server offset (or give up after `tries`).
        Needs two polls (a tick that ADVANCED), so it sleeps between them. With the market
        closed no tick ever advances: the offset stays unknown until it reopens and the rows
        carry NOOFFSET meanwhile."""
        clock = clock or time.time
        for _ in range(tries):
            self._poll_tick(now)
            if self.offset is not None:
                return True
            self.sleep(1.0)
            now = clock()
        return False

    def start(self, now, clock=None):
        os.makedirs(self.out_dir, exist_ok=True)
        self.started_at = now
        self.learn_digits()
        self.resume(now)
        self.learn_offset(now, clock=clock)
        spec = self.snapshot_spec(now, force=True) or {}
        self.log("mt5_quotes: %s | account %s | server offset %s | quotes every %ds (poll %ds) -> %s"
                 " | resume: last quote %s" % (
                     self.symbol, (spec.get("decoded") or {}).get("account_kind") or "?",
                     self.off_txt(), self.interval, self.poll, self.out_dir,
                     utc_str(self.last_stamp) if self.last_stamp else "none"))

    # ---- tick handling -------------------------------------------------------------
    def _poll_tick(self, now):
        """-> ('ok', bid, ask, tick_time) | ('bad',) | ('none',). Updates the offset."""
        try:
            t = self.mt5.symbol_info_tick(self.symbol)
        except Exception as e:
            self._err("tick", "symbol_info_tick failed: %s" % e, now)
            return ("none",)
        if t is None:
            return ("none",)
        try:
            bid, ask, tt = float(t.bid), float(t.ask), int(t.time)
        except (AttributeError, TypeError, ValueError):
            return ("bad",)
        if not (bid > 0 and ask > 0 and ask >= bid):
            return ("bad",)
        fresh = self._prev_tick_time is not None and tt != self._prev_tick_time
        self._prev_tick_time = tt
        if fresh:                       # a frozen tick is stale: it must not move the offset
            self._note_offset(estimate_offset(tt, now))
        return ("ok", bid, ask, tt)

    def _note_offset(self, cand):
        """First estimate is taken at once; a different one only after OFFSET_CONFIRM
        consecutive agreeing fresh ticks (one glitchy tick must not flip every row)."""
        if cand is None:
            return
        if self.offset is None:
            self.offset = cand
            return
        if cand == self.offset:
            self._pending_offset = None
            return
        n = self._pending_offset[1] + 1 if (self._pending_offset and self._pending_offset[0] == cand) else 1
        self._pending_offset = (cand, n)
        if n >= OFFSET_CONFIRM:
            self.log("mt5_quotes: server offset changed %s -> %+gh (DST?)" % (self.off_txt(), cand / 3600.0))
            self.offset, self._pending_offset = cand, None

    # ---- one poll ------------------------------------------------------------------
    def step(self, now):
        """One poll at wall-clock `now`. Returns the poll outcome tuple (for tests)."""
        g = self.grid(now)
        if self.window is None or self.window.grid != g:
            self.flush_window(now)
            self.window = QuoteWindow(g)
        res = self._poll_tick(now)
        if res[0] == "ok":
            _, bid, ask, tt = res
            self.window.add_ok(now, bid, ask, tick_age_s(tt, self.offset, now), self.offset)
            self.last_ok_poll = now
            self.last_spread = ask - bid
        else:
            self.window.add_bad(res[0])
        self._watchdog(now)
        if now >= self.next_spec_at:
            self.snapshot_spec(now)
        if now >= self.next_heartbeat:
            self.next_heartbeat = now + HEARTBEAT_S
            self.log("mt5_quotes: %s UTC | spread %s | rows written %d | offset %s" % (
                utc_str(now)[:16], "n/a" if self.last_spread is None else "$%.2f" % self.last_spread,
                self.rows_written, self.off_txt()))
        return res

    def _watchdog(self, now):
        ref = self.last_ok_poll if self.last_ok_poll is not None else (
            self.started_at if self.started_at is not None else now)
        quiet = now - ref
        if quiet > REINIT_AFTER_S and now - self.last_reinit > REINIT_AFTER_S:
            self.last_reinit = now
            self._err("reinit", "no valid quote for %.0f s - re-initializing the MT5 link" % quiet, now)
            try:
                self.mt5.shutdown()
                if self.mt5.initialize():
                    self.mt5.symbol_select(self.symbol, True)
            except Exception as e:
                self._err("reinit2", "re-initialize failed: %s" % e, now)
        if quiet > DEAD_AFTER_S:
            self.flush_window(now)
            self.log("mt5_quotes: no valid quote for %.0f s - exiting for a clean restart" % quiet)
            raise SystemExit(2)

    # ---- quote rows ----------------------------------------------------------------
    def flush_window(self, now):
        """Write the open window as one row (if it has any poll and is newer than the last)."""
        w, self.window = self.window, None
        if w is None or (w.n_ok == 0 and w.n_bad == 0):
            return None
        if self.last_stamp is not None and w.grid <= self.last_stamp:
            return None     # clock stepped back, or a restart inside the same window: no duplicate
        row = w.row(self.digits, self.poll, self.stale_s)
        try:
            self._appender(self.quotes_path(w.grid), QUOTE_FIELDS).append([row])
        except OSError as e:
            self._err("write-quote", "cannot write quote row: %s" % e, now)
            return None
        self.last_stamp = w.grid
        self.rows_written += 1
        return row

    # ---- contract spec -------------------------------------------------------------
    def snapshot_spec(self, now, force=False):
        if not force and now < self.next_spec_at:
            return None
        self.next_spec_at = now + self.spec_every_s
        spec = build_spec(self.mt5, self.symbol, self.label, now)
        prev = self.last_spec_hash if self.last_spec_hash is not None else self._history_last_hash()
        try:
            atomic_write_text(os.path.join(self.out_dir, SPEC_FILE),
                              json.dumps(spec, indent=2, sort_keys=True) + "\n")
            if spec["hash"] != prev:
                with open(os.path.join(self.out_dir, SPEC_HISTORY_FILE), "a",
                          newline="", encoding="utf-8") as f:
                    f.write(json.dumps(spec, sort_keys=True, separators=(",", ":")) + "\n")
                dec = spec["decoded"]
                self.log("mt5_quotes: contract spec %s (hash %s): %s, %s execution, filling %s, "
                         "stops level %s" % ("recorded" if prev is None else "CHANGED", spec["hash"],
                                             dec.get("account_kind"), dec.get("execution_mode"),
                                             dec.get("filling_allowed_flags"),
                                             spec["symbol_info"].get("trade_stops_level")))
        except OSError as e:
            self._err("write-spec", "cannot write the spec snapshot: %s" % e, now)
        self.last_spec_hash = spec["hash"]
        return spec

    def _history_last_hash(self):
        try:
            with open(os.path.join(self.out_dir, SPEC_HISTORY_FILE), "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = [x for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
            return json.loads(lines[-1]).get("hash") if lines else None
        except Exception:
            return None

    # ---- run -----------------------------------------------------------------------
    def run_forever(self, clock=None):
        clock = clock or time.time
        self.start(clock(), clock=clock)
        target = 0.0
        try:
            while True:
                now = clock()
                target = self.next_poll_time(max(now, target))   # never poll the same slot twice
                if target > now:
                    self.sleep(target - now)
                try:
                    self.step(clock())
                except SystemExit:
                    raise
                except Exception as e:                    # never let one bad poll end the clock
                    self._err("step", "poll error: %s (continuing)" % e, clock())
        except KeyboardInterrupt:
            pass
        finally:
            self.flush_window(clock())


# =========================================================================================
# CLI
# =========================================================================================
def _connect(symbol, m):
    if m is None:
        print("mt5_quotes: MetaTrader5 package missing - install it in the WINE python:\n"
              "  wine C:/Python312/python.exe -m pip install MetaTrader5", flush=True)
        sys.exit(1)
    if not m.initialize():
        print("mt5_quotes: MT5 initialize failed: %s (is the terminal running and logged in, "
              "in this prefix?)" % (m.last_error(),), flush=True)
        sys.exit(1)
    if not m.symbol_select(symbol, True):
        print("mt5_quotes: symbol_select(%s) failed: %s (check the exact symbol name in Market "
              "Watch, e.g. GOLD vs GOLDm)" % (symbol, m.last_error()), flush=True)
        sys.exit(1)


def main(argv=None, mt5mod=None, clock=None, sleep=None):
    """CLI entry. `mt5mod`, `clock` and `sleep` are injectable so the smoke test can drive every
    mode (--spec, --once) against a fake terminal without patching globals."""
    ap = argparse.ArgumentParser(description="XM quote + contract-spec logger for GOLD (read-only)")
    ap.add_argument("--spec", action="store_true", help="print the contract-spec snapshot; write nothing")
    ap.add_argument("--once", action="store_true", help="one cycle, then exit")
    ap.add_argument("--dir", default=os.environ.get("MT5_QUOTES_DIR", DEFAULT_DIR))
    a = ap.parse_args(argv)

    m = mt5mod if mt5mod is not None else mt5
    clock = clock or time.time
    symbol = os.environ.get("MT5_QUOTES_SYMBOL", DEFAULT_SYMBOL)
    label = os.environ.get("MT5_QUOTES_LABEL", "")
    _connect(symbol, m)
    try:
        if a.spec:
            print(json.dumps(build_spec(m, symbol, label, clock()), indent=2, sort_keys=True))
            return 0
        lg = XmLogger(m, symbol, a.dir,
                      interval=_env_num("MT5_QUOTES_INTERVAL", 30), poll=_env_num("MT5_QUOTES_POLL", 5),
                      label=label, sleep=sleep)
        if a.once:
            lg.start(clock(), clock=clock)
            lg.step(clock())
            row = lg.flush_window(clock())
            print("mt5_quotes --once: quote row = %s" % (row,), flush=True)
            return 0
        try:
            lg.run_forever(clock=clock)
        finally:
            print("mt5_quotes: stopped", flush=True)
        return 0
    finally:
        m.shutdown()


if __name__ == "__main__":
    sys.exit(main())
