# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Gold trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

Keep it current: every session that changes code, params, or conclusions must
update §1, §4/§5 and §6 before it ends (see §11 "How to keep this file
honest"). §11 also carries the **Session & Push Protocol** — push every commit
immediately and keep the session PR open until the user signs off. Follow it
from the first commit.

### Start here (30 seconds)

1. Read **§1** (stance + numbers) and **Definitions** below it.
2. Run integrity + era report:
   ```bash
   python3 tools/check_data.py          # expect "0 fail"
   python3 tools/win_rate_report.py
   ```
3. **Next formal work:** max-hold re-review (~2026-10-05 or n≈200 max-hold-era trades).
4. Never change `BE_TRIGGER_R` / `MAX_HOLD_MINUTES` / ATR bounds / blackouts without a
   pre-registered bar + REVIEW/ANALYSIS doc.

### Command cheat sheet

| Goal | Command |
|------|---------|
| Integrity first | `python3 tools/check_data.py` |
| Era / WR / ratchet grid | `python3 tools/win_rate_report.py` |
| Blocked-signal phantoms | `python3 tools/phantom_trades.py` |
| Gate replay | `python3 tools/validate_gates.py` |
| Loser features | `python3 tools/analyze_losers.py` |
| Engine regression | `python3 tools/smoke_test.py` |
| Force autosync now | `sudo /opt/gold/tools/autosync.sh` |
| Live state | `cat /opt/gold/status.json` |
| Engine service | `systemctl status goldbot` (or unit that runs `engine.py` under `/opt/gold`) |
| Autosync log | `tail -80 /var/log/gold_autosync.log` |

### Do not

- Pool **decisive WR** across the 09-15 ratchet change without naming the era.
- Key BE reconstruction only on `Exit_Reason == "BE"` — use **geometry**
  (`Stop_Loss == Entry_Price`) + `ATR_At_Entry`.
- Hand-edit code on `/opt/gold` (autosync will refuse deploy).
- Ship param/strategy changes without a pre-registered bar + REVIEW/ANALYSIS doc.
- Treat the bot as income, or go LIVE without broker-side BE + a costs model.

### Env (names only — never commit values)

`/opt/gold/.env`:
- `DATA_SOURCE` = `MT5` (live) or `TWELVEDATA`
- `TWELVE_DATA_API_KEY`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
- `MT5_FEED_FILE` (optional; default `/opt/gold/mt5_last_candle.json`)

### Era timeline (UTC)

| When | What |
|------|------|
| 2026-09-10 ~12:34 | BE ratchet 0.30R + London BUY-only + trend-side daily breaker (PR #7) |
| 2026-09-15 ~06:00 | `BE_TRIGGER_R` → **0.75** (PR #9 deploy) |
| 2026-09-17 | Falsification bar tripped (−$0.40/trade at n≥60) |
| 2026-09-21 ~06:00 | `MAX_HOLD_MINUTES=240` live (PR #15); **no era counter reset** |

## 1. Where things stand (as of 2026-09-25)

- Repo: `shashidaren/gold-trading-bot`, default branch `main` (no open session PR;
  prior arena work branches exist but are historical).
- **PR #15 MERGED** (2026-09-21 04:50:49Z): max-hold time stop
  (`MAX_HOLD_MINUTES = 240`, reason TIME) — **deploy confirmed live**; **0 TIME
  exits still**. **PR #16/#17 MERGED** same day: win-rate drop check (NO drop) +
  dashboard Win-Rate tile clarity + §2b era table / no-reset decision.
  Earlier: **PR #9** (2026-09-15) `BE_TRIGGER_R` 0.30 → 0.75; **PR #7** (2026-09-10)
  BE ratchet + direction-aware London blackout + trend-side daily breaker.
- Current ledger (`status.json` last_update **2026-09-24 23:59:07**, data on main):
  - **352 closed trades, 0 active** → 52W / 147L / 153BE / 0TIME → **26.1%
    decisive**, equity **$255.80** (true P&L from $500 ≈ −$244; engine-summed
    profits ≈ −$261 — known ledger drift ~+$17, unchanged order of magnitude
    since 09-15)
  - **0.75R era** (entries ≥ 09-15 06:00 UTC): **~175 trades** → 34W/86L/55BE,
    **~28.3% decisive**, ≈ −$0.78/trade (**still below the −$0.40 falsification
    bar**). **Max-hold era** (entries ≥ ~09-21 06:00): **~80 trades** →
    14W/45L/21BE, **~23.7% decisive**, ≈ −$1.20/trade — **still 0 TIME fires**.
  - **Falsification bar FORMALLY TRIPPED 09-17** → fallback step 1 (max-hold)
    **SHIPPED and LIVE 09-21**; step 2 (ratchet-off) still queued behind the
    pre-registered re-review (deploy + ~2 weeks / n ≈ 200 max-hold-era).
  - 0.30R era (09-10 12:34 → 09-15 06:00, n=130): 10W/22L/98BE, 31.2% dec,
    −$0.321/trade. Pre-ratchet (n=45): 17.8% dec, −$1.834/trade.
- Live bot runs from `/opt/gold` via systemd (`goldbot.service` =
  engine, `mt5feed.service` = price-feed sidecar). Daily Grok HANDOFF job +
  autosync every 3 h (§10).

**Current stance:** Edge is **not confirmed**. Mechanism (scratch rate, BE
behaviour) is still consistent with the 0.75R design, but P&L/trade remains
negative and the max-hold stop has never fired (longest holds still ≪ 240 min
in the recent sample). **Next formal re-review** of the max-hold isolation
window ≈ deploy + 2 weeks from 09-21 (target ~2026-10-05) or n≈200 max-hold-era
trades. Do **not** treat the bot as income. Auto-trade timeline unchanged:
edge confirmation ~8 weeks, multi-regime 3–4 months, micro live pilot Q1 2027,
decision **6–12 months (Mar–Sep 2027)**.

### Definitions (binding)

| Term | Meaning |
|------|---------|
| **Decisive WR** | TP / (TP + SL). **Excludes** BE and TIME. |
| **BE exit** | Scratch: SL was ratcheted to entry; P&L ≈ $0. Neutral for WR, cooldown, daily breaker. |
| **TIME exit** | Max-hold close (`MAX_HOLD_MINUTES`). Neutral bucket like BE (own counter; excluded from decisive WR; ignored by SL streak / daily breaker). |
| **0.75R era** | Entries with `Entry_Time ≥ 2026-09-15 06:00 UTC` (PR #9 deploy). |
| **Max-hold era** | Entries after max-hold deploy (~2026-09-21 06:00 UTC autosync). **No counter reset** — falsification bar stays on the whole 0.75R book. |
| **Ratchet geometry** | Reconstruct original SL/TP from `ATR_At_Entry` when `Stop_Loss == Entry_Price` (never key only on `Exit_Reason == "BE"` — some TPs also show that geometry). |

## 2. Bot in one paragraph

Simulated XAUUSD scalper on 1-min candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥38% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar slope, ≤0.3·ATR from EMA50), RSI 30–68, ATR 1.10–4.50.
Exits: SL = entry ∓ 2·ATR, TP = entry ± 3·ATR (1:1.5), plus a breakeven ratchet
that moves SL to entry once the trade is +0.75R ahead (`BE_TRIGGER_R`, 0.30R
from 09-10 to 09-15 — see §4). `engine.py` = signals +
execution/state; `trade_filter.py` = portfolio risk gates; `dashboard.py` =
Flask status page. Trading is FORWARD-TEST simulated (no real orders);
`TRADING_MODE=LIVE` path exists but the BE stop (below) is engine-side only there.

## 3. Data feed: Twelve Data → MT5 sidecar (configured 2026-09-10)

`DATA_SOURCE` env var in `/opt/gold/.env` picks the feed; default in code is
`TWELVEDATA`. **The deployed engine runs `DATA_SOURCE=MT5`**.

How MT5 works (feed-only, trading stays simulated):
- MT5 terminal runs **under Wine** in prefix `~/.mt5`, logged in.
- Sidecar `tools/mt5_feed.py` runs under the **Wine** Python and atomically
  publishes the latest **closed** M1 GOLD candle to `/opt/gold/mt5_last_candle.json`.
- Engine reads that file each poll, dedupes by candle timestamp.

**Tool (2026-09-11):** `tools/mt5_history_dump.py`
- Pulls historical bars (M1/M5/H1/etc.) from the same MT5 connection.
- Useful later for faster offline filter research / walk-forward tests.
- Does **not** affect the live engine.
- Example:
  ```bash
  export WINEPREFIX=~/.mt5
  xvfb-run --auto-servernum \
    wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_history_dump.py \
      --days 365 --timeframe M1 --out Z:/opt/gold/history_m1.csv
  ```
- Remember: broker history ≠ live feed. Live forward-test remains the authority.

Stale-feed guard still active. Feed price scale is the **broker demo GOLD
feed** (~4.4k), not spot XAUUSD.

## 4. Current risk gates (trade_filter.py)

**Source of truth for live params** (do not change without a pre-registered bar + REVIEW/ANALYSIS doc):

| Param | Value | File |
|-------|-------|------|
| `BE_TRIGGER_R` | 0.75 | `engine.py` |
| `MAX_HOLD_MINUTES` | 240 | `engine.py` |
| `ATR_SL_MULT` / `ATR_TP_MULT` | 2.0 / 3.0 | `engine.py` |
| `RSI_MIN` / `RSI_MAX` | 30 / 68 | `engine.py` |
| `MIN_ATR` (engine) | 1.10 | `engine.py` |
| `MIN_ATR_TO_TRADE` / `MAX_ATR_TO_TRADE` | 1.10 / 4.50 | `trade_filter.py` |
| `MAX_DAILY_LOSSES` | 10 | `trade_filter.py` |
| `SL_COOLDOWN_BASE/ESCALATED` | 30 / 60 min | `trade_filter.py` |
| London blackout | 07:55–09:00 UTC, **BUY only** | `trade_filter.py` `BLACKOUT_WINDOWS` |
| NY / rollover blackouts | both sides | `trade_filter.py` `BLACKOUT_WINDOWS` |

- SL cooldown: 30 min, escalating to 60 min after 2 consecutive SLs (BE
  scratches neither count toward nor break the streak — see the engine note
  below and §6 item 2b).
- Daily breaker: after `MAX_DAILY_LOSSES = 10` SLs → trend-side-only mode.
- Blackouts (UTC): London 07:55–09:00 **blocks BUYs only**; NY windows and
  rollover block both sides.
- ATR bounds: <1.10 or >4.50 → skip (high-ATR bound validated live).

Engine: **BE stop ratchet** at +`BE_TRIGGER_R = 0.75`·risk → SL moves to entry
(raised from 0.30 on 2026-09-15: at 0.30R = 0.6·ATR the trigger was one noisy
1-min bar, 77% of new-regime trades scratched with a median lifetime of 1.5 min
and the ratchet was converting +$222 of runs into $0 — docs/REVIEW-2026-09-15.md).
Exit reason `BE` = scratch (excluded from wins/losses/cooldown/daily tally).
Still true after the change: **a BE exit neither triggers nor breaks the SL
streak** (`get_consecutive_sl_count` breaks on TP, counts SL, ignores BE), so
escalation to 60 min is the norm and a scratch can be followed by an instant
re-entry into the same dying setup (27 of 58 0.75R-era entries came <10 min
after the previous exit). Both are open items in §6. Note the counterweight
that FOMC day surfaced: escalating cooldown is what kept 17:28–18:28 UTC dark
on 09-16, so it is no longer an unambiguous leak.

Engine: **max-hold time stop** (deployed 2026-09-21, fallback step 1 —
`docs/REVIEW-2026-09-21.md` §2): any open trade older than
`MAX_HOLD_MINUTES = 240` closes at market with reason `TIME`, whatever the
P&L. Price exits take priority (a simultaneous TP/SL wins); checked on both
the tick path and the MT5 candle path (at close); wall-clock, so across a
closure the trade exits on the first candle/tick back. TIME is a **neutral
bucket like BE**: own `time_exits` counter (in `total_trades`), P&L-signed
into the balance and era P&L/trade, but **excluded from decisive WR math and
ignored by the SL streak / daily breaker**. Engine-side only (LIVE caveat as
for the ratchet).

## 5. Evidence base (don't re-derive)

Key documents:
- `docs/ANALYSIS-2026-09-21-revert-or-maintain.md` (latest — whole book before
  vs after the recent parameter changes on 281 trades → **MAINTAIN, revert
  nothing**: new-regime stack −5.7× bleed, 0.30R→0.75R replay −$116 → +$29
  (never back), max-hold exonerated by 0 fires at longest hold 24.9 min;
  today's −$22 trend-day bleed is noise within the pre-registered fallback)
- `docs/ANALYSIS-2026-09-21-win-rate-drop-check.md` ("did the win rate
  just drop?" → **no**: pooled 27.3% at n=271, era 32.3% at n=96, 0 TIME exits,
  ratchet verified firing at ≥0.76R; the recent 0W/4L run is sampled noise +
  the known cooldown leak. Also relabels the dashboard Win-Rate tile
  "**(decisive)** — all eras · excl. BE/TIME · all-in 14.0%", because the bare
  27.3% tile is era-blind and reads like a collapse; the era rate is 32.3%.
  **§2b: the era table** — 271 trades partitioned into 4 non-overlapping books
  (all 27.3%/−$0.625, pre-ratchet n=45 17.8%/−$1.834, 0.30R era n=130
  31.2%/−$0.321, master 0.75R book n=96 32.3%/−$0.471, of which max-hold era
  n=1) — **plus the no-reset decision (binding):** the max-hold deploy resets
  nothing; "closes at deploy" = the sub-period stops receiving trades; the
  falsification bar stays judged on the whole 0.75R book)
- `docs/REVIEW-2026-09-21.md` (max-hold time stop deployment record
  + 90-trade 0.75R close-out)
- `docs/REVIEW-2026-09-18.md` (falsification bar formally tripped; fallback
  starts; auto-trade timeline framework in §5)
- `docs/REVIEW-2026-09-15.md` (last full review — 164 trades; read it for
  the ratchet rationale, it supersedes several older conclusions below)
- `docs/ANALYSIS-2026-09-10-losing-trades.md`
- `docs/REVIEW-2026-09-10-PM.md`

Current headlines (2026-09-15, 164 trades / 119 new-regime):
- 19.4% decisive (14/72), CI 12.0–30.0; 56% of all trades are $0 scratches.
  Needs 40% decisive to break even at 1:1.5.
- **The ratchet, not the entries, was crushing the win rate.** Same 119 entries
  re-walked at +0.75R: ~45% decisive, +$0.40/trade (cascade-aware). At 0.30R the
  replay reproduces live exactly, which is what makes that comparison valid.
- "Expectancy ≈ −0.5R at every TP placement — entries are the problem" (09-10)
  no longer holds as stated: with the looser ratchet the entry stream replays
  ~50/50. Blocked signals replay 64% decisive (+$198 sequential) vs 19.4%
  taken — cooldown escalation + ratchet explain both sides of that gap.
- RSI < 45 **now meets its pre-registered adoption bar** (new regime: 47 trades,
  10.0% decisive, −$32.22 vs 29.4% for the rest) — candidate #1, adopt next
  cycle.
- ATR ≥ 2.5 (new regime): 0W/4L/13BE, −$27.11 — MAX_ATR tightening is eligible
  but held one cycle so it isn't confounded with the ratchet change.
- ⚠️ Sequence-aware numbers in `docs/REVIEW-2026-09-10-PM.md` §3 used
  `pathwalk_sims.py`, which had its SELL bar extremes inverted (fixed 09-15).
  Anything pathwalk said about SELL trades before this cycle is unreliable.
- **Interim 2026-09-17** (`docs/REVIEW-2026-09-17.md`, 58 trades at +0.75R):
  30.6% dec (CI 18–47), −$0.557/trade — **falsification bar (−$0.40)
  breached in P&L, n=58 < 60**. FOMC 09-16 (+25bp → 3.75–4.00%, 18:00 UTC)
  produced a −$118 (−2.7%) cascade that hit no open trade (escalated cooldown
  17:28–18:28 → MAX_ATR wall 18:02–20:01); 09-16 was already a bleed day
  pre-release, so the breach is not a news fluke. RSI ≥ 45 now ~dropped
  (skip bucket 36.0% dec, −$18.79 vs 27.9% kept); BE-resets-streak
  down-graded (escalation just protected the FOMC hour); ~4h max-hold time
  stop promoted to front of queue. Next check: if P&L/trade ≤ −$0.40 at
  n ≥ 60 → max-hold first, ratchet-off second. Era boundary unchanged:
  09-15 06:00 UTC (PR #9 merged 03:00:23Z, deployed by the 06:00 run).

## 6. Next steps (in order)

1. **Max-hold time stop SHIPPED 09-21 — LIVE, in isolation; re-review next**
   (max-hold re-baseline + ~2 weeks in-isolation data, ≈ deploy + 14 d).
   Deploy confirmed (PR #15 merged 04:50:49Z → ~06:00 autosync restart; the
   engine's 06:59:06 `status.json` carries `time_exits`); the max-hold era is
   at **n ≈ 80, 0 TIME fires** as of 09-25 (still within the pre-registered
   isolation window — do not act on the short-run −$1.20/trade until the
   scheduled re-review). Still pin the exact boundary timestamp
   from `/var/log/gold_autosync.log` or the Telegram deploy digest
   (the engine logs no version, so it cannot be recovered from the CSVs alone).
   After pulling the latest data:
   ```bash
   python3 tools/check_data.py          # expect "0 fail"
   python3 tools/win_rate_report.py     # win-rate decomposition + ratchet grid
   python3 tools/phantom_trades.py
   python3 tools/analyze_losers.py
   python3 tools/validate_gates.py
   ```
   Judge on **P&L per day and bleed per trade**, not on win rate alone (a
   looser ratchet refunds fewer losers, so individual losses get bigger). Write
   `docs/REVIEW-2026-09-2X.md` or `docs/REVIEW-2026-10-XX.md`, update this file +
   `archive/PROJECT_LOG.md`.

2. **Queued strategy changes** — status after the 09-18 review:
   - (a) **RSI ≥ 45 entry filter** — **~DROPPED** (reversal confirmed: skip
     bucket 36.0% dec / −$18.79 vs 27.9% kept; the 09-15 signal was an
     artifact of the old ratchet). Reopen only on a clear reversal at the
     full re-review.
   - (b) **BE resets the SL streak** (cooldown de-escalation) — still queued
     (cooldown phantoms +$206 sequential) but **down-graded**: FOMC day showed
     escalation covering 17:28–18:28 UTC, the one hour it mattered most. It is
     a leak that also buys real protection; treat as a trade-off, not a free win.
   - (c) **RISE120 entry gate** — **REJECTED / dropped** (as a keep-filter it
     retains a worse book: 135 kept, 18% decisive, −$123.40).
   - (d) **MAX_ATR 4.50 → 2.50** — still eligible (0.75R-era ATR≥2.5 bucket
     was thin) but held one more cycle until the max-hold re-review so it is
     not confounded with the time-stop experiment.
   - **~4 h max-hold time stop — SHIPPED 09-21, in isolation from deploy.**
     Era re-baselines at the deploy restart; judge at deploy + ~2 weeks on
     P&L/day + bleed/trade, TIME count + P&L split, >60-min holds ≈ 0.
     Proposed (not yet pre-registered) bar for fallback step 2: post-deploy
     P&L/trade ≤ −$0.40 at n ≥ 200 max-hold-era trades → ratchet-off
     experiment. Confirm or amend at the re-review.
   - Still queued: **~5-min post-scratch pause** (27/58 0.75R entries came
     <10 min after the previous exit); **BUY-side momentum gate** (BUY at
     0.75R was no longer ~0%); a **scheduled-news gate** is a *named*
     candidate post-FOMC but that event passed without one.
   - Falsification for the ratchet change: **TRIPPED** (09-17 16:17 UTC,
     −$0.595/trade at n=60) — fallback in progress with the
     **~4h max-hold stop** in isolation, then ratchet-off if needed (replay
     +$0.52/trade, 41% decisive) — **never** back to 0.30R.

3. Historical research (optional, later): use `tools/mt5_history_dump.py`
   once you want to stress-test candidate filters on multi-year data. A
   replay-driven change of this size is exactly what multi-year data is for.

4. LIVE-mode broker-side BE modify — only if/when switching to real orders.
   Note the ratchet level is now +0.75R, and the engine-side-only caveat still
   applies.

## 7. How to verify code changes (always)

```bash
python3 tools/smoke_test.py          # must print "SMOKE TEST PASSED"
python3 -m py_compile engine.py trade_filter.py
python3 tools/check_data.py          # expect "0 fail"
python3 -m py_compile tools/*.py     # analysis tools must at least import
python3 tools/win_rate_report.py     # must run end-to-end on current data
```

Note: `tools/` scripts are NOT covered by smoke_test.py and several of them
have historically crashed or lied on new data shapes (2026-09-15: ZeroDivision
on ratcheted-stop rows, inverted SELL bars in pathwalk). Run them after every
data drop, not just after code changes.

## 8. Data gotchas (hard-won)

- `trades.csv` has historical Trade_Num resets — dedupe by timestamp.
- **Ratcheted rows** log the *live* stop, so `Stop_Loss == Entry_Price` on 98
  rows: all 92 BE scratches **plus 6 TP winners** (#95, #120, #123, #133, #156, #164).
  Reconstruct original SL/TP from `ATR_At_Entry` (SL = entry ∓ 2·ATR, TP = entry ± 3·ATR).
- `status.json` `win_rate` is decisive (TP/(TP+SL)); dashboard tile now labels it.
- Balance vs sum(Profit) drift is known (~$10–25); order of magnitude is the authority.
- Entry times are UTC; local session labels (London/NY) use UTC windows in code.

## 9. Architecture quick map

```
engine.py          signals + BE ratchet + max-hold TIME + state machine
trade_filter.py    portfolio gates (cooldown, daily breaker, blackouts, ATR)
dashboard.py       Flask status page (read-only)
tools/             analysis / integrity / report scripts (not on the hot path)
/opt/gold/         live deploy root (autosync from main; never hand-edit)
```

## 10. Deploy & ops

- **Source of truth for live code:** `main` on GitHub.
- Autosync: every 3 h from `/opt/gold` (`tools/autosync.sh`); refuses if local
  dirty. Force: `sudo /opt/gold/tools/autosync.sh`.
- Daily Grok job refreshes `docs/HANDOFF.md` §1 from `status.json` + `trades.csv`.
- Services: `goldbot.service` (engine), `mt5feed.service` (Wine MT5 sidecar).
- Logs: `journalctl -u goldbot -f`; autosync log `/var/log/gold_autosync.log`.

## 11. How to keep this file honest

**Session & Push Protocol**
1. Push every commit immediately (do not batch).
2. Keep a session PR open until the user signs off.
3. Before ending: update §1 numbers, §4/§5 if params/evidence moved, §6 next steps.
4. Never leave conclusions in chat only — land them in this file or a dated REVIEW.

**Auto-trade timeline (unchanged)**

| Horizon          | Gate                              | Action |
|------------------|-----------------------------------|--------|
| Now              | Edge not confirmed                | Isolation: max-hold only |
| ~2 weeks (10-05) | Max-hold re-review                | Judge TIME + P&L; queue (a) approved-next, (c) dropped |
| ~2–4 weeks       | Judge the new ratchet level       | Re-run suite; P&L/day + bleed/trade, not WR alone |
| ~2–4 months      | 100+ trades, multiple regimes     | First serious evaluation of edge            |
| 6–12 months      | Durable positive expectancy?      | Decide if it deserves any real capital      |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
