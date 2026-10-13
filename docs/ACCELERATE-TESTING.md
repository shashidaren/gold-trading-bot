# Accelerating testing: the large-N history path

*Added 2026-10-13. Port of the idea in bitcoin-trading-bot PR #18 (`history_to_log` / `backtest` /
`ACCELERATE-TESTING`), built for gold's M1 engine. Context:
[`ANALYSIS-2026-10-13-btc-port-assessment.md`](ANALYSIS-2026-10-13-btc-port-assessment.md) item 8.*

## 1. The problem, and what this buys

Live evidence arrives at about 100 trades a week. 575 trades in 5.5 weeks sounds like a lot, but the
structural-stop era is **n = 78** and is only judged at about n ≈ 130 (2026-10-19), and every idea after it
costs another 2–3 weeks of forward testing to reach n ≈ 100–150. The terminal keeps M1 history, and the engine
already consumes that same terminal's closed M1 bars (`mt5_feed.py` reads `copy_rates_from_pos(..., M1, 1, 1)`),
so today's rules can be **replayed** over months the live bot never saw.

| | live ledger | this path |
|---|---|---|
| span | 5.5 weeks (since 2026-09-04) | up to `maxbars` M1 bars: the default 100,000 ≈ **14.5 weeks** (the logger's spec snapshot records the terminal's `maxbars`; raising "Max bars in chart" in the terminal options and re-dumping reaches further, if the broker keeps it) |
| out-of-sample for the rules | none (everything was tuned on it) | **everything before 2026-09-04**, the first live trade |
| regimes | one | two or three more months of them |
| authority | **final** | a *sieve*: a hypothesis generator |

**What it does not do.** It does not replace the forward test (HANDOFF §8: broker history is not the live feed:
spreads, gaps, the exact cascade), it moves no parameter, and **nothing found here changes anything inside the
struct-stop window** (open until 2026-10-19 21:00 UTC or n = 150). A promising row is a reason to pre-register a
forward test, never a reason to ship.

## 2. The three steps (on the box)

```bash
# 1. dump M1 history through the same Wine terminal the feed uses (read-only; writes only the CSV)
export WINEPREFIX=/root/.mt5
xvfb-run --auto-servernum wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_history_dump.py \
    --bars 100000 --timeframe M1 --out Z:/opt/gold/mt5_history.csv

# 2. convert + PROVE the time basis against the live log (refuses if it cannot)
python3 tools/history_to_log.py /opt/gold/mt5_history.csv --out /opt/gold/history_utc.csv

# 3. replay today's rules over it (no ledger, no calibration, nothing written)
python3 tools/strategy_lab.py --bars /opt/gold/history_utc.csv
```

`history_*.csv` and `mt5_history*.csv` are git-ignored: these files are large and derived, and **must never go
into `xm_data/`** (autosync commits that directory). `--check-only` runs step 2 without writing.

## 3. Why step 2 exists: the time trap

`mt5_history_dump.py` writes MT5's bar times as they come, i.e. **broker-server time** (XM: UTC+3 in summer,
UTC+2 in winter), **labelled as UTC**, stamped at the bar's **open**. `forward_test_log.csv` is real UTC stamped when
the bar **closes**. Feeding the raw dump to anything UTC-aware (the blackout windows, the Asia/London/NY bands, the
UTC day of the daily-loss breaker) is silently wrong by hours, and the last row is the bar still forming. So
`strategy_lab --bars` **refuses a raw dump** (it recognises the `TickVolume`/`Spread` columns) and points here.

### How the converter proves the clock, instead of assuming it

From 2026-09-10 the log is fed by the MT5 sidecar, i.e. by the *same terminal's closed M1 bars*, so it is an exact,
UTC-stamped copy of part of the history (before that it came from Twelve Data, a different vendor, and is never used
as proof; `--overlap-from` moves the boundary). For every candidate whole-hour offset from −12 h to +14 h the tool
matches history to log **minute by minute on all four of open/high/low/close**, **per UTC day**, and requires:

* a day votes only with ≥ 200 comparable bars and a winner with at least twice the runner-up's matches (a flat or
  thin tape votes nothing: it cannot prove a clock);
* the days that voted must be explained ≥ 90 % (`--min-match`) by their winning offsets;
* the chosen DST rule must reproduce the observed offsets on ≥ 99 % of those days.

If anything fails it prints **why** and writes nothing (exit 1). It also drops the dump's last (still-forming) row,
writes UTC with `Timestamp` = bar close (`open + 60 s`) and the price text verbatim, and never overwrites
`forward_test_log.csv`.

| it says | meaning / what to do |
|---|---|
| `offset +3h : 100.0% exact OHLC match` | what a good run looks like |
| `REFUSED: the winning offset(s) explain only 62% …` | the history is not this symbol/terminal, or its bars differ from the live feed. Look at the three candidate offsets printed above it |
| `REFUSED: … share NO minute at any offset` | the pull does not reach the log's period (the dump takes the **last** N bars; the log must overlap its recent end) |
| `REFUSED: the overlap says +2h but the EU rule … predicts a different offset` | the server is not on XM's documented clock. If it is a fixed offset, `--dst none`; if New York time, `--dst us` |
| `REFUSED: no UTC day … has a clear winner` | the overlap is too thin or too flat to prove anything; pull a longer, more recent history |
| `already looks like a converted/log-format file` | you gave it a UTC file; converting again would shift it a second time |
| `UNVALIDATED` | you used `--no-validate`: the clock is what you asserted, not what was proved |

**What was and was not verified here.** There is no MT5 terminal in the development sandbox, so the converter was
exercised against a server-time rendering of the *real* MT5-era log (29,912 bars recovered with 100.0 % exact match;
every wrong offset scored 0.0 %) and against synthetic tapes covering summer, a wrong-offset server, an EU and a US
DST change inside the overlap, a transition neither rule explains, flat tapes and corrupt bars (smoke Scenario S).
**The first run on the box is the real validation**: it prints the actual match rate against a real dump. Expect
~100 %; anything under 90 % is refused rather than guessed.

## 4. Daylight saving (the 2026-10-25 change)

* **Right now it does not matter.** Anything pulled between 2026-03-29 and 2026-10-25 lies in one +3 h regime under
  *both* the EU and the US rule, so the conversion is rule-independent and the report says so.
* **After Sunday 2026-10-25** a pull will span the change. The overlap with the log is then enough to *observe* it:
  the per-day offsets read `+3h … , +2h …`, and the data picks the rule (EU or US) that explains them; if neither
  does, it refuses instead of guessing. Bars *before* the overlap are converted by the rule, and the tool flags
  any such crossing as `from the RULE ONLY - nothing in the overlap confirms it yet` until the log itself contains
  a transition. `tools/xm_quote_report.py` section 4 (the quote logger's observed offsets,
  [`XM-LOGGER.md`](XM-LOGGER.md)) is the independent check, and `tools/broker_time.py` is the single place the rule lives.
* The change happens on a Sunday while gold is shut, so no bar is ambiguous.

## 5. Reading the replay

`strategy_lab --bars FILE` (add `--only a,b`, `--cost X`, `--ratchet const|era|off`) prints:

* **H1 data** — gaps (scheduled daily breaks / weekends / *unscheduled holes*) and how much of the file lies before
  2026-09-04.
* **H2 windows** — ALL, OOS (< 2026-09-04) and IN-SAMPLE (≥ 2026-09-04), baseline and structstop, each a full
  independent cascade restarted at the window start, with the structstop − baseline delta.
* **H3 months** — each month an independent cascade (partial months are small-n; never read one alone).
* **H4 cost sensitivity** — R/trade and $/trade at $0 / 0.15 / 0.20 / 0.35 per side.

`--ratchet const` (default) applies today's 0.75R break-even ratchet to every bar; `era` follows the live schedule
(none before 2026-09-10 12:34); `off` disables it. The live-era replay is untouched by all of this: without `--bars`
every output is byte-identical to before (checked on six invocations when this was added).

**A calibration to keep in mind.** On the live MT5-era log, `structstop` replayed at zero cost gives **+0.005 R/trade**;
the live struct-stop era's *gross* result is **+0.007 R/trade** (n = 78). They cover different windows, but the
replay is not wildly more generous than reality, which is the property a sieve needs. The same replay at the
assumed $0.20/side is **−0.068 R/trade**: the cost, not the geometry, is the story.

**Discipline.**

1. Compare rows, not absolute dollars; use the Wilson interval printed with each decisive win rate.
2. OOS is out-of-sample for the *rules*, not for the *idea*: a hypothesis found by browsing these tables has been
   tested on this data once already. Pre-register it (bar, n, window) in HANDOFF §6 and forward-test it.
3. The flat per-side cost understates Asia/rollover/news; `xm_quote_report.py` measures it ([`XM-LOGGER.md`](XM-LOGGER.md)).
4. Intra-bar ordering is unknowable from OHLC (the engine's convention is arm-before-stop, stop-before-target):
   every row shares that bias, so a looser stop or ratchet always looks better here than it will live.
5. The live log has holes (feed stalls) that history fills, so replayed trade streams are not the live ones.

## 6. Troubleshooting

| symptom | fix |
|---|---|
| `copy_rates_from_pos failed` / fewer bars than asked | the terminal's *Max bars in chart* or the broker's history is the cap; try a smaller `--bars`, or raise the option and let the terminal sync |
| converter: `no MT5-era rows` | run it on a checkout whose `forward_test_log.csv` is current (autosync keeps `/opt/gold` current) |
| `--bars: only N usable bars` | below ~1,000 bars the EMA200/ATR warm-up dominates; pull more |
| OOS section absent | the file has no bar before 2026-09-04; the banner says so |
