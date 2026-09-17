# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Gold trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

Keep it current: every session that changes code, params, or conclusions must
update §1, §4/§5 and §6 before it ends (see §11 "How to keep this file
honest"). §11 also carries the **Session & Push Protocol** — push every commit
immediately and keep the session PR open until the user signs off. Follow it
from the first commit.

## 1. Where things stand (as of 2026-09-17)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`.
  Current work branch: `arena/01a0afd7-gold-trading-bot` (FOMC review, docs only).
- **PR #9 MERGED** (2026-09-15): `BE_TRIGGER_R` **0.30 → 0.75**, analysis-tool
  fixes (SELL replay bug, ratcheted-stop handling, `check_data` tripwires), new
  `tools/win_rate_report.py`, and this review cycle's docs. Earlier: PR #7
  (2026-09-10 12:33 UTC) put the BE ratchet + direction-aware London blackout +
  trend-side daily breaker on `main`.
- Current ledger (from latest `trades.csv` / `status.json`, data collection 66):
  - **233 trades** → 29W / 84L / 120BE → 25.7% decisive (CI 18.1–35.0),
    −$156.50 (engine ledger $368.20, known drift +$24.70)
  - **0.75R era** (entries ≥ 09-15 06:00 UTC — the 06:00 autosync run deployed
    PR #9, which merged 03:00:23Z, 23 s after the 03:00 run): **58 trades** →
    11W/25L/22BE, **30.6% decisive (CI 18.0–46.9)**, −$32.30 (**−$0.557/trade —
    below the −$0.40 falsification bar**; bar formally trips at n ≥ 60)
  - 0.30R era (09-10 12:34 → 09-15 06:00, n=130): 10W/22L/98BE, 31.2% dec,
    −$0.321/trade. Pre-ratchet (n=45): 17.8% dec, −$1.834/trade.
  - Scratch rate 75.4% → **37.9%** across the ratchet change; median BE hold
    1.9 → 8.5 min; BUY side 7W/16L/19BE at 0.75R.
- Live bot runs from `/opt/gold` via systemd (`goldbot.service` =
  engine, `mt5feed.service` = price-feed sidecar).

**Current stance:** 58 trades into the +0.75R era
(`docs/REVIEW-2026-09-17.md`): the **mechanism is still confirmed** (scratch
rate 38%, median BE hold 8.5 min) but the **edge is not there** — 30.6% dec
and **−$0.557/trade** after the FOMC day (09-16: +25bp hike to 3.75–4.00% at
18:00 UTC) and a genuine 09-16 grind-down bled −$22.92. The FOMC cascade
(−$118, +2.7% in 70 min) hit **no open trade**, covered by defense-in-depth
(escalated cooldown 17:28–18:28 → MAX_ATR wall 18:02–20:01) — good, but
09-16 was already a bleed day pre-release, so the bar breach is not a
news fluke. **No strategy changes.** RSI ≥ 45 is now ~dropped; the
BE-resets-streak candidate is down-graded (FOMC day showed escalation
covering the one hour it mattered most); the **~4h max-hold time stop is
promoted to the front of the queue**. If 0.75R P&L/trade is still ≤ −$0.40 at
n ≥ 60 the pre-registered fallback begins — max-hold first, ratchet-off second
(never back to 0.30R). Still do **not** treat the bot as income. See the
patience notes at the end.

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

## 5. Evidence base (don’t re-derive)

Key documents:
- `docs/REVIEW-2026-09-17.md` (latest — FOMC day + 58-trade 0.75R check;
  **read this one first**)
- `docs/REVIEW-2026-09-15.md` (last formal review — 164 trades; read it for
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

1. **Let the new ratchet level accumulate data, then re-review** (~2 weeks).
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
   `docs/REVIEW-2026-09-2X.md`, update this file + `archive/PROJECT_LOG.md`.

2. **Queued strategy changes** — status after the 09-17 (FOMC) review:
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
     1W/4L/4BE, −$12.35, −$1.37/trade) but held one more cycle (n=9 too small;
     and it was not the FOMC-day balm it briefly looked like in-window).
   - Still queued: **~4h max-hold time stop** (now **first in queue** — caps
     the two >60-min holds, expresses "close before scheduled macro events"
     without a news feed); **~5-min post-scratch pause** (27/58 0.75R entries
     still come <10 min after the previous exit); **BUY-side momentum gate**
     (BUY at 0.75R is 7W/16L/19BE = 30.4% dec — no longer ~0%, tripwire not
     met); a **scheduled-news gate** is now a *named* candidate post-FOMC but
     this event passed without one.
   - Falsification for the ratchet change (still the pre-registered plan): if
     0.75R-era P&L/trade is ≤ −$0.40 once n ≥ 60, begin the fallback with the
     **~4h max-hold stop** measured in isolation, then ratchet-off if needed
     (replay +$0.52/trade, 41% decisive) — **never** back to 0.30R.

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
  rows: all 92 BE scratches **plus 6 TP winners** (#95, #120, #123, #133, #156,
  #157 — they armed, held, and still printed TP). Key any reconstruction on the
  GEOMETRY (`entry == sl`), never on `Exit_Reason == "BE"`, or you divide by
  zero. Reconstruct the 2×/3×ATR levels from `ATR_At_Entry` for R math.
- Counterfactual exits need a walk with an explicit horizon: a BE scratch died
  ~1.5 min after entry, so re-scoring it inside its own exit window can never
  reach a looser TP and silently returns "actual" (this is what made
  `pathwalk_sims.py` look self-validating and `analyze_losers.py` §4 print
  nonsense). Use `pathwalk_sims.py` (`horizon_min` rows) or
  `win_rate_report.py` §5b/§5c.
- Direction matters in every replay: a SELL's *favourable* bar extreme is its
  LOW and its *adverse* extreme is its HIGH. `hi_r = d*(h-e)/risk` is only the
  favourable side for BUYs (fixed 09-15 via max/min excursion form).
- Clock skew between `forward_test_log.csv` and `trades.csv` (use ±2 min windows).
- Gold price series = broker demo feed (~4.3-4.4k), not spot.
- No time stop exists: a trade opened just before a market close rides the gap
  (#95: Fri 20:57 → Sun 22:01, 49.1 h). `check_data.py` now warns on >60-min
  holds and on trades spanning any price-log gap (inclusive bounds).

## 9. File map (short)

`engine.py` · `trade_filter.py` · `trades.csv` · `forward_test_log.csv` ·
`skipped_trades.csv` · `status.json` · `tools/` (analysis incl.
**`win_rate_report.py`** (new 09-15), `check_data.py`, `phantom_trades.py`,
`pathwalk_sims.py`, `analyze_losers.py`, `validate_gates.py`, `exit_sims.py`,
`smoke_test.py` + feeds `mt5_feed.py` / **`mt5_history_dump.py`** +
`autosync.sh`) · `docs/REVIEW-*.md` · `docs/HANDOFF.md`

---

## 10. Autosync & deploy rhythm (single reference)

**Cron (on the box):**
```cron
0 */3 * * * /opt/gold/tools/autosync.sh >> /var/log/gold_autosync.log 2>&1
```

**What autosync does every 3 hours:**
1. Commits any new live data (`trades.csv`, `forward_test_log.csv`,
   `skipped_trades.csv`, `status.json`) and pushes to `origin/main`.
2. If `origin/main` has moved (new code/docs from a session):
   - Stops the engine **only if** `engine.py` or `trade_filter.py` changed
   - Merges (data files = server wins, everything else = remote wins)
   - Runs `tools/smoke_test.py` — automatic rollback on failure
   - Restarts the engine (and dashboard if needed)
   - Verifies `status.json` is fresh
3. Runs `tools/check_data.py`
4. Sends a short Telegram digest

**Working agreement:**
- Code, tools, and docs changes are pushed to `main` from sessions.
- The box picks them up automatically on the next autosync cycle (≤ 3 h).
- No need for manual `git pull` or engine restarts in normal operation.
- Only intervene when Telegram reports a problem (rollback, check_data fail,
  engine not active, etc.).

**Safety guarantees already in the script:**
- `flock` prevents overlapping runs
- Data is committed *before* any merge (rollback never loses trades)
- Refuses to deploy if someone hand-edited code files on the server
- Smoke-test gate + automatic rollback
- `.env` is never committed

---

## 11. How to keep this file honest (do this every session)

### Session & Push Protocol (CRITICAL — zero unpushed state)

The sandbox workspace is **ephemeral**: when a session ends, its filesystem is
destroyed, so **a commit that is not on GitHub does not exist**. These four
rules apply to every session, from the first commit:

1. **One session = one scope = one PR at the end.** Do all session work on the
   session branch and keep pushing to it; open at most one PR per session and
   merge it only when the entire session goal is complete. Merging is the last
   click, not a mid-session step — and here merge → `origin/main` → the next
   `tools/autosync.sh` run (≤ 3 h, §10) **deploys to the live box**, a second
   reason it is final.
2. **Push after every logical step (zero local-only state).** After each code
   or doc modification:
   `git add <files> && git commit -m "..." && git push origin <branch>`
   Keep GitHub perfectly synchronized with the workspace so nothing is lost if
   the connection drops or the browser closes. Never plan to cherry-pick or
   salvage commits from a previous session's local workspace — that workspace
   is gone; anything not pushed is unrecoverable.
3. **The PR stays open (draft / in-progress) until the user gives the green
   light.** If a PR is opened early, open it as a **draft** and push additional
   commits to the same branch — GitHub updates the PR automatically. Merge only
   after the agent reports "all tasks complete, `tools/smoke_test.py` prints
   SMOKE TEST PASSED and `tools/check_data.py` reports 0 fail (§7), ready for
   merge" **and** the user confirms.
4. **Hand off via this file + `archive/PROJECT_LOG.md`, not chat.** Before a
   session ends (and always before a PR merges), §1/§4/§5/§6 and the changelog
   must reflect the new state, so the next session boots from `main` with full
   context — no cherry-picking, no orphan commits, no lost work.

**Opening line for a new session (no need to re-explain this workflow):**
> "Read `docs/HANDOFF.md` and follow the Session & Push Protocol. I want to
> work on [X]."

### Per-session update ritual

1. Update **§1** (date, trade count, new-regime count, branch/PR state).
2. Update **§4/§5** if params changed or a review produced new numbers —
   replace stale figures, don't append.
3. Move anything you shipped out of **§6** and into `archive/PROJECT_LOG.md`'s
   changelog; add whatever the session queued.
4. Write the analysis itself in `docs/REVIEW-YYYY-MM-DD.md`; this file only
   carries the *conclusion* and a pointer. The current one is
   `docs/REVIEW-2026-09-17.md` (FOMC + 233 trades / 58 at +0.75R); the last
   full review is `docs/REVIEW-2026-09-15.md` (164 trades).
5. Never quote a pooled decisive win rate across the 09-15 ratchet change
   (`BE_TRIGGER_R` 0.30→0.75) without naming the era, and key any BE
   reconstruction on the geometry (`Stop_Loss == Entry_Price`), never on
   `Exit_Reason == "BE"` — both traps are detailed in §8 and have already
   bitten this project.
6. Commit with a message that names the doc, so `git log --oneline` stays a
   usable index of decisions — and push immediately (see protocol above).

---

### Patience / decision framework

| Horizon          | Goal                              | Action                                      |
|------------------|-----------------------------------|---------------------------------------------|
| Done             | Reach ≥30 new-regime trades       | Cleared (119 as of 2026-09-15)               |
| Done             | Fresh review + decide queued changes | `docs/REVIEW-2026-09-15.md`; ratchet raised 0.30→0.75, (a) approved-next, (c) dropped |
| ~2–4 weeks       | Judge the new ratchet level       | Re-run suite; P&L/day + bleed/trade, not WR alone |
| ~2–4 months      | 100+ trades, multiple regimes     | First serious evaluation of edge            |
| 6–12 months      | Durable positive expectancy?      | Decide if it deserves any real capital      |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
