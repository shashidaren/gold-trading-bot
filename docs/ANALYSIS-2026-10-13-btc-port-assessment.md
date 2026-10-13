# ANALYSIS 2026-10-13 — what the bitcoin-trading-bot improvements mean for gold

**Asking question (owner):** *"given what we did for our bitcoin trading bot updates in docs/HANDOFF.MD,
do you think we can have some improvements on my gold trading bot as well … dont create a PR until we
can finalise everything."*

| | |
|---|---|
| **Compared** | `shashidaren/bitcoin-trading-bot` `main` @ `cbc9240` (`docs/HANDOFF.md`, PRs #1–#20, #19 still open) against this repo @ `91333ca` (data collection 226) |
| **Gold data at judgement time** | 575 closed, 110W/248L/215BE/2TIME = **30.7% decisive** [26.2–35.7]; paper P&L from $500 −$319.51 → $180.49 (**gross**) and **−$549.51 at the assumed $0.20/side**; open SELL #577 verified *not* stuck (price has touched neither SL 4189.49 nor TP 4172.28 since entry) |
| **Shipped on this branch** | tooling, docs and ops only (§3 "DONE"). **No** `engine.py` / `trade_filter.py` / `dashboard.py` change; no parameter, gate, exit or strategy change |
| **Not claimed** | nothing here is evidence of edge. The struct-stop window is still open and still below its n=100 screen |

---

## 0. Answer in five sentences

Yes — but what transfers from BTC is **measurement, guard-rails and process, not strategy**, and the most
valuable finding was a defect in gold's own guard, not something BTC did. Porting BTC's machine-checked
handoff meant checking gold's docs against gold's data, which showed the pre-registered struct-stop invariant
(A1) was **failing on live data** because the cutover was dated 6 h early — the 10-19 review would have opened
on a red A1 that HANDOFF §6.1(a) defines as "a code/harness bug", and whose REVERT row treats a post-cutover
stop inside its level as a code regression — and that the replay harness used a 19-bar level where the engine
uses 20. Both are fixed in tooling (the guard now passes on n=78 and *proves* the deploy boundary from the
ledger); gold's 8-day-stale handoff is now announced in every autosync digest. What BTC has that gold still
lacks and should get next is **measured costs** and a **large-N history path** — but none of that, and none
of BTC's engine-side fixes, may touch the runtime until the struct-stop window is judged
(2026-10-19 21:00 UTC or n=150, HANDOFF §6 item 1).

---

## 1. What BTC changed, and where gold stood

| # | BTC improvement | BTC PR | What it does | Gold before this branch |
|---|---|---|---|---|
| 1 | Machine-checked HANDOFF snapshot + digest line | #6 (09-16) | `tools/handoff_check.py` recomputes a marked block from the CSVs, says FRESH/STALE; autosync shows it | none — §1 said "493 closed, as of 10-05"; box had 575 |
| 2 | `docs/AUTOSYNC.md` runbook | 09-15 (`0d3f00e`) | install checklist, main-only deploy rule, digest legend | `autosync.sh` header pointed at a file that did not exist |
| 3 | Net-of-cost convention, `--spread` | #3 (09-15), #6 | every P/L quoted net of the *measured* round trip unless marked gross | ledger/prose gross; cost assumed (`strategy_lab` $0.20/side) and never measured |
| 4 | Autosync `NOTIFY=alerts` | #7 (09-17) | deploys + incident *changes* immediately, one `(daily)` digest, repeats deduped | `always`/`quiet` only: 8 digests a day |
| 5 | MT5 server-time → UTC | #11 (10-01) | feed sidecar learns the whole-hour broker offset, publishes UTC `ts` | feed publishes broker-server `ts` (see F4) |
| 6 | Closed-candle exit fills | #14 (10-05) | a stop gap fills at the candle **open** if the bar opens through the stop | candle-range resolution exists (`resolve_open_trade_on_candle`) but fills at the stop level |
| 7 | Daily-loss breaker reads the whole UTC day | #3 (`DAY_WINDOW = 400`) | breaker must see every SL of the day, not the last 30 rows | reads 30 rows (see F3) |
| 8 | Large-N history back-test | #18 (10-13) | `history_to_log` / `backtest` / `replay_lib`: frozen gates over months of bars | `mt5_history_dump.py` exists; nothing consumes it (HANDOFF §6.4, "optional, later") |
| 9 | XM quote + contract-spec logger | #10 (10-01) | read-only Wine sidecar logs bid/ask/spread every 30 s, contract specs, shadow candles | none — the cost model is a guess |
| 10 | `live_readiness.py` + `live_path_probe.py` | #9 (10-01) | 6 statistical go-live gates; 9 fake-MT5 probes of the LIVE order path | none (paper-only, correctly) |
| 11 | Demo order executor, START-LEVER1, GO-LIVE-WINDOW | #19 (open), #20, #17 | staged path to a micro-live window | none |
| 12 | `reconcile_stale_trade.py` | #15 (10-05; #12/#13 docs) | repairs a paper trade stuck open past a touched barrier | none; no stuck trade exists (#577 checked) |

---

## 2. Findings made while checking gold against BTC (all reproduced; commands in §6)

### F1 — The struct-stop guard was red on a change that is working

`ANALYSIS-2026-10-05` §7 A1 requires `check_structural_stop.py` → "stop INSIDE level" **= 0** after the
cutover; HANDOFF §6.1(a) says a failure "is a code/harness bug, not a strategy result", and the REVERT row
lists *"any post-cutover trade has a stop inside its level after A1 was shown to work (a code regression)"*.
A1 had never been run (no session since 10-05). Run on today's data the tool printed **FAIL: 3 post-cutover
trades** (#495, #497, #498). They are not an engine regression — the cutover constant was wrong, and the
10-19 review would have started by hunting a regression that does not exist (or, worse, by reverting a change
that is doing what it was built to do):

| Event | UTC | Evidence |
|---|---|---|
| Cutover promised by the docs / `strategy_lab.LIVE_CUTOVER` | 2026-10-05 21:00 | the plan ("next autosync") |
| PR #28 merged | 2026-10-06 00:31:53 | `gh pr view 28` |
| **Deployed** (`autosync: merge upstream`, `2f4f4c6`) | **2026-10-06 03:00:04** | GitHub commit history of `main` |
| Last OLD-rule trade (#498, risk exactly **2.00 ATR**, level 2.9 ATR away) | 2026-10-06 02:39:09 | ledger |
| First NEW-rule trade (#499, risk 3.03 ATR = level 2.53 + 0.5) | 2026-10-06 03:33:05 | ledger |

Autosync only runs at HH:00 every 3 h, so a merge after 21:00 cannot be live at 21:00. Four trades
(#495–#498) were entered in that 6-hour gap under the **old** rule. The cutover is now
`2026-10-06 03:00 UTC` (`PLANNED_CUTOVER` keeps the old value for the record) and
`check_structural_stop.py` **proves the boundary from the ledger** (each stop is classified OLD / NEW / BOTH
rule; the deploy must sit between the last OLD-only and first NEW-only trade; a constant outside that
bracket is flagged; a failure is diagnosed as BOUNDARY ERROR vs REGRESSION). Mutation check: restoring
the 10-05 21:00 constant on the real ledger fails the guard with exactly *"BOUNDARY ERROR … move it into
(02:39:09, 03:33:05]"*.

**What the correction does to the era — disclosed in full, because it moves in the flattering direction.**
The four moved trades are 1 win, 3 losses, **−$9.90** (#495 SL −2.86, #496 SL −3.73, #497 TP +3.90,
#498 SL −7.21). Removing them from the struct-stop era:

| struct-stop era | n | W/L/BE/TIME | decisive WR | gross P&L | per trade | R/trade (gross) | SL/trading day | era drawdown below start |
|---|---|---|---|---|---|---|---|---|
| old boundary (10-05 21:00) | 82 | 26/40/15/1 | 39.4% [28.5–51.5] | −$10.60 | −$0.129 | −0.012R | 5.7 | $23.67 |
| **corrected (10-06 03:00)** | **78** | **25/37/15/1** | **40.3% [29.0–52.7]** | **−$0.70** | **−$0.009** | **+0.007R** | **5.3** | **$13.77** |

The correction is applied because the four trades *demonstrably ran the old code* (three are OLD-only by
geometry, #496 is bracketed by OLD-only trades #495 and #497 and entered 1 h 42 m before the deploy) — not
because it improves the numbers. The pre-registered thresholds in §7 are **unchanged**. Either way n is
below the n=100 screen: **none of this is a result**.

### F2 — The replay harness's level window was off by one bar

`strategy_lab.Lab` computed the 20-bar floor/ceiling as `lows[:-1]` of a window that already held the
current bar — **19** prior bars. The engine takes `list(self.lows)[-20:]` *before* appending the current bar —
**20** prior bars. Against the engine's own logged `Dynamic_Floor` (38,934 bars): the 20-bar definition
matches **99.96%**, the lab's 19-bar level only **85.97%**. The signal funnel barely noticed (the level test
has a ~$8 tolerance, recall was 99.7–100%) but every replayed *structural stop* — the whole point of the
variant — was up to ~1.6 $ tighter than the live one, and 20 of the 78 post-cutover trades classified as
"matches neither rule". Fixed (one line + a smoke check that feeds one synthetic series to the real engine
and to the lab and compares the engine's logged floor bar by bar). After the fix the lab's floor equals the
logged one on 99.81% of bars; the remaining 0.19% is a **log artifact**, not an engine fault — e.g. #550's
engine window contains a duplicated 16:03 candle that the lab de-duplicates (the engine's own floor, 4187.430,
matches the stop's implied level 4187.425; the lab's was 4187.270).

What it changes in figures the docs quote (same data, only the window differs):

| Figure | As quoted / before | Corrected |
|---|---|---|
| Stop *inside* the level, 0.75R book before the deploy | 203/318 = 63.8% (SL exits 95/149 = 63.8%) | 211/318 = **66.4%** (SL exits 99/149 = **66.4%**) |
| Median \|entry − level\| | 2.42 ATR | **2.53 ATR** |
| Funnel recall, 0.75R master / max-hold eras | 99.8% / 99.7% | **100.0% / 100.0%** |
| Replay, 0.75R master, $0.20/side: baseline → structstop R/trade | −0.202R → −0.101R | −0.209R → **−0.076R** |
| same, $/calendar-day / replay max drawdown (structstop) | −$5.91 / $188.5 | −$4.24 / $149.2 |
| "structstop better in 3 of 4 parameter eras" | pre-ratchet worse, other three better | **unchanged** (−0.104→−0.151 worse; −0.223→−0.188, −0.199→−0.050, −0.212→−0.077 better) |

Every correction moves the way the original design argued, and no conclusion in the 10-05 analysis reverses;
the doc carries an erratum instead of rewritten history. (My replication of the *old* window reproduced the
doc's 95/149 exactly and 201 vs 203 on the all-trades count — a 2-trade join difference.)

### F3 — Latent: the daily-loss breaker counts SLs among the last 30 ledger rows

`trade_filter.should_take_trade()` calls `load_recent_trades()` with the default `LOOKBACK = 30` and
`get_daily_sl_count()` counts *that window*, so on a day with more than 30 trades earlier SLs fall out of
the count and the 10-SL breaker under-fires. BTC hit the same trap and fixed it (`DAY_WINDOW = 400`; its
comment: *"gold hit 62"*). Replayed against the real ledger at every entry: the window under-counted today's SLs
at **34 entries**, but the breaker was **never silently off** (0 entries taken with a true count ≥ 10 while
production saw < 10); the only >30-trade days were 09-11 (31), 09-14 (63) and 09-15 (33), all before the
structural stop, which trades ~11 a day. **Latent, has not bitten, low urgency** — and it is a gate-behaviour
change, so it waits for the window (§4).

### F4 — `mt5_history_dump.py` labels broker-server time as UTC (and a trap for porting BTC's fix)

MT5 candle times are **broker-server epoch values**, not UTC. Gold shows it directly: `status.json`
`mt5_last_candle_ts` = 1791903480 renders as 14:58:00 while the engine's UTC wall clock reads 11:59:09 — a
**+3 h** offset (the terminal logs into XMGlobal-MT5 17; BTC's docs say XM moves between UTC+2 and UTC+3
with DST and expect the next flip around the 10-24/25 weekend — not verified for this terminal).

* **Live engine: not affected.** Log rows are stamped with the engine's UTC wall clock; the candle `ts` is only a
  dedup watermark and a heartbeat label. So BTC's PR #11 is **not needed** for the live feed.
* **Trap if ported naively:** converting the sidecar's `ts` to UTC would make every new candle look 3 h
  *older* than the persisted `mt5_last_candle_ts` watermark → the engine's dedup (`ts <= last_ts`) would drop
  about 3 hours of candles silently. Do not copy PR #11 into `mt5_feed.py` without resetting the watermark.
* **Research path: affected.** `mt5_history_dump.py` writes `ts_to_str(r["time"])` under a docstring that says
  "UTC". Any replay of that file puts the London/NY/rollover blackouts, the day boundary of the daily breaker
  and every session cut 2–3 h off, and the shift changes at the broker's DST date. This is the one place BTC's
  server-time lesson genuinely applies, and it is a prerequisite for item 8.

### F5 — The handoff was 8 days behind and nothing said so

§1 was written 10-05 21:15 UTC at 493 closed; on 10-13 the box had 575 (+82). §10 says a "daily job
refreshes §1", but the last refresh PR is **#22 (2026-09-25)**; since then only working sessions touched it.
`handoff_check.py` replayed on the 10-05 values returns *STALE: +82 trades since the snapshot* and the autosync
digest now carries the verdict (advisory — never blocks a deploy, never raises an alert line).

---

## 3. Verdict per BTC item

| # | Item | Verdict | Why |
|---|---|---|---|
| 1 | Handoff snapshot + digest line | **DONE** | `tools/handoff_check.py`, snapshot block, autosync phase 4c, smoke Scenario P. Tolerances re-calibrated (30 trades / 48 h — BTC's 5 trades would be ~7 h of gold drift and permanently STALE). Config keys tie the doc's cutover and cost to the tools |
| 2 | `AUTOSYNC.md` | **DONE** | written against gold's script; records that *the deploy time, not the plan, is the cutover* |
| 3 | Net-of-cost convention | **PARTLY DONE** | snapshot carries `cost_usd_per_side` and `net_pnl_usd_at_cost` (−$549.51 vs gross −$319.51: **the gap is what the paper engine hides**, mostly scratches paying a spread) and HANDOFF states the convention. **Queued, small:** `win_rate_report.py --spread` so the report itself can print net — a tools-only change, say the word |
| 4 | `NOTIFY=alerts` | **OWNER'S CALL — not ported** | it changes what reaches your phone. Gold's 8 digests/day are chatty, not BTC's 96-a-day flood, and `quiet` barely helps (the minute log changes every run in market hours). If you want it: port BTC's `alert_once` + daily-stamp logic, default `alerts`, keep `always` as the one-line revert; I would test it in the same sandbox harness used for phase 4c |
| 5 | Server-time → UTC | **NOT FOR THE LIVE FEED; REQUIRED FOR THE HISTORY PATH** | F4. Live engine unaffected and a naive port drops ~3 h of candles. The history path needs UTC normalisation (below, item 8) |
| 6 | Gap-aware stop fills (fill at the open if the bar opens through the stop) | **QUEUED — after the window** | paper-accounting realism for gap/closure holds (#476-type, 49 h). It is an **exit change**, it alters the era's measured P&L, and the pre-registered REVERT trigger ("avg SL loss > 2.2×") is measured on it — do not change it mid-window |
| 7 | Whole-day breaker window | **QUEUED — after the window** | F3: latent, one line (`load_recent_trades(n=400)` for the daily count), gate-behaviour change, needs its own smoke scenario |
| 8 | Large-N history back-test | **QUEUED — highest research value; tools-only, can start before 10-19** | gold's evidence is one regime (6 weeks, a falling market) and four parameter eras that overlap; a months-long history is what separates "era-unstable" from "regime-unstable" (HANDOFF §6.3(i) needs ~4 forward weeks for exactly this question). Design notes: `strategy_lab` already recomputes everything from raw OHLC, so BTC's `history_to_log` converter is **not** needed — it needs `--bars PATH`, a **UTC conversion** of `mt5_history_dump.py` output (offset + the broker's DST rule, validated against the overlap with `forward_test_log.csv` before use), the ratchet default for pre-09-10 history (the era schedule returns "no ratchet"), and a whole-history window in `--table`. Needs one dump on the host (`--bars 100000 --timeframe M1`). Honest limit (BTC's own §5): an M1 reconstruction from broker history, read rows relatively |
| 9 | XM quote + spec logger for GOLD | **QUEUED — recommended, needs your go** | the single most unmeasured number in the project. Costs are *the* gap between a −$320 and a −$550 paper book; `strategy_lab` itself warns that real GOLD spreads widen in Asia/rollover and at news while its charge is flat. Same broker and same Wine prefix as BTC's logger, so the design transfers (symbol `GOLD`, $/oz instead of $/BTC). Untestable here beyond a fake terminal, like BTC's; the 14-day clock starts at the first real row, so earlier is better |
| 10 | `live_readiness` + `live_path_probe` | **NOT NOW** | every data gate fails by construction while expectancy is negative, and HANDOFF "Do not" already forbids LIVE without broker-side BE and a costs model. Revisit when the struct-stop SCREEN/PASS is met and item 9 has data |
| 11 | Order executor / START-LEVER1 / GO-LIVE-WINDOW | **NOT FOR GOLD** | a staged path to micro-live presupposes a positive point estimate; gold has none (BTC: +$0.32/trade net, unproven; gold: −$0.96/trade at the assumed cost, −$0.04 in the *replayed* struct-stop era) |
| 12 | `reconcile_stale_trade` | **NOT NEEDED** | #577 is open and legitimately so; gold's weekend hold (#476) already resolves via the TIME exit on the first candle back. Port only if a trade is ever found open past a touched barrier |

---

## 4. Proposed order of work (everything is gated by the open struct-stop window)

**Allowed now — tools / ops / docs only, cannot disturb the experiment:**
1. **Sign off this branch** → merge → autosync deploys tools + docs (no engine restart: `CORE_CHANGED` stays 0).
2. Decide item 4 (`NOTIFY`) and item 3's `--spread` view.
3. Item 9 — say go, install the GOLD quote logger, start the cost clock.
4. Item 8 — one history dump on the host, then build the converter with the UTC check.

**2026-10-19 21:00 UTC (or n=150):** judge the structural stop with the *corrected* tools:
`check_structural_stop.py` first (A1–A5, boundary evidence), then the screen/pass bar exactly as pre-registered.

**After the judgement — one runtime PR with its own pre-registration:** items 6 and 7 (and the already-named
pre-close guard), measured on the large-N path first.

## 5. What I deliberately did not do

* Touch `engine.py`, `trade_filter.py` or `dashboard.py`, or any parameter, gate or exit — F3 and item 6
  are real, but each changes behaviour inside a pre-registered one-variable window.
* Edit the pre-registered §7 thresholds. The erratum corrects *dates and harness fidelity* only.
* Change `NOTIFY`'s default, install anything on the host, or open a PR (you asked to wait).
* Run BTC's tools against gold data: they are written against BTC's loaders and M5 geometry; the ports above
  are re-implementations against gold's loaders, tested on synthetic ledgers (smoke Scenarios O and P) and on
  the real data.

**Caveats.** Autosync was exercised in a sandbox against a local bare origin with stubbed `curl`/`systemctl`
(data-only run, full merge-and-deploy run, deliberately stale doc) — not on the production box, and the real
crontab was not inspected. The struct-stop descriptive numbers in HANDOFF §1 are n=78: below the pre-registered
n=100 screen, shown for transparency, never a verdict.

## 6. Reproduce

```bash
python3 tools/check_structural_stop.py --since 2026-10-05   # PASS + boundary evidence (bracket 02:39:09 → 03:33:05)
python3 tools/strategy_lab.py --calib-only                  # recall 100.0 / 100.0 on 0.75R / max-hold
python3 tools/strategy_lab.py --table --only baseline,structstop   # the corrected replay table
python3 tools/handoff_check.py                              # FRESH on the live data
python3 tools/smoke_test.py                                 # A–P, SMOKE TEST PASSED
git log --format='%h %cI %s' --grep 'autosync: merge upstream'   # on the host: the real deploy times
```
