# HANDOFF-HISTORY — dated session archaeology (append-only)

`docs/HANDOFF.md` §1 holds the **current** state. This file holds the dated blocks §1 replaced, newest
first. **Nothing here is current:** numbers are as of the date on the block, and every conclusion that
still matters has been carried forward into HANDOFF §1/§4/§5/§6 or a dated `REVIEW-`/`ANALYSIS-` doc.

**Read it when** you need the *why* behind a live rule or the full record of an incident — never for
numbers. For sessions before 2026-10-05, `archive/PROJECT_LOG.md` is the changelog of record.

**Add to it** by appending at the top with a dated `## ` heading, moving the block out of HANDOFF §1 in
the same commit (HANDOFF §11 rule 5). Never edit a historical block to change a conclusion — write a new
block or a REVIEW instead; that is what makes this file trustworthy. (Created 2026-10-15, when §1 was
223 lines and 92% of it was history no session had pruned.)

---

## 2026-10-15 — data refresh + struct-stop era past the n≥100 screen; HANDOFF restored

**This is HANDOFF §1 exactly as it stood on 2026-10-15**, moved here on 2026-10-16 when §1 was
rewritten in place (HANDOFF §11 rule 5). **Nothing here is current.** The numbers are as of
data collection 243–246; everything that still matters was carried forward into the 2026-10-16 §1,
and the struct-stop judgement it points at (2026-10-19 21:00 UTC) has not happened yet.

### §1 as written (2026-10-15) (as of **2026-10-15, ~14:00 UTC — data collection 243**)

### 2026-10-15 update — data refresh + struct-stop era past n=100 screen (no runtime change)

- **Snapshot refreshed.** `handoff_check.py --update` brought the machine-checked block current to 2026-10-15 11:59 UTC (data collection 243, 606 closed, no open trade). Integrity still **0 fail / 8 warn**.
- **Struct-stop era now n=109** (entries ≥ 2026-10-06 03:00 UTC). Crossed the pre-registered n≥100 screen. Outcomes: **34W / 52L / 22BE / 1TIME**; decisive WR **39.5%**; gross **−$30.23 (−$0.277/trade)**; at assumed $0.40 RT **−$0.119R/trade** (from `win_rate_report.py --spread 0.40`). Guard still **PASS** (0 stops inside level; level-bound share 82.6%, median clearance +0.50 ATR, median risk 3.23 ATR).
- **Against the pre-registered bars** (from `ANALYSIS-2026-10-05-stop-loss-geometry.md` §7, unchanged): SL events **5.2 / calendar day** (bar ≤6.5 ✔); SL share **47.7%** (bar ≤47% — still marginal ✗ by 0.7 pp); BE share **20.2%** (≤35% ✔); avg SL loss **$5.91** vs pre-change ~$3.91 = **1.51×** (revert >2.2× ✔); peak-to-trough DD in era **$76.84** (revert >$250 ✔). Gross expectancy still negative. **Not yet a PASS/FAIL judgement** — the scheduled 10-19 21:00 review (targeting n≈130) comes next; this is the first look past the screen.
- **Quote logger is collecting.** `xm_data/` has quotes-2026-10-13..15.csv + symbol_spec. Median spread **$0.55** (p95 $0.58) per oz. Report currently notes STALE (newest row ~2h old at check time — normal if market closed or logger paused). Cost model is moving from pure assumption toward measurement; full 14-day (incl. weekends) still needed before replacing the $0.20/side constant.
- **No open trade.** Last closed #607 BUY SL −$5.91. Equity (true) **$150.96** (engine ledger $167.93, drift +$16.97). Net-of-assumed-cost ledger **−$591.44**.
- **Still no runtime change.** Struct-stop window remains the only live experiment. Do not stack another change until the 10-19 review judges the bars.

### 2026-10-15 (later) — HANDOFF restored and consolidated (docs only, **no runtime change**)

- **The file had been truncated; it is restored.** The daily doc job rewrote `docs/HANDOFF.md` twice on 10-15:
  `43884e1` (14:06 UTC) wrote the single line `PLACEHOLDER - will replace`, and `072459d` (14:07 UTC) put back
  the front matter + §1 only. **§2–§11 were lost** — the gates, the evidence base, next steps, the verification
  ritual, data gotchas, architecture, the deploy runbook and the **§11 protocol itself** — along with the §1
  history blocks, `Definitions` and the 09-29 feed-outage record. **`handoff_check.py` still said FRESH** (it only
  read the snapshot block), so nothing flagged it. Content recovered from `712d106` (the 10-13 version).
- **The gate now checks structure, not just freshness.** `tools/handoff_check.py` gained `doc_structure()`:
  every `## 1.`–`## 11.` section must exist, placeholder markers are flagged, and every `§N` reference must
  resolve. `--update` **refuses to stamp a truncated file**, and smoke Scenario P covers all three rules.
- **§1 no longer accumulates.** The dated session blocks (10-13 tooling, the 10-05 state, the 09-29 outage,
  the superseded stances) moved to **`docs/HANDOFF-HISTORY.md`** (append-only, newest first); §1 keeps the
  current state and pointers only. That is the whole of the 10-15 shrinkage: 223 lines of §1 were 92% history
  that no session ever pruned. New rule 5 in §11 stops it coming back.
- **Why it matters beyond tidiness:** the file is rewritten by an automated daily job, and an 886-line / 68 KB
  document is more than that job can reliably reproduce — the truncation is a symptom of the size. A smaller
  §1 (and a hard structural gate) is the mitigation.

**Current stance (2026-10-15, later):** still **paper-only**, no runtime change. Stop-loss question answered in
`docs/ANALYSIS-2026-10-15-stop-loss-rate.md`: the replay-vs-live gap is closed (tooling fix), and the next candidate, the 0.25 ATR level test, is **pre-registered on paper** (`docs/PREREG-2026-10-15-level-test-0.25.md`) to be deployed only after the 10-19 review.

**Current stance (2026-10-15):** unchanged and still **paper-only**. Edge is **not confirmed**, and neither the
10-15 data refresh nor this docs pass claims one. The struct-stop era has crossed its pre-registered n≥100
**screen** (n=109, 39.5% decisive WR, gross −$0.277/trade, −$0.119R/trade at the assumed cost) with the
mechanical invariant **PASS**ing and every revert trigger clear, but the SL-share bar is still marginal
(47.7% vs ≤47%) and expectancy is still negative — so the judgement stays exactly where the bar put it:
the scheduled **2026-10-19 21:00 UTC review (targeting n≈130)**, thresholds as written on 10-05.
**No runtime change is stacked on the open window.** The honest one-line summary of the book: 606 closed
trades, 31.2% decisive, engine ledger **$167.93** from a $500 start (true equity $150.96, drift +$16.97),
**−$591.44** at the assumed $0.20/side — i.e. **−$0.576/trade true, −$0.976/trade at the assumed cost**.
The cost model is moving from assumption toward measurement (quote logger collecting, median spread
$0.55/oz; needs 14 days incl. two weekends) — a reason to keep measuring, not to size up.

**Dated session history is in `docs/HANDOFF-HISTORY.md`** (append-only, newest first): the 10-13 tooling
session, the 10-05 state block, the 09-29 feed outage, and the stances as written then. §1 is current-state
only — see §11 rule 5.



- **What this session did.** Branch `arena/3f12a4a6-gold-trading-bot`, **no PR yet** (the owner asked to
  finalise first). Compared gold with `bitcoin-trading-bot`'s improvements and changed **only** `tools/`,
  `deploy/` (one new unit file), `docs/`, `.gitignore`, `README.md`, `archive/PROJECT_LOG.md`. `engine.py`, `trade_filter.py`, `dashboard.py` and every
  parameter, gate and exit: **untouched**; the struct-stop window is undisturbed. Verdict per BTC item (done /
  queued / not for gold, with evidence): `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3.
- **The struct-stop cutover is 2026-10-06 03:00 UTC, not 10-05 21:00.** PR #28 merged 10-06 00:31:53 and autosync
  deployed it at 03:00:04. #495–#498 (1W/3L, −$9.90) ran the **old** rule and are **not** in the era, so the era is
  **n = 78**. The guard had been red on this: `check_structural_stop.py` now **PASSES** (A1 stop-inside-level **= 0**;
  min clearance +0.36 ATR, level-bound median +0.50; level-bound share 82.1%; median risk 3.23 ATR — all inside the
  A2/A4/A5 bars; the one level-bound trade under 0.5 ATR, #550, is a duplicated log candle, not an engine fault) and
  it now **proves the deploy boundary from the ledger** (last OLD-rule #498 02:39:09 → first NEW-rule #499 03:33:05).
  Erratum at the top of `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`; thresholds in its §7 unchanged.
- **Replay-harness fix.** `strategy_lab` took the 20-bar level over 19 prior bars; the engine uses 20 (the lab now
  equals the engine's logged `Dynamic_Floor` on 99.81% of bars, was 85.97%). Funnel recall 99.8/99.7 → **100.0/100.0**;
  quoted replay figures move the way the design argued (stop-inside-level 63.8% → 66.4%; master-era replay
  structstop −0.101R → −0.076R at $0.20/side; "better in 3 of 4 eras" unchanged). No conclusion reverses.
- **This file is now machine-checked.** The snapshot block at the top is recomputed by `tools/handoff_check.py`
  and every autosync digest carries `📝 handoff: fresh|STALE` (advisory). §1 had been **8 days / 82 trades stale**
  (it said 493 closed; the box had 575) and the "daily job" last refreshed it on 09-25 (PR #22).
- **Struct-stop era, first look — DESCRIPTIVE ONLY. n = 78 is below the pre-registered n = 100 screen; this is NOT a
  result, in either direction, and the bar is unchanged.** 25W/37L/15BE/1TIME; decisive WR **40.3%** [29.0–52.7];
  gross **−$0.70** (−$0.009/trade, **+0.007R**); **−$31.90 = −$0.409/trade at the assumed $0.40 round trip**;
  SL events **5.1/calendar day** (bar ≤ 6.5); SL share **47.4%** (bar ≤ 47% — marginal); BE share **19.2%** (≤ 35%);
  avg SL loss $5.57 vs $3.91 on the pre-change 0.75R book = **1.42×** (revert > 2.2×); era drawdown below start
  **$13.77** (revert > $250; peak-to-trough $59.67); trades open across a price-log gap **0** (revert at 2+); longest
  hold 240.1 min (the one TIME exit, #526, in-session). **Moving the four old-rule trades out flatters the era by
  $9.90 (−$10.60 → −$0.70 gross)** — disclosed with before/after numbers in the assessment, F1. Pace is ~10.7
  trades/day, so n = 100 lands ~10-15 and the **10-19 21:00 review comes first at n ≈ 130** (weekends are thin).
- **Latent, not bitten:** the daily-loss breaker counts SLs among the last 30 ledger rows (34 entries under-counted,
  never silently off) — queued for the post-window runtime PR (assessment F3).
- **Built after the first review — all tooling, deployable by autosync with no engine restart:**
  - `win_rate_report.py --spread X`: the net-of-cost view (ties to the snapshot, −$549.51 at $0.40 a round trip).
  - **The GOLD quote + contract-spec logger** — `tools/mt5_quotes.py`, `deploy/mt5quotes.service` (installs as
    `mt5quotes-gold`), `tools/xm_quote_report.py`, `tools/broker_time.py`, `docs/XM-LOGGER.md`. Read-only, privacy
    allow-lists (the repo is public), gold's closures handled (a frozen tick is a `STALE` row, never an outage, and
    never moves the learned server offset). Autosync now commits `xm_data/` and the digest has a `📡 xm logger:`
    line; a ⚠️ is raised only when the *logger* stops (newest row > 15 min old), never because gold is shut.
  - **The large-N path** — `tools/history_to_log.py` (proves the server-time → UTC conversion against the live log's
    MT5 era, **observes** a DST change inside the overlap, refuses rather than guesses), `strategy_lab --bars` /
    `--ratchet`, `docs/ACCELERATE-TESTING.md`. **Calibration, like for like** (the live struct-stop era, same window,
    zero cost): the replay gives **+0.066 R/trade** (n=77), the ledger **+0.007** (n=78) — the replay is ≈ **0.06 R/trade
    more generous than live**: inside the noise at this n (SE ≈ 0.1) but in the direction its caveats predict, so read
    absolute replay P&L as optimistic and trust only differences between rows.
  - Smoke is now **A–T, 315 checks, ~10 s, hermetic**; 62 mutations of the new code were all killed; the autosync
    wiring was exercised in a sandbox (bare origin, stubbed `curl`/`systemctl`): fresh / stale / frozen-feed /
    crashed-report / not-installed / `xm_data`-conflict cases, and — the one that matters for this very deploy — the
    **old `autosync.sh` merging its own new version mid-run finishes cleanly** (git replaces files, the running bash
    keeps the old inode). **Neither the logger nor the dump has run against a real terminal** (none exists in the
    sandbox): the first run on the box is their real validation.
- **Decided by the owner (2026-10-13):** leave `NOTIFY` as is (not ported); the `--spread` view, the logger and the
  large-N path: **build** (done above).
- **On the box, in this order — tooling-only, safe inside the window:** (1) after the merge autosync deploys
  everything (no engine restart: `CORE_CHANGED` stays 0); (2) **install `mt5quotes-gold`** (`docs/XM-LOGGER.md` §3)
  **before Sunday 2026-10-25** — the server clock changes that day and the logger's offset column is the evidence
  for the DST rule, and the cost model is still a guess (−$319.51 gross vs −$549.51 at $0.20/side) until it has
  14 days incl. 2 weekends; (3) one `mt5_history_dump.py --bars 100000 --timeframe M1`, then `history_to_log.py` and
  `strategy_lab --bars` (`docs/ACCELERATE-TESTING.md` §2) — its output shows the proof, and anything under a 90%
  exact-OHLC match is refused.

---

## 2026-10-05 (2nd session) — §1 state as it stood then (numbers are as of 10-05)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`. The 10-05 second session (branch
  `arena/bf9e984a-gold-trading-bot`, PR #28) **shipped one runtime change**: the
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
- Current ledger (**data collection 226**, last bar 2026-10-13 11:59 UTC; **not frozen**, §1a):
  **575 closed / 1 active** (SELL #577 since 10:30, SL 4189.49 / TP 4172.28, ratchet not armed — verified not
  stuck), 110W / 248L / 215BE / **2 TIME** → **30.7% decisive** [26.2–35.7], paper P&L from $500
  **−$319.51 → $180.49** (engine ledger $197.46, drift +$16.97), **−0.136R/trade** (avg 1R $4.08), payoff 1.54,
  scratch rate 37.4%. **At the assumed $0.20/side the same ledger is −$549.51 (−$0.956/trade, −0.253R)** — scratches
  pay a spread the paper engine never books. Integrity **0 fail / 8 warn**; synthetic smoke **A–T passed** (315 checks).
  The 10-05 figures this replaces: 493 closed, 28.8% decisive, −$308.91 → $208.05, −0.163R.
  - **0.75R master book** (entries ≥09-15 06:00; **now includes the struct-stop era**): **n=400**,
    92W/189L/117BE/2TIME, **32.7% decisive** [27.5–38.4], **−$195.31 = −$0.488/trade**; the part *before* the
    deploy (n=322): 67W/152L/102BE/1TIME, 30.6% [24.9–37.0], −$0.604/trade = −0.162R, 8.0 SL/trading day.
    The original −$0.40 falsification bar remains tripped (formally since 09-17).
  - **Max-hold era** (entries ≥09-21 06:00, re-reviewed 10-05, isolation closed): **n=305**,
    72W/148L/83BE/**2TIME**, **32.7% decisive** [26.9–39.2], **−$154.70 = −$0.507/trade**. The 240-min cap bound in-session
    exactly once, **#526** (10-08 BUY, ratchet armed, closed at the cap after 240.1 min, +$0.48); the other TIME exit is
    the **weekend-gap hold #476** (49.1 h, −$1.52) — the cap cannot fire while the market is closed, so positions can ride a
    daily/weekly closure with an unenforceable stop (LIVE risk).
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

---

## 2026-09-29 — 🛑 feed outage: 6 h of silent starvation (was §1a)

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

---

## Stances as written then (superseded, kept verbatim)

**Current stance (2026-10-13):** unchanged and still **paper-only**. Edge is **not confirmed** and nothing in the
10-13 session claims one — it fixed the guard, not the strategy. The struct-stop era is at n=78 with its mechanical
invariant **passing**; the pre-registered read is at n≥100 / **2026-10-19 21:00 UTC**, with the thresholds exactly as
written on 10-05. The honest one-line summary of the book: gross **−0.136R/trade** over 575 trades, **−0.253R at the
assumed cost**, with the new stop's era sitting near gross break-even on 78 trades — which is a reason to keep
measuring (and to measure the cost for real), not a reason to size up.

**Prior stance (2026-10-05, end of day):** Edge is **not confirmed** — and today's
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
