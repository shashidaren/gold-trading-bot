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
3. **10-05 re-review is DONE:** `docs/REVIEW-2026-10-05.md`. Max-hold isolation
   closed (n=209, 1 TIME exit, cap never bound in-session); fallback step-2
   trigger **MET** (−$0.570/trade at n=209) → ratchet-off is **eligible to be
   pre-registered, but blocked on the costed harness + user sign-off**;
   `H-side-awareness` **DROPPED** (bar (b) and (c) fail). New named candidate:
   London/NY session-band bleed (§5a) — not adopted. No runtime change.
4. Never change `BE_TRIGGER_R` / `MAX_HOLD_MINUTES` / ATR bounds / blackouts /
   session windows without a pre-registered bar + REVIEW/ANALYSIS doc.

### Command cheat sheet

| Goal | Command |
|------|---------|
| Integrity first | `python3 tools/check_data.py` |
| Era / WR / ratchet grid | `python3 tools/win_rate_report.py` |
| Falling-gold / side regime check | `python3 tools/momentum_regime.py` |
| Blocked-signal phantoms | `python3 tools/phantom_trades.py` |
| Gate replay (ledger-side, cascade-ignorant — descriptive only) | `python3 tools/validate_gates.py` |
| **Any exit/gate/param counterfactual** | `python3 tools/strategy_lab.py --table --only baseline,<variant>` |
| Replay-vs-production recall | `python3 tools/strategy_lab.py --calib-only` |
| Stop-vs-level invariant | `python3 tools/check_structural_stop.py` |
| Loser features | `python3 tools/analyze_losers.py` |
| Engine regression | `python3 tools/smoke_test.py` |
| Force autosync now | `sudo /opt/gold/tools/autosync.sh` |
| Live state | `cat /opt/gold/status.json` |
| Engine service | `systemctl status goldbot` (or unit that runs `engine.py` under `/opt/gold`) |
| Autosync log | `tail -80 /var/log/gold_autosync.log` |

### Do not

- Pool **decisive WR** across the 09-15 ratchet change without naming the era.
- Key BE reconstruction only on `Exit_Reason == "BE"` — use **geometry**
  (`Stop_Loss == Entry_Price`), and recover the pre-ratchet risk from the **reward leg**
  (`|TP − Entry| ÷ 1.5`), **not** from `ATR_At_Entry`: since 2026-10-05 the stop is
  structural, so `2·ATR` understates risk on level-bound trades (§8).
- Decide an exit/ratchet/stop change from `exit_sims.py`, `pathwalk_sims.py` or
  `phantom_trades.py` — they are **cascade-ignorant** (one position,
  cooldown and breaker state are not modelled). Use `tools/strategy_lab.py` (§7).
- Stack a second runtime change on the open **struct-stop window** (entries ≥ 2026-10-05
  21:00 UTC): one variable at a time, and its bar is already written (§6 item 1).
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
| 2026-10-05 (1st) | Scheduled max-hold re-review (`docs/REVIEW-2026-10-05.md`): isolation closed at n=209, fallback step-2 trigger met, `H-side-awareness` dropped, session-band candidate named. **No runtime change** |
| 2026-10-05 ~21:00 | **STRUCTURAL STOP live**: `SL_CLEAR_ATR = 0.5` + TP = 1.5 × actual risk (`engine.py`). One variable; **new isolation window** (entries ≥ cutover). Evidence + pre-registered bar: `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` |

## 1. Where things stand (as of **2026-10-05, 21:15 UTC — second session today**)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`. This session is on
  `arena/bf9e984a-gold-trading-bot` and **it ships one runtime change**: the
  **structural stop** (`SL_CLEAR_ATR`/`RR_TARGET` in `engine.py`, §4) plus the
  costed/stateful replay harness that was the stated blocker for judging exit
  changes (`tools/strategy_lab.py`) and a geometry guard (`tools/check_structural_stop.py`).
  Everything else — entries, gates, ratchet trigger, max-hold, lot, mode — is untouched.
  Read `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` (evidence + the pre-registered bar)
  and `docs/REVIEW-2026-10-05.md` (earlier verdict) before proposing anything else.
- Historical deploys unchanged: **PR #15 MERGED** (09-21, `MAX_HOLD_MINUTES =
  240` live ~06:00); **PR #9** (09-15) BE 0.30→0.75R; **PR #7** (09-10) ratchet
  + BUY-only London blackout + trend-side daily breaker. Production-host
  hardening/verification still **not performed** (§6 item 0).
- Current ledger (data collection 181, commit `d8f8905`; **not frozen**, §1a):
  **493 closed / 0 active**, 84W / 208L / 200BE / **1 TIME** → **28.8% decisive**
  [23.9–34.2], paper P&L from $500 **−$308.91 → $208.05**, **−0.163R/trade**
  (avg 1R $3.84), payoff 1.51, scratch rate 40.6%. Integrity **0 fail / 8 warn**;
  synthetic smoke **A–N passed** (Scenario L also fixed: it read the real wall clock and went
  red between 21:00–01:59 UTC). October 5 is a **partial day**; the last trade (#494) exited
  10-05 18:34 under the OLD geometry.
  - **0.75R master book** (entries ≥09-15 06:00): **n=318**, 66W/149L/102BE/1TIME,
    **30.7% decisive** [24.9–37.2], **−$0.581/trade = −0.155R**, −$10.26/calendar day,
    17.7 entries/day; original −$0.40 falsification bar remains tripped (formally since 09-17).
  - **Max-hold era** (entries ≥09-21 06:00, re-reviewed 10-05): **n=223**,
    46W/108L/68BE/**1TIME**, **29.9% decisive** [23.2–37.5],
    **−$0.646/trade = −$11.08/calendar day**, 17.2 entries/day.
    **Isolation closed; the 240-min cap never bound an in-session trade**
    (longest non-TIME hold **68.0 min**). The single TIME exit is the
    **weekend-gap hold #476** (SELL Fri 10-02 20:56 → Sun 10-04 22:00, 49.1 h
    wall-clock, −$1.52) — the cap cannot fire while the market is closed, so
    positions can ride a daily/weekly closure with an unenforceable stop
    (LIVE risk). Keep the cap; it is inert on this sample, not the cause of the
    SL cluster.
  - 0.30R era unchanged: n=130, 10W/22L/98BE, 31.2% decisive, −$0.321/trade.
    Pre-ratchet: n=45, 17.8%, −$1.834/trade. 0.75R pre-maxhold: n=95, 32.8%,
    −$0.427/trade.
- **Fallback step-2 (ratchet-off) is now ANSWERABLE and the answer is no.** The trigger was met
  (n=209 → now n=223, −$0.646/trade ≤ −$0.40) and the blocker was the missing
  costed/stateful/era-matched harness — that harness exists now (`tools/strategy_lab.py`, funnel
  recall 99.7–100% per era). Its verdict: ratchet-off gross is ≈ breakeven (−0.052R), it works
  only by deleting the scratch bucket (**61.7% of trades become full stop-outs** vs 45.4% today),
  and **stacked on the shipped structural stop it adds nothing (−0.131R vs −0.124R)**.
  **Recommendation: drop step 2 rather than spend an isolation slot on it** (owner may override;
  never back to 0.30R). See `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §8(e).
- **`H-side-awareness` DROPPED (10-05, its own bar):** (a) 27 decisive in the
  60-min counter-trend bucket ≥25 ✔; **(b) FAIL** — 60-min aligned BUY better
  (+8.1 pp) but aligned SELL worse (−6.4 pp), and the failing side flips at
  240 min; **(c) FAIL** — no rising-gold sub-period supplies the comparison.
  No BUY ban / SELL-only / momentum gate. BUY-side bleed is observation only:
  max-hold BUY n=92, 24.6% decisive, −$1.306/trade vs SELL 35.7%, +$0.008,
  Fisher p=0.2031 (**weaker** than the 10-01 p=0.1137).
- **Session-band candidate DOWNGRADED (10-05, second session).** It was measured costed and
  cascade-aware for the first time: baseline replay Asia/rollover +0.022R vs London/NY −0.246R
  (gap 0.268R) — but under the structural stop the same split is +0.001R vs −0.084R (**gap
  0.085R**). The band was mostly a **proxy for the stop-geometry defect** (wider LDN/NY tape puts
  a 2·ATR stop inside the level more often), so it fails REVIEW-2026-10-05 §5a's own
  independence clause (b) and must NOT be stacked on the current window. The older
  ledger-only figures (39.8% vs 25.4% dec, pooled Fisher p=0.034) stand as description, not as
  a tradeable gate.
- **Ledger description, unchanged by today:** the master-era bleed is still
  Asia/rollover-better (125 trades 39.8% dec, +$0.258/trade) than London/NY (179, 25.4%,
  −$1.073) and BUY (24.5% dec all-time, −$0.995/trade) worse than SELL (33.3%, −$0.265).
- Candidate refresh done era-correct **and risk-normalized** (R = Profit ÷
  2·ATR): **RSI≥45 still dropped** (−0.151R keep vs −0.135R skip master);
  **MAX_ATR 4.50→2.50 normalized-rejected** (−0.146R vs −0.143R — the dollar
  gap was position risk; ATR≥2.0 actually beats ATR<2.0 in R); **ATR<2.0
  rejected**; **post-BE <5-min same-side re-entry** is the strongest queued
  candidate (−0.325R vs −0.104R master; −0.389R vs −0.111R max-hold) but stays
  observational pending the stateful cascade replay + a pre-registered bar.
- **ANALYSIS-2026-10-01 §4 tool corrections — now mostly covered by
  `tools/strategy_lab.py`, which is the canonical replay for exit/gate decisions:** cost model
  on every exit including BE ✓, SL-streak + wall-clock cascade with production semantics ✓
  (block only while the *last closed trade* was an SL; escalation at streak ≥ 2; daily breaker
  counted by `Exit_Time`), direction-aware blackouts + era-correct gates ✓, era labelling ✓,
  per-era funnel recall as a self-check ✓. **Still open:** MFE/MAE alignment + era labels in
  `analyze_losers.py`; decisive-WR labels + current-rule fallbacks in `pathwalk_sims.py` /
  `phantom_trades.py`; `validate_gates.py` still replays gates ledger-side (cascade-ignorant).
  Those tools remain descriptive only — their simulated profit must not pick a change.
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

**Current stance (2026-10-05, end of day):** Edge is **not confirmed** — and today's
change does not claim one. The pre-change book (0.75R master −$0.581/trade, max-hold
−$0.646) still loses before realistic costs, and the costed replay of the new geometry is
still negative (−0.106R at $0.30 round trip); it halves the bleed and removes a mechanical
defect (a stop that sat inside the level the entry was anchored to), which is why it shipped.
**First real measurement is a pre-registered forward read at n≥100 (~2026-10-19), never
before** — bar and revert triggers in `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7.
The **10-05 re-review is complete**
(`docs/REVIEW-2026-10-05.md`): isolation closed at n=209, the max-hold cap
never bound an in-session trade, and the fallback **step-2 trigger is met** —
so a **ratchet-off experiment is eligible but not approved**: it needs the
costed/stateful harness and an explicit pre-registration + sign-off first.
`H-side-awareness` is **dropped** on its own terms. New candidate (not
adopted): the London/NY session-band bleed. **No runtime change was made or
adopted at the 10-05 *scheduled review* (that review changed nothing).** The structural
stop is the first runtime change since 09-21 and it is a **reversible experiment**: one
commit, `git revert` if the bar fails. Stay paper-only and do **not** treat the bot as
income. Capital decisions remain evidence-gated, not promised by the existing
calendar timeline (§11).

### Definitions (binding)

| Term | Meaning |
|------|---------|
| **Decisive WR** | TP / (TP + SL). **Excludes** BE and TIME. |
| **BE exit** | Scratch: SL was ratcheted to entry; P&L ≈ $0. Neutral for WR, cooldown, daily breaker. |
| **TIME exit** | Max-hold close (`MAX_HOLD_MINUTES`). Neutral bucket like BE (own counter; excluded from decisive WR; ignored by SL streak / daily breaker). |
| **0.75R era** | Entries with `Entry_Time ≥ 2026-09-15 06:00 UTC` (PR #9 deploy). |
| **Max-hold era** | Entries after max-hold deploy (~2026-09-21 06:00 UTC autosync). **No counter reset** — falsification bar stays on the whole 0.75R book. |
| **Ratchet geometry** | Reconstruct original SL/TP from `ATR_At_Entry` when `Stop_Loss == Entry_Price` (never key only on `Exit_Reason == "BE"` — some TPs also show that geometry). |
| **R/trade (Rmult)** | `Profit ÷ actual risk`. Actual risk = \|Entry − Stop\|, recovered from the **reward leg** (`\|TP − Entry\| ÷ 1.5`) on rows whose stop was ratcheted to entry — never from `Exit_Reason == "BE"` alone. `tools/strategy_lab.py` and `tools/win_rate_report.py` both do this. **Backward-compatible:** before 2026-10-05 the engine always set risk = 2·ATR, so `Profit ÷ (2·ATR_At_Entry)` gives the identical number on every historical row (that was the definition used in REVIEW-2026-10-05); the two only diverge once `SL_CLEAR_ATR` can bind. |
| **Structural stop / level-bound** | The stop is set by the 20-bar level rather than by `ATR_SL_MULT·ATR` (replay share under the new rule: **80.2%**). Checkable on any era with `tools/check_structural_stop.py`. |
| **Clearance** | ATR by which the stop sits BEYOND the tested level (positive = the level must break for the stop to print). Pre-2026-10-05 median was **−0.42 ATR** (i.e. inside, stop fires on a retest); the rule requires ≥ 0 always and ≥ `SL_CLEAR_ATR` when level-bound. |
| **Session band** | Entry hour in UTC: "Asia/rollover" = 23:00–06:59; "London/NY" = 07:00–22:59. Named 2026-10-05 §5a; **downgraded later the same day** — costed/cascade-aware replay shows the gap collapses from 0.268R to 0.085R once the stop is structural (it was a proxy for stop geometry). Never a live gate. |
| **Struct-stop era** | Entries ≥ **2026-10-05 21:00 UTC**. A real isolation window (the rule changed), unlike the max-hold deploy which did not reset the counter. Judge per `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7 at n≥100; n<60 is not a result in either direction. |

## 2. Bot in one paragraph

Simulated XAUUSD scalper on 1-min candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥38% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar slope, one-sided 0.3·ATR EMA50 buffer),
RSI BUY 30–68 / SELL 32–70, ATR 1.10–4.50.
Exits: SL = entry ∓ **max(2·ATR, distance to the tested level + 0.5·ATR)**, TP = entry ∓
1.5 × that risk (1:1.5 held against the *actual* stop; identical to the old 3·ATR whenever the
level does not bind — 2026-10-05, §4/§5), plus a breakeven ratchet
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
| `ATR_SL_MULT` / `ATR_TP_MULT` | 2.0 / 3.0 (TP = `RR_TARGET` × **actual** risk) | `engine.py` |
| `SL_CLEAR_ATR` / `RR_TARGET` | **0.5 / 1.5** (live 2026-10-05 21:00; pre-cutover books have neither) | `engine.py` |
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

Engine: **structural stop** (live 2026-10-05 21:00, `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`).
`risk = max(ATR_SL_MULT·ATR, |entry − level| + SL_CLEAR_ATR·ATR)` where `level` is the same
20-bar floor/ceiling the rejection gate was measured against; `take_profit = RR_TARGET·risk`.
Why: the level test's tolerance is price-% (`FLOOR_BUFFER_PCT = 0.0020` ≈ $8.30 ≈ **4.5×** the
median ATR) so it passes on 86.9% of bars, entries fill a median **2.42 ATR** from the level,
and a plain 2·ATR stop therefore sat **inside** the range on **63.8%** of the 0.75R master book
— 63.8% of SL exits needed no structural break at all (median SL lifetime 7.2 min). Guarded by
`tools/smoke_test.py` Scenario N and checkable on any era with
`python3 tools/check_structural_stop.py` (**post-cutover it must print 0**). Costed, era-matched
replay: master era n 326→217, 32.1→37.4% decisive, −0.217→−0.106R/trade, −$13.90→−$5.83/day at
$0.15/side, SL/day 8.2→5.4, maxDD $255→$175; **better in 3 of 4 eras** (worse pre-ratchet — it
needs the ratchet), and **still negative at every cost tested**. §7 of that doc is the
pre-registered bar (judge at n≥100, ~2026-10-19).

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
**Post-10-05 re-review:** the cap never bound an in-session trade in its first
14 days (longest non-TIME hold 68.0 min; n=209). It **cannot fire while the
market is closed**, so a position opened before a closure rides it — the only
TIME exit so far is #476, held 49.1 h across the 10-02→10-04 weekly close.
In LIVE mode that stop is not broker-protected across the gap; a pre-close
entry guard / flat-before-close policy is a named candidate (§5a/REVIEW-10-05
§5b), not adopted.

## 5. Evidence base (don't re-derive)

Key documents:
- `docs/REVIEW-2026-10-05.md` (**latest, analysis-only — the scheduled formal
  re-review**): max-hold isolation closed (n=209, 1 TIME, cap never bound
  in-session, −$0.570/trade) → **fallback step-2 trigger MET** (eligible, not
  approved: needs the costed harness + pre-registration + sign-off);
  `H-side-awareness` **DROPPED** (27 decisive counter-trend ✔ but within-SELL
  60-min gap −6.4 pp and the failing side flips at 240 min; no rising-gold
  sub-period supports it); candidate refresh era-correct + risk-normalized
  (RSI≥45 dropped; MAX_ATR tighten normalized-rejected; post-BE fast re-entry
  −0.325R vs −0.104R remains the strongest queued, still observational);
  **new named candidate: London/NY session-band bleed** (39.8% vs 25.4% dec,
  p=0.034, holds in-side/in-ATR/in-era/5-of-5 chunks; proposed bar 4/6, not
  registered); #476 weekend-gap finding; two analysis-tool labels corrected.
- `docs/ANALYSIS-2026-10-01-stop-loss-rate.md` (still the **cost/tooling
  reference**; its ledger numbers are that snapshot's — current numbers are §1):
  448 closed; SL/all 41.1% versus SL/decisive 70.5%; current 0.75R n=273,
  −$0.467/trade, max-hold n=178, −$0.488/trade / 0 TIME. Geometry/labels and
  current-rule replay verified; smoke A–M passed, integrity 0 fail / 8 warn.
  **No bot change justified by the percentage alone.** Next-session queue:
  verify host/feed, repair/calibrate research tools, formal isolation review,
  costed stateful ratchet-off only if approved, separate post-BE-pause test.
  Replaces stale candidate headlines, not historical review records.
- `docs/REVIEW-2026-09-29-feed-outage.md` (6-h silent starvation after
  the 08:29 reboot: evidence chain, the guard bug that hid it, the undocumented
  09-28 precursor, detection fix + ops runbook)
- `docs/ANALYSIS-2026-09-28-falling-gold-win-rate.md` ("WR improves
  when gold falls?" → **wrong cause, no adoption**: real 30.7% vs 25.0% pooled
  gap but day-level null (27.9% vs 28.1%), side-coupled (94/96%), within-BUY
  refuted (13 falling-tape BUYs = worst bucket, 15.4%), whole gap 3 days old and
  inverted in the 09-17/09-18 up-leg (BUY 45.0% vs SELL 12.5%). Registered
  `H-side-awareness` + pre-registered bar — **scored at the 10-05 re-review:
  DROPPED** (fails bar (b) within-SELL and (c) rising-gold).
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

### 5z. `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` — why the SL rate is high, and the one change that fixes it

**Read this before touching any exit parameter.** Headline findings (all reproducible, §10 of
that doc):

- The level test is **inert**: `FLOOR_BUFFER_PCT = 0.0020` is a *price-%* tolerance, ≈ $8.30 on
  a $4,150 market ≈ **4.5× the median ATR (1.83)**. `Tested_Floor` is true on 86.9% of logged
  bars and 44.5% of the bars that pass it close >2 ATR *above* the level.
- Therefore the stop is **not structural**: median |entry − level| = **2.42 ATR**, so a 2·ATR
  stop sits inside the range (median 0.42 ATR short of it) on **63.8%** of the 0.75R master
  book, and **63.8% of its SL exits** were that class. Median SL lifetime **7.2 min**
  (46% ≤ 7 min, 97.6% ≤ 30 min of a 240-min budget); only 22.3% of trades touched +1·ATR first.
- **Shipped:** stop must clear the level (`SL_CLEAR_ATR = 0.5`), TP = 1.5 × the actual risk.
  Costed replay (master era, $0.15/side): −0.217 → **−0.106R**/trade, −$13.90 → −$5.83/day,
  decisive 32.1 → 37.4%, SL/day 8.2 → 5.4, scratches 33 → 25%, maxDD $255 → $175, 3 of 4 eras
  better (worse pre-ratchet: it needs the ratchet). 0 of 217 post-change trades have a stop
  inside their level (210 of 326 before).
- **Costs of it:** −33% trade flow (occupancy/cooldown, not a gate change), avg SL −$4.20 →
  −$6.80, holds 10 → 22 min (TIME 1 → 7, so more closure-gap exposure), the daily-loss breaker
  fires less (it counts SLs), and expectancy is **still negative at every cost level tested**.
- **Rejected on this data (do not re-derive):** ATR-rescaling the level test (era-unstable,
  0 winners of 21 decisive in the 0.30R slice; and the near-miss bucket is the *worst* of all at
  14.3% dec / −0.409R), stop-only widening that degrades the ratio (49.1% WR but −0.107R),
  min-SL 2.5/3.0/3.5 ATR with RR held (WR up to 50.7%, expectancy flat-to-worse), min-SL
  1.5/1.0 (−0.257/−0.425R), ratchet-off (≈breakeven gross, 61.7% SL share, redundant next to
  the stop fix), the session band (§1), and stacking the entry tolerance on top (≡ the stop fix
  alone).

## 6. Next steps (in order)

0. **Ops verification first (still open):** CSV collection advances through
   10-05 02:59 and shows no new outage signature (only the normal daily break,
   one 8-min gap and the weekly close), but confirm the heartbeat/alerts/dedup
   deployment and `mt5.service` hardening **on the production host**. Runbook +
   drop-in in `docs/REVIEW-2026-09-29-feed-outage.md` §7 (`Restart=always`,
   `TimeoutStopSec=30`, `KillMode=control-group`, `systemctl enable`). Recover
   the terminal only if it is stalled; do not infer a fresh outage from a
   cloned snapshot's age. Check `mt5_last_candle.json` mtime/`updated_at`, live
   status/log progression, `📈 candles: ok` and journal recovery/health lines.
   Server access/deployment was **not** verified in 10-01 or 10-05.
   **Research prerequisite (DELIVERED 10-05):** `tools/strategy_lab.py` is the costed,
   stateful, era-matched, direction-aware replay the 10-01 §4 list demanded (funnel recall
   99.7–100% per era; cost on every exit incl. BE; production cooldown/breaker semantics).
   Era/pooling labels in `win_rate_report.py` and the false long-hold warning in `check_data.py`
   were fixed earlier the same day. Remaining §4 items are cosmetic-for-decisions (MFE/MAE
   alignment in `analyze_losers.py`, decisive-WR labels in `pathwalk_sims.py`/`phantom_trades.py`)
   but those tools stay **descriptive only**.
   Calibrate each era's actual rule before trusting any hypothetical P&L.
   Tools-only validation does not authorise runtime/strategy changes.
1. **🔒 STRUCT-STOP WINDOW IS OPEN — do not touch exits until it is judged.** The only live
   experiment: entries ≥ 2026-10-05 21:00 UTC use `SL_CLEAR_ATR = 0.5` + `RR_TARGET` TP.
   Sequence (from `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7): **(a)** after the first
   ~10–20 trades run `python3 tools/check_structural_stop.py --since 2026-10-05` — the
   "stop inside level" count **must be 0** and `--calib-only` must still show ~100% recall
   (if either fails it is a code/harness bug, not a strategy result); **(b)** judge expectancy
   only at **n ≥ 100** (≈8 trading days at the expected 12 trades/day; **n < 60 is not a result**);
   **SCREEN** = R/trade ≥ −0.10R **and** decisive WR ≥ 36% **and** SL/day ≤ 6.5 **and** scratch share
   ≤ 35%. **PASS** additionally needs **n ≥ 150 with the WR's Wilson 95% LB > 32.1%** (≈40% WR — the
   uncosted 1:1.5 breakeven). REVERT (single-commit `git revert`) if R/trade ≤ −0.20R, or avg SL loss
   > 2.2× pre-change, or the era drawdown exceeds $250, or 2+ trades ride a closure gap.
   Re-review **2026-10-19 21:00 UTC** or n=150, whichever comes first. No other strategy/param
   change inside this window (that includes the session band and the level-test re-scale).
2. **Max-hold isolation: CLOSED 10-05** (`docs/REVIEW-2026-10-05.md`). Verdict:
   n=209, 1 TIME exit (the 49.1-h weekend-gap hold #476), **the cap never bound
   an in-session trade** (longest non-TIME hold 68.0 min) → keep it as cheap
   insurance, it is **not** the cause of the SL cluster. Era result −$0.570/trade,
   −$8.64/calendar day.
   **Fallback step-2 (ratchet-off): trigger was MET (n=223, −$0.646/trade), the harness
   prerequisite is now delivered, and the measured answer is NO.** It is *not* worse than the
   live baseline in isolation (−0.162R vs −0.245R pooled master, $0.20/side) — but it buys
   that only by **deleting the scratch bucket: 61.7% of trades become full stop-outs** (45.4%
   today), its gross expectancy is ≈ breakeven (−0.052R), and **stacked on the shipped
   structural stop it adds nothing: −0.131R vs −0.124R** (`--only structstop,structstop+nord`).
   Spending an isolation slot on a variant that is redundant once the stop is fixed is not
   worth 2+ weeks. **Recommendation: close step 2.** Owner may override with a pre-registered
   bar; **never** back to 0.30R either way.
3. **Queued strategy changes** — refreshed 10-05; candidates only, no adoption
   (all numbers 0.75R master / max-hold era; `R` = Profit ÷ 2·ATR, which equals actual risk
   on every pre-2026-10-05 row — see Definitions):
   - (a) **RSI ≥45 — remains DROPPED.** keep 31.0% dec / −0.151R vs skip
     32.5% / −0.135R (max-hold: −0.175R vs −0.135R). The skip bucket is better
     in both books. Do not reopen without a new era-correct pre-registration.
   - (b) **BE resets the SL streak** (cooldown de-escalation) — still queued,
     still **down-graded** (FOMC escalation covered 17:28–18:28 UTC). Needs the
     calibrated cascade tool first; do not combine with a post-BE pause.
   - (c) **RISE120 entry gate — REJECTED / dropped.**
   - (d) **MAX_ATR 4.50→2.50 — NORMALIZED-REJECTED 10-05.** ATR<2.5 −0.146R vs
     ATR≥2.5 −0.143R (max-hold: −0.174R vs −0.092R); the dollar gap was
     position risk. ATR<2.0 also loses (keep −0.197R vs skip −0.063R). Drop
     unless a costed harness says otherwise.
   - (e) **Momentum / `H-side-awareness` — DROPPED 10-05** (fails bar (b) and
     (c); see REVIEW-2026-10-05 §3). No BUY ban / SELL-only / momentum gate.
     The BUY-side bleed is observation only (max-hold BUY −$1.306/trade,
     p=0.2031 — weaker than the 10-01 p=0.1137).
   - (f) **Session-band gate (London/NY bleed) — DOWNGRADED 10-05 (same day), do not
     adopt or stack.** Measured with the costed stateful harness: baseline Asia +0.022R vs
     London/NY −0.246R (gap 0.268R), but under the shipped structural stop the same split is
     +0.001R vs −0.084R (**gap 0.085R**) — the band was largely a **proxy for the stop-geometry
     defect**, so it fails REVIEW-2026-10-05 §5a's independence clause (b). Ledger-only
     description (39.8% vs 25.4% dec, pooled p=0.034) stands as history, not as a gate.
   - (g) **Post-BE <5-min same-side re-entry pause — strongest queued
     entry candidate.** master −0.325R vs −0.104R (n=57); max-hold −0.389R vs
     −0.111R (n=36). Observational only: needs the stateful cascade replay and
     a pre-registered bar; separate from the SL-streak change.
   - (i) **Level-test re-scale (`FLOOR_BUFFER_PCT` price-% → 0.15–0.25 ATR) — REGISTERED,
     NOT adopted.** It is the single largest replay lever found (pooled all-eras bleed
     −12.4 → −2.1 $/day at $0.30 rt, n 563 → 137; master-era `sweep` 45.3% dec +0.091R gross)
     but it is **era-unstable** (0 winners of 21 decisive in the 0.30R slice; −0.273R vs
     −0.154R in 0.75R pre-max-hold) and it cuts flow to ~5 trades/day, so a judgement needs
     ~4 weeks. Reproduce with `tools/strategy_lab.py --grid level`. It may only be registered
     **after** the struct-stop window closes, and it must not be stacked with it.
   - (h) **Pre-close entry guard / flat-before-close** — NEW, named 10-05 from
     the #476 weekend hold (§REVIEW-10-05 §5b). Pair with the LIVE-mode work;
     not adopted. A **scheduled-news gate** remains a named unadopted candidate.
   - Ratchet falsification: **TRIPPED** (09-17, −$0.595 at n=60; now −$0.581 at
     n=318 master). Max-hold fallback delivered **no** improvement to blame or
     credit (§1). Step 2 (ratchet-off) measured 10-05 and **rejected** — see above.

4. Historical research (optional, later): use `tools/mt5_history_dump.py`
   once you want to stress-test candidate filters on multi-year data. A
   replay-driven change of this size is exactly what multi-year data is for.

5. LIVE-mode broker-side BE modify — only if/when switching to real orders.
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
python3 tools/strategy_lab.py --calib-only        # funnel recall must stay ~100% per era
python3 tools/check_structural_stop.py            # stop-vs-level invariant (post-10-05: 0)
```

Note: `tools/` scripts are NOT covered by smoke_test.py and several of them
have historically crashed or lied on new data shapes (2026-09-15: ZeroDivision
on ratcheted-stop rows, inverted SELL bars in pathwalk). Run them after every
data drop, not just after code changes.

- **Exit / stop / TP geometry changes** must additionally (a) be replayed costed and stateful
  with `python3 tools/strategy_lab.py --table --only baseline,<new-variant>` across **all four
  parameter eras** — a variant that wins in one era is noise, and `exit_sims.py` /
  `pathwalk_sims.py` / `phantom_trades.py` are cascade-ignorant and must not
  decide them; (b) carry a mechanical invariant checkable from the ledger alone
  (`tools/check_structural_stop.py` for stop-vs-level) — a code fact is a far stronger early
  signal than expectancy at n=20; and (c) be mirrored in a smoke Scenario. Bar shape:
  `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7.
- **Smoke tests must not read the wall clock.** Scenario L (`mt5_feed_problem` quiet-hours) did;
  it passed in market hours and failed at 00:09 UTC on 10-05 on a *clean* checkout. It is now
  pinned inside the scenario. If a scenario goes red only between 21:00–01:59 UTC or at a
  weekend, suspect the test before the code.

## 8. Data gotchas (hard-won)

- `trades.csv` has historical Trade_Num resets — dedupe by timestamp.
- **Ratcheted rows** log the *live* stop: at the 10-01 snapshot,
  `Stop_Loss == Entry_Price` on **256 rows: 187 BE + 69 TP**. Reconstruct the original
  geometry from the **reward leg**, not from the ATR multiple: `risk = |TP − Entry| ÷ 1.5`
  (the ratchet never touches TP). That is exact in **both** regimes — pre-2026-10-05 it
  reproduces risk = 2·ATR, after it the level-bound risk (median 3.07 ATR) — whereas
  `entry ∓ 2·ATR` silently *understates* risk on every level-bound trade and would inflate
  apparent R. `win_rate_report.py`, `check_structural_stop.py` and `strategy_lab.py` all use the
  TP-leg rule. For exact baseline calibration, preserve the logged target and account for
  ATR/price rounding; see ANALYSIS-2026-10-01 §4.
- **A %-expressed price tolerance is not a constant in ATR terms.** `FLOOR_BUFFER_PCT = 0.0020`
  looked like "0.2%, basically at the level" but on a $4,150 metal that is ~$8.30 ≈ 4.5× the
  median ATR, and it silently disabled the entry gate (86.9% of bars pass) — see
  ANALYSIS-2026-10-05 §2. Every threshold in this funnel must be ATR-scaled; the corollary is
  that a change whose *benefit* comes from an ATR-relative distance will read differently as
  the metal's price drifts, so re-check these numbers after a large regime/price move.
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
- **Dollars measure position size, not signal.** ATR varies 1.10–4.50, so a
  $/trade gap can be pure risk-sizing (the MAX_ATR candidate died exactly this
  way on 10-05). Normalize: `R = Profit ÷ (2·ATR_At_Entry)` before comparing
  buckets, and still cost the result.
- **The 240-min TIME stop cannot fire while the market is closed** and closes
  on the first candle/tick back: a position can ride a daily/weekly closure
  (#476: 49.1 h wall-clock, −$1.52 on the Sunday reopen). Do not read a long
  hold as "the cap failed", and do not assume the stop is enforceable across a
  gap in LIVE.
- `tools/analyze_losers.py` prints "Skip 23:00-06:59 UTC (Asia/rollover)" with
  keep = the **London/NY** book. Read keep/skip labels carefully — the *skipped*
  199-trade bucket was the better one (10-05 §5a).

## 9. Architecture quick map

```
engine.py          signals + structural stop + BE ratchet + max-hold TIME + state machine
trade_filter.py    portfolio gates (cooldown, daily breaker, blackouts, ATR)
dashboard.py       Flask status page (read-only)
tools/strategy_lab.py   canonical costed/stateful/era-matched replay (exit+gate decisions)
tools/check_structural_stop.py  ledger-side invariant guard for the 2026-10-05 change
tools/             other analysis / integrity / report scripts (not on the hot path)
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
3. Before ending: update §1 numbers, §4/§5 if params/evidence moved, §6 next steps, the
   era-timeline table (top of file) and `archive/PROJECT_LOG.md`. A runtime change is not
   "done" until its **pre-registered bar exists in a dated doc** — write the bar before any
   post-change trade can be judged, and never re-slice eras afterwards to rescue it.
4. Never leave conclusions in chat only — land them in this file or a dated REVIEW.

**Auto-trade timeline (unchanged)**

| Horizon          | Gate                              | Action |
|------------------|-----------------------------------|--------|
| Now              | Edge not confirmed                | Paper-only |
| ~~~2 weeks (10-05) / n≈200~~ | ~~Max-hold re-review~~ **DONE 10-05** | Isolation closed (n=209, cap inert); `H-side-awareness` dropped; step-2 trigger met but **not approved** |
| ~~Next (gated)~~ | ~~Ratchet-off experiment approved?~~ **CLOSED 10-05** | Harness delivered (`tools/strategy_lab.py`); measured answer is **no** (≈breakeven gross, 61.7% full stop-outs, redundant next to the structural stop: −0.131R vs −0.124R). Session-band candidate downgraded in the same pass. Never back to 0.30R either way |
| **2026-10-19 (or n=150)** | **Judge the structural stop** | `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7: invariant checks first (`tools/check_structural_stop.py` must print 0), then SCREEN at n≥100 (R/trade ≥ −0.10R + WR ≥ 36% + SL/day ≤ 6.5 + scratch ≤ 35%) and PASS only at n≥150 (Wilson LB of WR > 32.1%); REVERT triggers include R/trade ≤ −0.20R and era drawdown > $250. **No other exit/param change in this window** |
| ~2–4 weeks       | Judge the new ratchet level       | Superseded 10-05: ratchet stays at 0.75R (step-2 experiment closed, §5.1 fallback); re-run the suite anyway — P&L/day + bleed/trade + R/trade, never WR alone |
| ~2–4 months      | 100+ trades, multiple regimes     | First serious evaluation of edge            |
| 6–12 months      | Durable positive expectancy?      | Decide if it deserves any real capital      |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
