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
   python3 tools/momentum_regime.py     # regime/side + the 09-28 hypothesis & its bar
   ```
3. **Next formal work:** max-hold re-review (~2026-10-05 or n≈200 max-hold-era trades;
   currently n=178); score `H-side-awareness` there (ANALYSIS-2026-09-28 §5).
   Read `docs/ANALYSIS-2026-10-01-stop-loss-rate.md` first: high SL rate verified,
   **no bot changes**, research-tool corrections and next-session checklist.
4. Never change `BE_TRIGGER_R` / `MAX_HOLD_MINUTES` / ATR bounds / blackouts without a
   pre-registered bar + REVIEW/ANALYSIS doc.

### Command cheat sheet

| Goal | Command |
|------|---------|
| Integrity first | `python3 tools/check_data.py` |
| Era / WR / ratchet grid | `python3 tools/win_rate_report.py` |
| Falling-gold / side regime check | `python3 tools/momentum_regime.py` |
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
- Read falling-vs-rising (or "gold is down") stats pooled across sides — split
  by BUY/SELL first (they are ~collinear with direction, §2).

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

## 1. Where things stand (as of 2026-10-01, 14:59:04 UTC snapshot)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`. This session is
  on `arena/01a0f896-gold-trading-bot`; **analysis + notes only**, no bot/code/
  parameter/data/deploy change. Latest review:
  `docs/ANALYSIS-2026-10-01-stop-loss-rate.md` (read before proposing a fix).
- Historical deploys unchanged: **PR #15 MERGED** (09-21 04:50:49Z),
  `MAX_HOLD_MINUTES = 240` live since ~06:00; **PR #9** (09-15) BE 0.30→0.75R;
  **PR #7** (09-10) ratchet + BUY-only London blackout + trend-side daily breaker.
  Feed-health/restart guards are present in the checkout; **production-host
  hardening/deploy verification was not performed in this session**.
- Current ledger (data collection 160, commit `3e734c4`; **not frozen at 09-29
  anymore**, §1a): **448 closed / 0 active**, 77W / 184L / 187BE / 0TIME →
  **29.5% decisive** [24.3–35.3], paper P&L from $500 **−$251.69 → $248.31**.
  Engine ledger $265.28; known drift **+$16.97**. Integrity **0 fail / 8 warn**;
  synthetic smoke **A–M passed**. October 1 is a **partial day**.
  - **0.75R master book** (entries ≥09-15 06:00): **n=273**, 59W/125L/89BE,
    **32.1% decisive** [25.8–39.1], **−$0.467/trade**; original −$0.40
    falsification bar remains tripped (formally since 09-17).
  - **Max-hold era** (entries ≥09-21 06:00): **n=178**, 39W/84L/55BE,
    **31.7% decisive** [24.1–40.4], **−$0.488/trade**, **0 TIME fires**.
    Longest hold **67.97 min**, #409 BE across the normal daily closure;
    median SL hold 9.02 min. The 240-min cap has not bound any recorded trade.
  - 0.30R era unchanged: n=130, 10W/22L/98BE, 31.2% decisive,
    −$0.321/trade. Pre-ratchet: n=45, 17.8%, −$1.834/trade.
- **High SL percentage verified:** **41.1% of all closed trades** versus
  **70.5% of decisive TP/SL outcomes** (BE/TIME excluded). In the current
  0.75R book: 45.8% / 67.9%. No current-era BE→SL mislabelling or incorrect
  2×ATR stop geometry found; a matched-rule diagnostic reproduces its ledger.
  Nevertheless gross profit factor is only **0.637** pooled / **0.736** at
  0.75R. Planned 1:1.5 needs ~40% decisive wins before costs. **Not a reason
  to widen/tighten SL or lower TP ad hoc.** The 46 new trades since the last
  handoff made +$3.30; no fresh win-rate collapse, but no confirmed edge either.
- **Candidates, not approvals:** max-hold BUY **−$103.83** (22.9% decisive)
  versus SELL **+$16.95** (37.3%), Fisher p=0.1137; remove 09-28 and SELL is
  **−$24.97**. `H-side-awareness` still does not qualify; no BUY ban/SELL-only
  gate. Fast <5-min same-side entries after BE lose **−$72.65 across 54 trades**
  in the 0.75R book (max-hold: −$55.31 across 33), but this is observational,
  not saved money or approval for the queued pause. RSI/ATR combo does not
  persist in the max-hold sample. See the latest analysis §§3–5.
- **Required next-session research corrections:** existing replay tools mix
  ratchet eras, carry stale 0.30R labels, and have cooldown/alignment/cost-model
  limitations. Correct/calibrate them **before** using their simulated profit
  to pick a change. A current-era observed-entry ratchet-off diagnostic is
  only **+$1.45 / 191 taken trades before costs** (max-hold-only +$9.37/130),
  not a proven replacement; it does not regenerate the full signal stream.
- Live bot historically runs from `/opt/gold` via systemd (`goldbot`, `mt5feed`,
  Wine `mt5`); daily HANDOFF job + autosync every 3 h (§10). Live-host state
  cannot be inferred from this checkout alone.

### 1a. 🛑 2026-09-29 feed outage — 6 h of silent starvation (read before trusting a "STALE" badge)

- **What happened:** the host rebooted at **08:29:15 UTC** (journal
  `-- Boot c22469d0… --`). `goldbot`, `mt5feed` and `mt5` all restarted at
  08:29:18, but **`mt5.service` never came back — stuck in
  `deactivating (stop-sigterm)`**, so the terminal published no more bars.
  `mt5_last_candle.json` froze at `ts=1790681280` (11:28 server / 08:28 UTC,
  mtime 08:29) and `status.json` froze at 08:29:19 → dashboard **STALE** from
  ~08:34 (the only detector that worked).
- **Why it was invisible:** the engine stayed `active (running)` and looped on
  the *deduped* candle, whose `continue` jumped over the stale-feed guard, and
  `feed_stale_seconds()` reads `_last_price_mono` — never set after a restart —
  so it reported `0.0` ("fresh") the whole time. No journal line, no Telegram
  alert; the 09:00/12:00/15:00 autosync digests said `data: no new data` and
  `check_data.py` was 0 fail.
- **Precursor (undocumented):** a second stall **09-28 17:50:05 → 09-29
  03:33:37** (9.7 h, ~283 open-market minutes) with the same signature — so the
  failure hit twice in 24 h, and the ~09-28 "slide" discussion never noticed it.
- **Impact (historical):** ~6 h of London/NY missing (engine does **not**
  backfill) + ~283 open minutes on 09-28. **No trade was open across either
  outage** (#397 exit 09-28 17:40:02, #403 exit 09-29 07:51:03) → no phantom P&L.
  At the outage the ledger froze at 402 closed, 64W/166L/172BE, −$254.99.
  **Recovery now visible in CSVs:** 09-29 14:47:39 (6 h 18 min gap); another
  14:50:40→15:43:06 gap also overlaps no trade. Data advances through 10-01
  14:59:04; §1 has current numbers. This does not prove server-side hardening.
  **Strategy/params untouched; the max-hold isolation window is undisturbed.**
- **Fix shipped (detection only, `docs/REVIEW-2026-09-29-feed-outage.md`):**
  engine feed-health check (`feed_publisher_age_seconds()` = sidecar heartbeat,
  missing/corrupt file, price-event stall — evaluated **before** the dedup,
  journal print every 5 min, Telegram on the 30-min cooldown, one recovery
  line); smoke **Scenario L**; autosync digest now carries
  `📈 candles: ok|STALE N open min`.
- **Ops follow-ups (server-side, not in the repo):** harden `mt5.service`
  (`Restart=always`, `RestartSec=10`, `TimeoutStopSec=30`,
  `KillMode=control-group`, `systemctl enable`), use the recovery runbook in
  §7 of the review, and treat the Wine MT5 terminal as the least reliable
  component (the 08:29 reboot cause is still unexplained).

**Current stance:** Edge is **not confirmed**; the current 0.75R and max-hold
books still lose money even before realistic costs. Stop/BE mechanics check
out on the paper ledger; the never-fired max-hold cannot explain the many
~9-min SL exits. Preserve isolation. **Next formal review** remains
~2026-10-05 or n≈200 post-deploy trades (currently 178). The proposed step-2
bar is not approved by this analysis; confirm/register any ratchet-off
experiment at that review, after costed, stateful research validation. Score
the registered momentum/side hypothesis there; keep the post-BE pause as a
separate later candidate. **No runtime change was made or adopted 10-01.**
Stay paper-only and do **not** treat the bot as income. Capital decisions
remain evidence-gated, not promised by the existing calendar timeline (§11).

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
EMA50 vs EMA200 (+30-bar slope, one-sided 0.3·ATR EMA50 buffer),
RSI BUY 30–68 / SELL 32–70, ATR 1.10–4.50.
Exits: SL = entry ∓ 2·ATR, TP = entry ± 3·ATR (1:1.5), plus a breakeven ratchet
that moves SL to entry once the trade is +0.75R ahead (`BE_TRIGGER_R`, 0.30R
from 09-10 to 09-15 — see §4). `engine.py` = signals +
execution/state; `trade_filter.py` = portfolio risk gates; `dashboard.py` =
Flask status page. Trading is FORWARD-TEST simulated (no real orders);
`TRADING_MODE=LIVE` path exists but the BE stop (below) is engine-side only there.
Because the trend gate keys side on EMA50 vs EMA200, **direction and side are
nearly collinear in the data** (94% of falling-60m entries are SELLs, 96% of
rising-60m are BUYs) — never read a "momentum" claim without splitting by side
(ANALYSIS-2026-09-28).

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
| `RSI_MIN` / `RSI_MAX` | BUY 30 / 68; SELL mirrored 32 / 70 | `engine.py` |
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
- `docs/ANALYSIS-2026-10-01-stop-loss-rate.md` (**latest, analysis-only**):
  448 closed; SL/all 41.1% versus SL/decisive 70.5%; current 0.75R n=273,
  −$0.467/trade, max-hold n=178, −$0.488/trade / 0 TIME. Geometry/labels and
  current-rule replay verified; smoke A–M passed, integrity 0 fail / 8 warn.
  **No bot change justified by the percentage alone.** Next-session queue:
  verify host/feed, repair/calibrate research tools, formal isolation review,
  costed stateful ratchet-off only if approved, separate post-BE-pause test.
  Replaces stale candidate headlines, not historical review records.
- `docs/REVIEW-2026-09-29-feed-outage.md` (latest — 6-h silent starvation after
  the 08:29 reboot: evidence chain, the guard bug that hid it, the undocumented
  09-28 precursor, detection fix + ops runbook)
- `docs/ANALYSIS-2026-09-28-falling-gold-win-rate.md` ("WR improves
  when gold falls?" → **wrong cause, no adoption**: real 30.7% vs 25.0% pooled
  gap but day-level null (27.9% vs 28.1%), side-coupled (94/96%), within-BUY
  refuted (13 falling-tape BUYs = worst bucket, 15.4%), whole gap 3 days old and
  inverted in the 09-17/09-18 up-leg (BUY 45.0% vs SELL 12.5%). Registered
  `H-side-awareness` + pre-registered bar — scored at the 10-05 re-review.
  Tool: `tools/momentum_regime.py`)
- `docs/ANALYSIS-2026-09-21-revert-or-maintain.md` (whole book before
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

Historical headlines (2026-09-15, 164 trades / 119 new-regime; superseded
for current decisions by the dated reviews above and §6):
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
- **2026-09-28 (380 trades) — "gold falls → WR improves?"** (see the
  ANALYSIS-2026-09-28 doc): the pooled falling-tape gap is real but small and
  insignificant (30.7% vs 25.0%, p=0.37; 240-min p=0.072) and structurally
  confounded with side. Day-level null; within-BUY refuted (falling-tape BUYs
  15.4% vs 23.2% — the worst bucket); the whole gap is 3 trading days old and
  inverts in the 09-17/09-18 up-leg (BUY 45.0% / SELL 12.5%). What survives: the
  recent bleed is the BUY side (max-hold era BUY 14.3% dec / −$84.07 vs SELL
  36.5% / +$10.69), consistent across eras but only nominal (pooled p=0.070,
  p→0.16 without 09-28) and possibly just the −6.7% slide we happen to be in.
  Registered hypothesis + bar; **no gate adopted**.

## 6. Next steps (in order)

0. **Ops verification first:** CSV collection recovered on 09-29 and advances
   through 10-01, but confirm the heartbeat/alerts/dedup deployment and
   `mt5.service` hardening **on the production host**. Runbook + drop-in in
   `docs/REVIEW-2026-09-29-feed-outage.md` §7 (`Restart=always`,
   `TimeoutStopSec=30`, `KillMode=control-group`, `systemctl enable`). Recover
   the terminal only if it is stalled; do not infer a fresh outage from a
   cloned snapshot's age. Check `mt5_last_candle.json` mtime/`updated_at`, live
   status/log progression, `📈 candles: ok` and journal recovery/health lines.
   Server access/deployment was **not** verified in the 10-01 analysis.
   **Research prerequisite:** fix the era, SL-streak, timestamp-alignment,
   direction-aware gate and costs issues in ANALYSIS-2026-10-01 §4; calibrate
   each era's actual rule before trusting any hypothetical P&L. Tools-only
   validation does not authorise runtime/strategy changes.
1. **Max-hold time stop SHIPPED 09-21 — LIVE, in isolation; re-review next**
   (max-hold re-baseline + ~2 weeks in-isolation data, ≈ deploy + 14 d).
   Deploy confirmed (PR #15 merged 04:50:49Z → ~06:00 autosync restart; the
   engine's 06:59:06 `status.json` carries `time_exits`); the max-hold era is
   at **n=178, 0 TIME fires** as of 10-01 14:59 (−$0.488/trade; longest
   67.97 min, one BE across the normal daily closure). Still within the
   isolation window — **22 trades short of n=200**; no runtime change at this
   analysis-only checkpoint. Still pin the exact boundary timestamp
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
   **Also score at this re-review:** the registered `H-side-awareness`
   hypothesis (falling-gold/win-rate question, 09-28) — aligned entries beat
   counter-trend entries *within each side*, across gold regimes. Its bar is
   printed by `tools/momentum_regime.py` §8 and in
   `docs/ANALYSIS-2026-09-28-falling-gold-win-rate.md` §5: (a) ≥25 decisive
   outcomes in the counter-trend bucket; (b) ≥5 pp gap, same direction, **within
   BUY and within SELL separately**; (c) must also hold in a rising-gold
   sub-period (≥1 day, gold +≥0.5%); (d) P&L/trade no worse than −$0.10; (e) doc
   + isolation before adoption. **10-01 60-min diagnostic:** counter-trend
   outcomes total only 24 decisive (16 BUY / 8 SELL); the within-SELL gap is
   opposite to the required direction. Current-era gaps also do not qualify
   (ANALYSIS-2026-10-01 §3). Score all criteria formally; no adoption now.

2. **Queued strategy changes** — refreshed 10-01; candidates only, no adoption:
   - (a) **RSI ≥45 entry filter — remains DROPPED/not approved.** 10-01
     0.75R keep/skip: 32.5%/31.4% decisive, −$0.493/−$0.422 per trade; no
     standalone P&L benefit. The RSI+ATR combo is less bad in the master book
     but reverses in max-hold (−$0.529 kept vs −$0.449 skipped). Reopen only
     with an era-correct, pre-registered test, not the old 09-15 adoption claim.
   - (b) **BE resets the SL streak** (cooldown de-escalation) — still queued
     but **down-graded**: FOMC day showed escalation covering 17:28–18:28 UTC.
     Treat it as a protection/opportunity trade-off, not a free win. Current
     phantom/cascade tools do not model the full live semantics; calibrate
     those before changing a gate. Do not combine this with a post-BE pause.
   - (c) **RISE120 entry gate** — **REJECTED / dropped** (as a keep-filter it
     retains a worse book: 135 kept, 18% decisive, −$123.40).
   - (d) **MAX_ATR 4.50→2.50 — queued, NOT approved.** 10-01 0.75R
     below/above-2.5 buckets both ~32.1% decisive; dollar loss can reflect
     position risk rather than signal quality. Max-hold keep −$0.509/trade
     vs skip −$0.401. Require normalized-risk/costed evidence at the formal
     review; no tightening during isolation.
   - **~4 h max-hold time stop — SHIPPED 09-21, in isolation from deploy.**
     Era re-baselines at the deploy restart; judge at deploy + ~2 weeks on
     P&L/day + bleed/trade, TIME count + P&L split, >60-min holds ≈ 0.
     Proposed (not yet pre-registered) bar for fallback step 2: post-deploy
     P&L/trade ≤ −$0.40 at n ≥ 200 max-hold-era trades → ratchet-off
     experiment. Confirm or amend at the re-review.
   - Still queued: **fixed ~5-min post-scratch pause**, separate from SL-streak
     changes. 10-01: 54/273 0.75R entries are same-side <5 min after BE,
     9W/30L/15BE, −$72.65 (max-hold 33 entries, −$55.31). Observational only;
     replay the changed signal/occupancy cascade and pre-register a bar before
     adoption. A **scheduled-news gate** remains a named, unadopted candidate.
   - (e) **Momentum gate / `H-side-awareness` — REGISTERED 09-28, not adopted.**
     10-01 max-hold BUY 11W/37L/24BE, 22.9% decisive, −$103.83; SELL
     28W/47L/31BE, 37.3%, +$16.95 (−$24.97 without 09-28), Fisher p=0.1137.
     It still fails the unchanged 5-part bar in ANALYSIS-2026-09-28 §5; latest
     side/era diagnostics in ANALYSIS-2026-10-01 §3. No ad-hoc BUY blocker.
   - Falsification for the ratchet change: **TRIPPED** (09-17 16:17 UTC,
     −$0.595/trade at n=60; now −$0.467 at n=273). Fallback max-hold remains
     in isolation. Step 2 is a **candidate ratchet-off experiment**, not a
     proven edge: current-era observed-entry replay +$1.45/191 gross, easily
     erased by costs (ANALYSIS-2026-10-01 §4). Confirm the proposed step-2 bar
     at review, then pre-register an isolated experiment if proceeding —
     **never** back to 0.30R.

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
python3 tools/momentum_regime.py     # same, plus prints the registered bar
```

Note: `tools/` scripts are NOT covered by smoke_test.py and several of them
have historically crashed or lied on new data shapes (2026-09-15: ZeroDivision
on ratcheted-stop rows, inverted SELL bars in pathwalk). Run them after every
data drop, not just after code changes.

## 8. Data gotchas (hard-won)

- `trades.csv` has historical Trade_Num resets — dedupe by timestamp.
- **Ratcheted rows** log the *live* stop: at the 10-01 snapshot,
  `Stop_Loss == Entry_Price` on **256 rows: 187 BE + 69 TP**. Reconstruct
  original risk geometrically, not just on BE (SL = entry ∓ 2·ATR, TP =
  entry ± 3·ATR). For exact baseline calibration, preserve the logged target
  and account for ATR/price rounding; see ANALYSIS-2026-10-01 §4.
- `status.json` `win_rate` is decisive (TP/(TP+SL)); dashboard tile now labels it.
- Balance vs sum(Profit) drift is known (~$10–25); order of magnitude is the authority.
- Entry times are UTC; local session labels (London/NY) use UTC windows in code.
- **Momentum at entry must be measured strictly before the entry bar** (the
  price log lags `trades.csv` by ~1 min — `tools/momentum_regime.py` uses
  `entry − 1 min` for "now" and the same offset for the window start). Never
  include the entry minute's close in a pre-entry feature.
- **A frozen `mt5_last_candle.json` is not a quiet market.** The sidecar
  rewrites the file every 5 s even when the market is closed, so a stale mtime
  means the *publisher* died (terminal logged out/stuck) — the only reliable
  signal, because with a frozen file no candle is ever accepted and
  `feed_stale_seconds()` stays `0.0` (2026-09-29). The engine now checks the
  heartbeat before the dedup; see `mt5_feed_problem()`.
- **Never read a momentum/regime claim without a side split**: the trend gate
  makes falling tape ≈ SELL and rising tape ≈ BUY (94%/96% in the book), so
  pooled momentum numbers are side numbers in disguise (2026-09-28).

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
- Autosync digest now carries `📈 candles: ok (N open min) | STALE N open min`
  (phase 4b, added 2026-09-29): open-market minutes since the last logged candle,
  weekend/daily break excluded, shouts at > 90. A green digest with `no new
  data` no longer means "all fine" on its own.
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
| ~2 weeks (10-05) / n≈200 | Max-hold re-review        | Judge TIME + P&L; score registered/queued candidates, none auto-approved |
| ~2–4 weeks       | Judge the new ratchet level       | Re-run suite; P&L/day + bleed/trade, not WR alone |
| ~2–4 months      | 100+ trades, multiple regimes     | First serious evaluation of edge            |
| 6–12 months      | Durable positive expectancy?      | Decide if it deserves any real capital      |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
