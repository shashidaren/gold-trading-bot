# XM quote + contract-spec logger (GOLD)

*Added 2026-10-13. Port of bitcoin-trading-bot PR #10 (`tools/mt5_quotes.py`, `tools/xm_quote_report.py`,
`deploy/mt5quotes.service`), minus the shadow candles. Why it exists:
[`ANALYSIS-2026-10-13-btc-port-assessment.md`](ANALYSIS-2026-10-13-btc-port-assessment.md) item 9.*

## 1. What it is, in one paragraph

A read-only sidecar next to `mt5feed`. Every 30 s it writes one row with the XM `GOLD` bid/ask/spread (plus a
5 s min/max envelope) and the broker-server clock offset, and every 6 h it snapshots the contract spec
(execution and filling modes, stops level, contract size, swap, demo vs real). It **changes nothing**: the
engine, `DATA_SOURCE`, the forward-test sample and every parameter are untouched, and it never sends, checks or
lists an order. `tools/xm_quote_report.py` turns the rows into the numbers the cost model has been guessing at.

## 2. Why gold needs it

Every costed number in this repo uses a **flat, assumed** $0.20 per side:
`strategy_lab.py --cost 0.20`, `win_rate_report.py --spread 0.40`, the HANDOFF snapshot's
`net_pnl_usd_at_cost`. The paper engine itself books no spread. That matters here more than anywhere:

| fact (data collection 226, snapshot in HANDOFF) | value |
|---|---|
| closed trades | 575 (110 W / 248 L / **215 BE** / 2 TIME) |
| gross P/L | −$319.51 |
| at the assumed $0.20/side | **−$549.51** |

215 scratches pay a spread each and earn nothing, so the cost assumption moves the verdict by $230 and nobody
has ever measured it. Real spreads also widen in Asia/rollover and around news (the engine already blacks out
21:45–22:30 for "spread spike"), exactly when a flat number is wrong. The logger measures the real figure, by
session and by blackout window, and at the moment each ledger trade entered and exited.

It also answers two questions the paper engine cannot: **is the engine's dollar the broker's dollar?** (the
`order_calc_profit` probe: 0.01 lot × a $1 move must be exactly $1.00) and **what would a live account be
allowed to do?** (execution mode, filling flags, stops level, minimum lot, swap).

## 3. Install (once, on the box)

The terminal must already be running and logged in, in the same Wine prefix as `mt5feed` (several Python clients
can attach to one terminal; the feed is unaffected). Nothing here needs a login or password.

```bash
export WINEPREFIX=/root/.mt5
cd /opt/gold            # autosync keeps this on main; the files below arrive with the PR

# 1. pre-flight: prints the contract spec as JSON and writes NOTHING
xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_quotes.py --spec
#    expect: "account_kind": "DEMO" (or REAL), "symbol_info"."trade_contract_size": 100.0,
#            "probes"."calc_profit_usd_0.01lot_plus_1usd": 1.0
#    "MetaTrader5 package missing"  -> wine C:/Python312/python.exe -m pip install MetaTrader5
#    "symbol_select(GOLD) failed"   -> the symbol is named differently in Market Watch (GOLD vs GOLDm ...);
#                                      set Environment=MT5_QUOTES_SYMBOL=<name> in the unit

# 2. one full cycle: learn the offset, record the spec, write one quote row, exit
xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_quotes.py --once
#    expect, in order: "contract spec recorded" ... "server offset +3h" ... "quote row = {...}"
#    (outside market hours: "server offset unknown" and a STALE row is NORMAL - section 5)

# 3. install as a service. NOTE the -gold suffix: BTC's logger on a shared host is mt5quotes-btc
sudo cp deploy/mt5quotes.service /etc/systemd/system/mt5quotes-gold.service
#    optional: uncomment Environment=MT5_QUOTES_LABEL=XM Standard demo   (MT5 does not expose the account tier)
sudo systemctl daemon-reload
sudo systemctl enable --now mt5quotes-gold
journalctl -u mt5quotes-gold -f        # a status line per hour; "contract spec recorded" at start
```

**Do it before Sunday 2026-10-25.** XM's server clock changes that day (section 6) and the logger's offset column
will be the first real evidence of how this particular terminal behaves.

Uninstall is `systemctl disable --now mt5quotes-gold`; the data stays, and nothing else depends on it.

## 4. What it writes (`/opt/gold/xm_data/`, committed by autosync)

`quotes-YYYY-MM-DD.csv` — UTC day files, one row per 30 s:

| column | meaning |
|---|---|
| `ts_utc` | window start on the box clock, aligned to the interval (UTC) |
| `bid`, `ask` | the **point sample**: the first valid quote of the window (~1 s after the boundary) |
| `spread` | `ask − bid` of the point sample, in $ per oz. × 0.01 lot × 100 oz = **$ per trade** (a factor of 1.00) |
| `spread_min`, `spread_max` | envelope over every 5 s poll in the window, so a spike between rows is not invisible |
| `n_ok`, `n_bad` | valid / invalid polls in the window (6 when healthy) |
| `tick_age_s` | age of the sample's tick when polled; large = a frozen feed (closed market) |
| `srv_offset_s` | broker-server clock minus UTC, in seconds, **learned from fresh ticks** (10800 = +3 h) |
| `flags` | `STALE` frozen tick · `NOQUOTE` terminal returned nothing · `BADQUOTE` zero or crossed price · `NOOFFSET` offset not yet known · `LATE` sample not at the boundary |

`symbol_spec.json` is the latest contract snapshot (allow-listed and decoded); `symbol_spec_history.jsonl` gets
one line each time it **changes** (swap, stops level, contract size...). About 66 bytes a row: **~186 KB per
day, ~5.7 MB a month raw** (git stores it compressed, roughly a seventh of that). If the repo size ever
matters, `MT5_QUOTES_INTERVAL=60` halves it; old day files can be moved to `archive/` once analysed.

## 5. Gold closes: STALE is not an outage

Unlike crypto, gold is shut every weekend and for a daily break (XM server 23:55–01:05, about 20:55–22:05 UTC
in summer, an hour later in winter). The terminal keeps answering with its last tick, so the logger **keeps
writing rows**, flagged `STALE` with a growing `tick_age_s`. That gives the report a clean split:

* **Logger outage** = a hole in the rows (a gap > 5 min). The process was down or the box was suspended.
* **Closed market** = rows continue, all `STALE`, inside the scheduled windows (padded 20:55–23:10 UTC and Fri
  20:55 → Sun 23:10 so DST never turns a scheduled break into an "incident").
* **Feed stall** = `STALE` rows ≥ 10 min *outside* those windows: an exchange holiday or news halt, a frozen
  terminal, a dropped broker connection. One is noise; a repeat is worth a look.

Only STALE rows are excluded from spread statistics. A frozen tick can never move the offset either: the
logger learns it only from ticks whose time *advanced* (a tick that is exactly 3 h old is otherwise
indistinguishable from a fresh tick on a server 3 h behind, and a weekend would do that every week).

## 6. Server time and the DST change on 2026-10-25

MT5 `time` fields are **broker-server time encoded as epoch seconds**, not UTC. XM's server runs UTC+2 in winter
and UTC+3 in summer on the EU rule (last Sunday of March/October, 01:00 UTC); the next change is **Sunday
2026-10-25**. The consequences for this repo:

* The live engine is **unaffected**: log rows use the wall clock; the feed's candle `ts` is only a dedup
  watermark (do **not** "fix" it to UTC, see the assessment doc: it would make the engine drop ~3 h of candles).
* `mt5_history_dump.py` labels server time as UTC (+3 h now), which matters for the large-N history path
  (`docs/ACCELERATE-TESTING.md`), and `tools/history_to_log.py` needs the right rule to fix it.
* The logger records the offset on **every row**. `xm_quote_report.py` section 4 compares what it observed with
  the EU rule and the US rule (`tools/broker_time.py`). A rule is **confirmed only after a transition is
  observed** and exactly one rule explains every fresh row; until then the verdict reads `UNVERIFIED` and names
  the dates that will settle it (EU: 2026-10-25 01:00 UTC → +2 h; US: 2026-11-01 06:00 UTC), because between those
  two dates the rules disagree.

## 7. Reading it

```bash
python3 tools/xm_quote_report.py            # the five sections below
python3 tools/xm_quote_report.py --days 14  # only the newest 14 UTC days
python3 tools/xm_quote_report.py --quiet    # one line (what autosync's digest shows)
```

1. **LOGGER** — complete days and weekends against the sample target (≥ 14 complete days incl. 2 weekends),
   logger outages, scheduled closures vs feed stalls, flags, offsets seen.
2. **SPREAD** — usable rows only: by session (ASIA 23–07, LONDON 07–12, NY 12–21, ROLLOVER 21–23 UTC), the weekly
   open, the engine's own blackout windows, by UTC hour, the share above the assumed cost and above 5/10/20 % of
   the median 1R. All in $/oz and in $ per trade at 0.01 lot.
3. **COST** — each ledger trade joined to the usable quote within 75 s of its entry and of its exit:
   measured round trip vs the assumed $0.40, and the same trades gross / net at $0.40 / net at the measured
   cost. The paper P/L is bid-to-bid, so a round trip really pays **one** spread (a BUY at entry, a SELL at exit);
   the mean of the entry and exit spread is used. It prints the exact flags to re-cost the ledger.
4. **SERVER TIME** — offsets observed and the DST verdict (above).
5. **SPEC** — contract facts and the assumption checks (100 oz contract, 0.01 min lot, $1.00 probe).

A digest line looks like `📡 xm logger: OK | 6/14 complete days, 0/2 weekends | rows 17210, outage 0.1 h | spread median
$0.25 p95 $0.41 /oz ($0.25/trade median)`, with ` | market closed or feed frozen` appended while gold is shut.
`STALE (newest row 3.1 h old - is mt5quotes-gold running?)` means the **logger** is down (the newest row is older
than 15 min) and is the only case that also raises a ⚠️ line in the digest.

## 8. What the numbers may and may not be used for

* **Measure, don't tune.** Spread-only cost is a *lower bound* on the real round trip (slippage and commission
  are not visible in quotes). Nothing here changes a gate, a parameter or an exit.
* **Inside the struct-stop window (open until 2026-10-19 21:00 UTC or n = 150) nothing about strategy moves**,
  and this logger does not ask it to. It only improves the *costing* of the existing evidence.
* **Re-costing is allowed and cheap**, because the tools take it as a flag: when the sample target is met,
  `win_rate_report.py --spread <median>` and `strategy_lab.py --table --cost <median/2>` show whether the verdict
  survives the measured cost. Section 3 prints both commands with the number filled in. Whether to *adopt* the
  measured figure as the repo-wide constant is a decision for HANDOFF §6, with the evidence attached.
* **Demo vs live.** The snapshot says `DEMO` or `REAL`. XM demo normally mirrors live pricing, but any go-live
  cost conclusion has to be confirmed on the account that will actually trade.
* **Spread-aware gating is out of scope.** If section 2 shows a window where spreads are routinely multiples of
  the median, that is a *hypothesis* to pre-register and test in `strategy_lab` after the window closes, not a
  rule to add.

## 9. Safety and privacy (enforced by `tools/smoke_test.py` Scenario Q)

* **Read-only by construction.** The module uses `symbol_select`, `symbol_info`, `symbol_info_tick`,
  `account_info`, `terminal_info` and the pure calculators `order_calc_profit` / `order_calc_margin`. The smoke
  test walks the file's AST and fails if any trading API name appears (`order_send`, `positions_get`,
  `history_deals_get`, `login`...), and drives the logger against a fake terminal that records any such call.
* **The repo is public and autosync commits `xm_data/`.** `account_info()` carries login, name, balance and
  server; `terminal_info()` carries Windows user paths. The logger **never dumps those objects**: it copies
  an explicit allow-list of non-identifying fields and prints no login. The smoke test plants a login, a name, a
  balance, a server name and a Windows path in the fake terminal and fails if any of them reaches a file.
* **It cannot hurt a deploy.** The autosync phase runs after the deploy decision, never assigns a deploy
  variable, and a failing or missing report only changes one digest line.
* **It cannot stop silently without the digest saying so**, and it cannot spin: 60 s without a valid quote
  re-initialises the MT5 link, 15 min makes it exit 2 so systemd restarts a clean process. A closed market does
  not count (frozen ticks are still answered).
* Writes are LF-only (the Wine Python would otherwise write CRLF), a drifted header moves the file aside rather
  than appending misaligned rows, and a torn last line is isolated.

## 10. Troubleshooting

| symptom | meaning / fix |
|---|---|
| digest: `xm logger: not collecting yet` | `xm_data/` has no quote rows. Install (section 3) or check `systemctl status mt5quotes-gold` |
| digest: `STALE (newest row … old …)` + ⚠️ | the **logger** stopped. `journalctl -u mt5quotes-gold -n 50`; the terminal being logged out/restarted is the usual cause; `Restart=always` retries every 10 s |
| every row `STALE` for many hours on a weekday | not the logger: the **feed** is frozen (terminal disconnected). `mt5feed` and the engine's 🛑 line will say the same |
| `NOOFFSET` rows at start-up | the market was shut, so no tick advanced; the offset is learned within a minute of the reopen |
| `contract spec CHANGED` in the journal | XM changed something (swap, stops level, contract size). The new snapshot is the last line of `symbol_spec_history.jsonl`; diff the last two |
| `server offset changed +3h -> +2h (DST?)` | the expected autumn change (Sun 2026-10-25). Report section 4 will turn the verdict to EU once a full transition is in the data |
| report says `MISMATCH` on the $1.00 probe | **stop trusting dollar figures** until explained: the engine's P/L unit differs from the broker's contract |
