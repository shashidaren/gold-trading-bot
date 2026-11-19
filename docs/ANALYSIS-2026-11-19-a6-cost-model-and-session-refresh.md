# ANALYSIS 2026-11-19 — Session Refresh (Collection 540), A6 Repo-Side Cost Model (Spread + Swap + Sensitivity), and Host/Window Blockers

**Date:** 2026-11-19 ~10:55 UTC  
**Data:** collection 540 (`ef69c0a`), `trades.csv` **974 closed** (`211W/431L/329BE/3TIME`, open **`BUY #975 @ $3737.09`**), `forward_test_log.csv` **74,569 bars** through `2026-11-19 09:00:00 UTC`, `skipped_trades.csv` **2,174 rows**, `xm_data/` **38 quote files / 102,967 rows** (`71,174` usable; **34/14 complete UTC days, 4/2 complete weekends**).  
**Status:** Ritual refresh + **A6 repo-side cost model analysis** (spread + contract-spec swap + sensitivity re-costing of ledger and `strategy_lab.py` + out-of-sample check of B4's cost guard on `#888–#974`). **No strategy parameter, risk gate, cost constant or code path changed. No order placed. `TRADING_MODE` stays `FORWARD_TEST`.** `live_readiness.py` remains **17 PASS / 0 TODO / 3 MANUAL (`LIVE GATE: CLOSED`)**.

---

## 1. Session ritual — verified on collection 540 (`2026-11-19 09:00:00 UTC`)

| Check | Result |
|---|---|
| `tools/check_data.py` | **0 fail / 9 warn** (all documented historical warnings) — 974 closed trades, 74,569 bars (`74,570` rows with 1 skipped unparsable row), `status.json` agrees with `trades.csv` |
| `tools/handoff_check.py` | **STALE** before refresh (+87 closed trades, +7,420 bars, +177.0 h since collection 480 on `2026-11-11 23:59`, `open_trade` moved `none → BUY #975 @ 3737.09`) → refreshed with `--update` and prose rewrite in this session |
| `tools/check_structural_stop.py` | **PASS** — struct-stop era **n = 477**, **81.3%** level-bound, **0 stops inside the level**, **+0.50 ATR** median clearance, **3.20 ATR** median risk (`0/388` level-bound trades below 0.50 ATR); deploy boundary still bracketed by `#498` (`OLD`) / `#499` (`NEW`) |
| `tools/check_gap_rides.py` | Registered post-cutover closure-ride count **7** (threshold 2, was 6 at collection 480; +1 new ride `#968` on `2026-11-18`, entered 42 min before the `21:58→23:00` daily break, outside the 30-min guard cutoff). **1** reopen gapped through the stop (`#815` on `2026-11-04`, headroom `−$2.77`, scratched at BE), **0 exits worse than the stop**, **3** rides on scratch stops, **0 weekend rides** |
| `tools/pressure_report.py --root .` | Struct-stop era **n = 477** (`126W/220L/129BE/2TIME`), decisive WR **36.4% [31.5–41.6]**, gross **−0.043R/trade** (`$−0.261/trade ÷ mean 1R $6.12`, total `$−124.36`; per-trade reward-leg scale `−0.065R/trade`; decisive-only `−0.090R/trade`), SL/day **5.95**, SL share **46.12%**, scratch **27.04%**, avg SL **$5.99**, era DD **$207.87**. Bar card **B1/B2/B3/C1/C2/A4/A5 all OK**. Pressure composite remains **collinear with side** (`BUY 183 aligned / 10 mixed / 0 against`; `SELL 274 aligned / 10 mixed / 0 against`) |
| `tools/xm_quote_report.py` | **34/14 complete UTC days, 4/2 complete weekends** (`102,967` rows, `71,174` usable); spread median **$0.55/oz** (`$0.55/trade`), p90 **$0.57**, p95 **$0.57**, p99 **$0.58**, max **$2.61**; **396** matched trades mean/median **$0.55**, p90 **$0.56**, max **$1.66**; EU DST rule fits **100.00%** of `71,174` rows (`+3h` to `10-23`, `+2h` from `10-25`); spec re-captured `2026-11-19 07:55:55 UTC` (`REAL`, `1:1000`, `IOC` only, contract `100`, stops `0` pts) |
| `tools/equity_runway.py` | Engine ledger **$73.76**, true equity **$56.83** (drift `+$16.93`), era net burn **−$0.78/closed trade** at `$0.40` RT and **12.9 trades/active day** (37 active days) → **~73 closed trades (~5.7 trading days)** to `$0.00` (bootstrap 90% range **69–853 trades**, 8% of draws show no burn). Owner's signed **"no rebaseline ever — let it go negative"** policy (`2026-10-30`) stands |
| `tools/strategy_lab.py --calib-only` | Funnel entry-stream recall **100.0%** (`0.30R`), **99.9%** (`0.75R master`, `n = 799`), **99.9%** (`max-hold`, `n = 704`) |
| `tools/live_readiness.py` | **17 PASS / 0 TODO / 3 MANUAL**, `LIVE GATE: CLOSED` |
| Full test suite | `smoke_test.py` (A–AD) **PASSED**, `test_live_readiness.py` **24 OK**, `test_live_manage.py` **25 OK**, `test_live_safety.py` **28 OK**, `test_readiness_tab.py` **16 OK**, `test_dashboard_context.py` **17 OK**, `test_manual_chart.py` **32 OK**, `test_equity_runway.py` **21 OK**, `test_box_alert.py` **35 OK**, `test_box_report.py` **14 OK**, `test_box_watch.py` **6 OK**, `test_signal_outlook.py` **9 OK**, `test_repair_phantom_ledger.py` **7 OK**, `goldbot/tests` **64 OK** |

**Feed health between collection 480 (`2026-11-11 23:59`) and collection 540 (`2026-11-19 09:00`):**
- Both `forward_test_log.csv` (last bar `2026-11-19 09:00:00 UTC`) and `xm_data/quotes-2026-11-19.csv` (last row `2026-11-19 08:59:30 UTC`) are live and continuous to the collection boundary.
- Every daily break (`21:58→23:00 UTC`, 62 min) and the `2026-11-13 21:57:09 → 2026-11-15 23:00:07 UTC` weekend break (`2,943.0 min`) resumed cleanly on the first open-market minute (`23:00:07 UTC`), with **no Sunday-reopen bar hole** (only one 5.6-min open-market jitter on `2026-11-17 06:28:07 → 06:33:42 UTC`).

---

## 2. Why Step A6 is addressed here, and what remains blocked (§3 / §6 precedence)

Following `docs/EXECUTION-PLAN.md` §3 and §6:
1. **No data-integrity or feed-outage blocker exists** at collection 540.
2. **No open experiment time gate has expired yet** (`structstop1.5` is not deployed, `CLEAR15_CUTOVER = None`; see §6 below on the approaching `2026-12-01 21:00 UTC` date gate).
3. **Track A — Step A2 (`SL_CLEAR_ATR = 0.5 → 1.5` deploy) is BLOCKED:**
   - First, the latest synced snapshot has an **active open position**: **`BUY #975 @ $3737.09`** (entered `2026-11-19 05:49:07 UTC`, SL `$3727.80`, TP `$3751.03`, `be_armed: false`).
   - Second, A2 requires verifying **on the production host (`/opt/gold`)** that no position is open at deploy time and recording the host's `autosync: merge upstream` commit timestamp as `CLEAR15_CUTOVER`. That cannot be done from this sandbox checkout.
   - Steps **A3–A5** are gated on A2.
4. **Track B — Step B5 (`docs/DEMO-EVIDENCE.md`) is BLOCKED on a host/operator action:**
   - All 17 code and data checks in `tools/live_readiness.py` are **PASS (`0 TODO`)** after B2 (`2026-10-28`), B3 (`2026-11-06`), and B4 (`2026-11-12`, deployed on host via `9e1fd9d` at `2026-11-12 06:00:05 UTC`).
   - B5 requires attaching an XM **DEMO** account on the host with a separate `GOLD_DATA_DIR` (the captured spec on `/opt/gold` is `account_kind: REAL`) and running a 48 h live-path pilot covering IOC fills, SL/TP attachment, `+0.75R` BE `TRADE_ACTION_SLTP`, 240-min time stop close, rejection handling, disconnect, restart, reconciliation, and the `LIVE_HALT` kill switch.
   - Step **B6** (`docs/RUNBOOK-LIVE.md` + drill log) is gated on B5.
5. **Step A6 (Cost model — `quote_sample` gate MET, after B4):**
   - `docs/EXECUTION-PLAN.md` §3 schedules A6 after B4: *"Complete the cost model: measured all-in round trip (spread + slippage + commission + swap), re-cost the ledger and canonical replay with a sensitivity range, write a dated cost doc. Keep $0.40 registered until that analysis is complete."*
   - We therefore complete **all repo-measurable parts of A6** in this document — (a) the 34-day / 4-weekend spread distribution and 5-second intrawindow spike envelope, (b) the **exact overnight swap cost** on every ledger trade from the 5 captured XM `symbol_spec` snapshots, (c) the contract-spec commission structure, (d) the out-of-sample evaluation of B4's cost-as-%-of-1R guard on the 87 new trades (`#888–#974`), and (e) the full cost-sensitivity re-costing of the ledger and `strategy_lab.py` across `$0.00–$0.50/side` (`$0.00–$1.00` round trip) — while explicitly recording the **exact remaining blocker** for `live_readiness.py`'s `MANUAL cost_model` check: **realized IOC market-order / stop-trigger slippage and deal-level commission/fee verification from B5 DEMO `history_deals_get` fills**.

---

## 3. Step A6 — Measured Cost Components from `xm_data/` and `trades.csv`

### 3.1 Component 1: Bid-Ask Spread & 5-Second Intrawindow Envelope (Complete — 34 Days / 4 Weekends)

Across `38` daily quote files (`2026-10-13 15:48:30 → 2026-11-19 08:59:30 UTC`, `102,967` total rows, `71,174` usable fresh open-market rows; `34/14` complete UTC days and `4/2` complete weekends):

| Metric (`$ per oz` = `$ per 0.01-lot trade` on 100 oz GOLD) | n | Mean | Median (p50) | p75 | p90 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Point sample (`spread = ask − bid`)** | 71,174 | **$0.552** | **$0.550** | $0.560 | **$0.570** | **$0.570** | $0.580 | $2.610 |
| **5s window envelope (`spread_max`)** | 71,174 | **$0.561** | **$0.560** | $0.570 | **$0.570** | **$0.580** | $0.700 | $2.790 |
| **Intrawindow 5s spike (`spread_max − spread`)** | 71,174 | **$0.009** | **$0.000** | $0.010 | **$0.020** | **$0.030** | $0.110 | $1.290 |
| **Matched ledger trades (`0.5 × (entry_spread + exit_spread)`, ±75s)** | 396 | **$0.553** | **$0.550** | $0.555 | **$0.560** | **$0.565** | $0.680 | $1.660 |

By UTC session (`71,174` usable rows):
- **ASIA (`23:00–07:00 UTC`, n = 24,641):** median **$0.55**, p90 **$0.57**, p95 **$0.57**, p99 **$0.58**, max **$1.00** (matched trades `n = 175`: mean **$0.56**).
- **LONDON (`07:00–12:00 UTC`, n = 15,389):** median **$0.55**, p90 **$0.56**, p95 **$0.57**, p99 **$0.57**, max **$0.58** (matched trades `n = 88`: mean **$0.55**).
- **NY (`12:00–21:00 UTC`, n = 26,918):** median **$0.55**, p90 **$0.56**, p95 **$0.57**, p99 **$0.58**, max **$2.00** (matched trades `n = 130`: mean **$0.55**).
- **ROLLOVER (`21:00–23:00 UTC`, n = 2,793):** median **$0.56**, p90 **$0.58**, p95 **$0.58**, p99 **$0.77**, max **$1.23** (matched trades `n = 3`: mean **$0.57**).
- **WEEKLY OPEN (`Sun–Mon first open hour`, n = 1,433):** median **$0.57**, p90 **$0.87**, p95 **$1.00**, p99 **$1.34**, max **$2.61**.

Key takeaway on spread:
- **99.3%** of usable quotes exceed the registered **$0.40/trade** assumption (`$0.20/side`).
- The empirical spread-only round trip is tightly concentrated at **$0.55/trade** (`$0.275/side`), with an intrawindow 5-second worst-case spike envelope median of **$0.56/trade** (mean `+$0.009/trade`, p95 `+$0.030/trade`).

### 3.2 Component 2: Overnight Swap / Rollover Financing (Measured from `symbol_spec_history.jsonl` + `trades.csv`)

`tools/mt5_quotes.py` has captured **5 contract-spec snapshots** in `xm_data/symbol_spec_history.jsonl` (`2026-10-13` through `2026-11-19`). All 5 snapshots report:
- `swap_mode = 1` (`POINTS`), `point = 0.01`, `trade_tick_value = 1.0` → **1 swap point = `$0.01` per `0.01` lot** (`1 oz`).
- `swap_rollover3days = 3` (`WED`) → positions held across the Wednesday daily server-midnight break (`00:00` server time = `20:58→22:00 UTC` under `+3h`, `21:58→23:00 UTC` under `+2h`) pay/receive **3×** the daily swap; all other weekday breaks (`Mon, Tue, Thu, Fri`) pay/receive **1×**.

Captured swap schedule across the 5 snapshots:

| Snapshot # | Captured (UTC) | `swap_long` (pts) | `swap_long` ($/night @ 0.01 lot, 1× / Wed 3×) | `swap_short` (pts) | `swap_short` ($/night @ 0.01 lot, 1× / Wed 3×) | Note |
|---|---|---:|---:|---:|---:|---|
| 1 | `2026-10-13 15:48:56` | `−83.83` | `−$0.84` / `−$2.51` | `+20.64` | `+$0.21` / `+$0.62` | Initial capture |
| 2–4 | `2026-10-25` .. `2026-11-07` | `−78.59` | `−$0.79` / `−$2.36` | `+16.81` | `+$0.17` / `+$0.50` | Autumn rate adjustment |
| 5 | `2026-11-15 01:54:56` (verified `11-19`) | `−75.42` | `−$0.75` / `−$2.26` | `+16.17` | `+$0.16` / `+$0.49` | Latest XM swap revision |

Because the strategy is an M1 scalper with `MAX_HOLD_MINUTES = 240`, median hold `9–22 min`, a `21:45–22:30 UTC` rollover blackout, and the `30-min` pre-close entry guard (`71317da`, `2026-10-25`), **only 10 of 974 closed trades (1.03%) in the entire book — and only 7 of 477 trades (1.47%) in the structural-stop era — were open across the daily server-midnight rollover break**:

| Ledger row | Trade # | Side | Entry (UTC) | Exit (UTC) | Era | Break Day (mult) | Applicable Swap (pts) | Realized Swap ($) | Exit Reason | Gross P&L ($) |
|---:|---:|---|---|---|---|---|---:|---:|---|---:|
| 95 | `#95` | SELL | `2026-09-11 20:57:05` | `2026-09-13 22:01:03` | pre-cutover | Fri (`1×`) | `+20.64` | **`+$0.21`** | TP | `+$3.38` |
| 408 | `#409` | BUY | `2026-09-29 20:58:08` | `2026-09-29 22:06:06` | pre-cutover | Tue (`1×`) | `−83.83` | **`−$0.84`** | BE | `$0.00` |
| 475 | `#476` | SELL | `2026-10-02 20:56:02` | `2026-10-04 22:00:05` | pre-cutover | Fri (`1×`) | `+20.64` | **`+$0.21`** | TIME | `−$1.52` |
| 594 | `#595` | BUY | `2026-10-14 18:28:04` | `2026-10-14 22:21:03` | `structstop` | **Wed (`3×`)** | `−83.83` | **`−$2.51`** | TP | `+$14.45` |
| 609 | `#610` | BUY | `2026-10-15 20:05:05` | `2026-10-15 22:48:07` | `structstop` | Thu (`1×`) | `−83.83` | **`−$0.84`** | SL | `−$6.95` |
| 686 | `#687` | SELL | `2026-10-22 20:20:01` | `2026-10-22 22:24:03` | `structstop` | Thu (`1×`) | `+20.64` | **`+$0.21`** | SL | `−$5.70` |
| 815 | `#815` | BUY | `2026-11-04 20:08:05` | `2026-11-05 00:04:05` | `structstop` | **Wed (`3×`)** | `−78.59` | **`−$2.36`** | BE | `$0.00` |
| 835 | `#835` | SELL | `2026-11-05 21:22:04` | `2026-11-05 23:18:07` | `structstop` | Thu (`1×`) | `+16.81` | **`+$0.17`** | TP | `+$13.39` |
| 887 | `#887` | SELL | `2026-11-11 20:42:07` | `2026-11-11 23:01:04` | `structstop` | **Wed (`3×`)** | `+16.81` | **`+$0.50`** | SL | `−$3.94` |
| 968 | `#968` | SELL | `2026-11-18 21:16:08` | `2026-11-18 23:01:05` | `structstop` | **Wed (`3×`)** | `+16.17` | **`+$0.49`** | SL | `−$5.31` |

Aggregate swap impact:
- **Whole book (`n = 974`):** total swap = **`−$4.77`** (**`−$0.0049/trade`**, or `0.10%` of mean 1R `$4.96`).
- **Structural-stop era (`n = 477`):** total swap = **`−$4.35`** (**`−$0.0091/trade`**, or `0.15%` of median 1R `$5.79`).
- **Per-event asymmetry:** SELL positions held across rollover earn a small positive swap (`+$0.16` to `+$0.50`), whereas BUY positions pay `−$0.75` to `−$0.84` on normal nights and **`−$2.26` to `−$2.51` on Wednesdays** (e.g. `#815` was a `$0.00` paper BE scratch that would have booked `−$2.36` in swap + `−$0.55` spread = `−$2.91` net in LIVE, which B3's `_live_book_deals` now captures directly from `deal.swap`).

### 3.3 Component 3 & 4: Commission and Execution Slippage (Why `cost_model` Stays `MANUAL` Until B5)

1. **Commission:** On the captured XM symbol (`Derivatives\Spot Metals\GOLD`, `calc_mode: CFD_LEVERAGE`, `contract_size: 100.0`, floating spread ~55 pts), costs are embedded in the bid-ask spread (`$0.00` separate commission on XM Standard CFD metals). However, confirming `deal.commission == 0.0` and `deal.fee == 0.0` in actual broker deal records requires at least one DEMO round trip in `history_deals_get` (Step **B5**).
2. **Execution Slippage (Market IOC entry + SL/TP/TIME exit):** Passive 30-second `symbol_info_tick` polling cannot observe order-book sweep or fill slippage between the trigger/request price and the executed deal price on `ORDER_FILLING_IOC` market orders or broker-side `SL`/`TP`/`TRADE_ACTION_SLTP` fills.
   - As an empirical quote-side proxy, the 5-second intrawindow spread spike (`spread_max − spread`) has a mean of **`$0.009/trade`** (p90 `$0.020`, p95 `$0.030`, p99 `$0.110`), and only `1/477` era trades (`#815`) reopened across a daily break below its stop (`−$2.77` headroom, recovered to BE).
   - Realized slippage in `$/trade` and `R/trade` must be measured from `history_deals_get` during the **B5 48-hour DEMO run** before `live_readiness.py`'s `cost_model` check can move from `MANUAL` or the registered `$0.40` (`$0.20/side`) constant is replaced.

---

## 4. Out-of-Sample Check of B4's Cost-as-%-of-1R Guard (`#888–#974`, `n = 87`)

Since B4 (`docs/ANALYSIS-2026-11-12-b4-live-order-safety.md`) landed at collection 480 (`887` closed trades), **87 new paper trades (`#888–#974`)** have closed in the structural-stop era, bringing the quote-matched structural-stop sample from **309** to **396** trades (`100%` of the 87 new trades matched a fresh quote within `±75s`).

### 4.1 Full 396-Trade Matched Sample by `1× Spread / 1R` Decile Bucket (Updating B4 §3)

| `spread / 1R` bucket | n (was 309 → **396**) | Decisive | Decisive WR | Gross R/trade | Net @ $0.55 R/trade | Net @ Measured Spread R/trade |
|---|---:|---:|---:|---:|---:|---:|
| **0–8%** | 143 | 103 | 35.9% | −0.074R | −0.138R | −0.137R |
| **8–12%** | 141 | 101 | 40.6% | +0.011R | −0.087R | −0.087R |
| **12–16%** | 63 | 42 | 35.7% | −0.072R | −0.210R | −0.210R |
| **16–20%** | 33 | 25 | 20.0% | −0.379R | −0.553R | −0.553R |
| **20%+** | **16** | **10** | **10.0%** (1W/9L/6BE) | **−0.469R** | **−0.684R** | **−0.709R** |

### 4.2 Out-of-Sample `#888–#974` (`n = 87` New Trades Since 2026-11-12)

We report both cost-share definitions on the 87 new trades (`2026-11-12` to `2026-11-19`):
1. **1× spread (`spread / 1R > 20%`, i.e., `1R < ~$2.75`, matching the §4.1 bucket definition):**
   - **Allowed (`≤ 20%`, `n = 82`):** `20W / 41L / 21BE / 0TIME` (`32.8%` decisive WR), gross `−$51.62` (`−0.134R/trade`), net at `$0.40` `−0.208R/trade`, net at measured spread `−0.236R/trade`.
   - **Vetoed (`> 20%`, `n = 5`: `#918, #934, #936, #948, #949`):** **`0W / 2L / 3BE / 0TIME` (`0.0%` decisive WR)**, gross `−$5.31` (`−0.400R/trade`), net at `$0.40` `−0.554R/trade`, net at measured spread **`−0.608R/trade`**.
2. **2× entry spread (`engine.GoldEngine.live_cost_measure()` = `2.0 × (ask − bid) / 1R > 20%`, i.e., `1R < ~$5.50`, matching B4 §8's addendum):**
   - **Allowed (`≤ 20%`, `n = 44`):** `10W / 22L / 12BE / 0TIME` (`31.2%` decisive WR), gross `−$41.26` (`−0.159R/trade`), net at measured spread `−0.232R/trade`.
   - **Vetoed (`> 20%`, `n = 43`):** `10W / 21L / 12BE / 0TIME` (`32.3%` decisive WR), gross `−$15.67` (`−0.140R/trade`), net at measured spread `−0.283R/trade`.

Note for B5 / Track B: `live_cost_measure()` in `engine.py` returns `2.0 * (ask - bid)` (`~$1.10` at median spread, pinned by `test_live_safety.py::TestMeasuredCost::test_round_trip_is_twice_the_live_spread` and Smoke Scenario AD), whereas a market round trip on a bid-to-bid chart pays `1.0 * (ask - bid)` (`~$0.55`). Thus in LIVE mode `LIVE_COST_MAX_PCT_OF_R = 20.0` with `2.0 * (ask - bid)` acts as an effective **10% single-spread / 1R cap** (`1R ≥ ~$5.50`), vetoing ~42–47% of setups, whereas the 1× spread > 20% tail (`1R < ~$2.75`) vetoes only the bottom 4–6% (`16/396` overall, `5/87` out-of-sample, `1W/9L/6BE`). Neither version makes the remaining flow net positive; we leave `engine.py` untouched.

---

## 5. Step A6 — Ledger and Canonical Replay Re-Costed Across the Sensitivity Range

### 5.1 Checked-in Ledger Re-Costed (`trades.csv`, `n = 974`, Scratches Included)

| Round-Trip Cost (`$/trade`) | Per-Side (`$/side`) | Meaning | All Trades (`n = 974`) Net $ / Net R/t (mean-1R `$4.96` / per-trade) | `0.75R Master` (`n = 799`) Net $ / Net R/t (mean-1R `$5.24` / per-trade) | `Struct-Stop Era` (`n = 477`) Net $ / Net R/t (mean-1R `$6.12` / per-trade) |
|---:|---:|---|---|---|---|
| **$0.00** | $0.000 | Gross (un-costed paper ledger) | −$443.17 (`−0.092R` / `−0.122R`) | −$318.97 (`−0.076R` / `−0.104R`) | −$124.36 (`−0.043R` / `−0.065R`) |
| **$0.30** | $0.150 | Optimistic lower bound | −$735.37 (`−0.152R` / `−0.193R`) | −$558.67 (`−0.133R` / `−0.172R`) | −$267.46 (`−0.092R` / `−0.122R`) |
| **$0.40** | **$0.200** | **Registered baseline cost** | **−$832.77 (`−0.173R` / `−0.217R`)** | **−$638.57 (`−0.153R` / `−0.194R`)** | **−$315.16 (`−0.108R` / `−0.141R`)** |
| **$0.55** | **$0.275** | **Measured median spread (`xm_data/`)** | **−$978.87 (`−0.203R` / `−0.253R`)** | **−$758.42 (`−0.181R` / `−0.228R`)** | **−$386.71 (`−0.133R` / `−0.170R`)** |
| **$0.56** | **$0.280** | **Measured spread + swap (`$0.55 + $0.009`)** | **−$988.61 (`−0.205R` / `−0.255R`)** | **−$766.41 (`−0.183R` / `−0.230R`)** | **−$391.48 (`−0.134R` / `−0.172R`)** |
| **$0.60** | $0.300 | Spread + $0.04/t slippage allowance | −$1,027.57 (`−0.213R` / `−0.265R`) | −$798.37 (`−0.191R` / `−0.239R`) | −$410.56 (`−0.141R` / `−0.180R`) |
| **$0.70** | **$0.350** | **PREREG §5 cost-override threshold** | −$1,124.97 (`−0.233R` / `−0.289R`) | −$878.27 (`−0.210R` / `−0.262R`) | −$458.26 (`−0.157R` / `−0.199R`) |
| **$0.80** | $0.400 | Stress test (+$0.24/t slippage) | −$1,222.37 (`−0.253R` / `−0.312R`) | −$958.17 (`−0.229R` / `−0.284R`) | −$505.96 (`−0.173R` / `−0.218R`) |
| **$1.00** | $0.500 | Severe stress test (rollover / news) | −$1,417.17 (`−0.294R` / `−0.360R`) | −$1,117.97 (`−0.267R` / `−0.329R`) | −$601.36 (`−0.206R` / `−0.256R`) |

### 5.2 Canonical Stateful Replay Sensitivity (`tools/strategy_lab.py`, Post-Cutover & `075R MASTER`)

Post-cutover window (`entries ≥ 2026-10-06 03:00 UTC`, independent stateful cascades):

| Cost / side (Round Trip) | `baseline` (`n=707`, `33.0%` dec) R/t · $/t · maxDD | `structstop` (`n=493`, `36.8%` dec) R/t · $/t · maxDD | `structstop1.0` (`n=451`, `36.7%` dec) R/t · $/t · maxDD | `structstop1.5` (`n=402`, `39.2%` dec) R/t · $/t · maxDD |
|---|---|---|---|---|
| **$0.000** (`$0.00` RT) | `−0.121R` · `−$0.472` · `$377.5` | `−0.056R` · `−$0.261` · `$216.9` | `−0.056R` · `−$0.331` · `$273.3` | **`−0.008R` · `−$0.098` · `$182.1`** |
| **$0.150** (`$0.30` RT) | `−0.210R` · `−$0.772` · `$571.9` | `−0.114R` · `−$0.561` · `$343.2` | `−0.106R` · `−$0.631` · `$386.4` | **`−0.052R` · `−$0.398` · `$290.1`** |
| **$0.200** (`$0.40` RT — registered) | `−0.239R` · `−$0.872` · `$636.7` | `−0.133R` · `−$0.661` · `$387.7` | `−0.123R` · `−$0.731` · `$424.1` | **`−0.067R` · `−$0.498` · `$326.1`** |
| **$0.275** (`$0.55` RT — meas. spread) | `−0.284R` · `−$1.022` · `$733.9` | `−0.162R` · `−$0.811` · `$454.4` | `−0.148R` · `−$0.881` · `$480.6` | **`−0.089R` · `−$0.648` · `$380.1`** |
| **$0.280** (`$0.56` RT — spread + swap) | `−0.287R` · `−$1.032` · `$740.5` | `−0.164R` · `−$0.821` · `$458.9` | `−0.150R` · `−$0.891` · `$484.4` | **`−0.091R` · `−$0.658` · `$383.7`** |
| **$0.300** (`$0.60` RT) | `−0.299R` · `−$1.072` · `$767.1` | `−0.172R` · `−$0.861` · `$476.7` | `−0.157R` · `−$0.931` · `$499.5` | **`−0.097R` · `−$0.698` · `$398.1`** |
| **$0.350** (`$0.70` RT — PREREG §5 bar) | `−0.328R` · `−$1.172` · `$833.6` | `−0.191R` · `−$0.961` · `$521.2` | `−0.174R` · `−$1.031` · `$537.9` | **`−0.111R` · `−$0.798` · `$434.1`** |
| **$0.400** (`$0.80` RT) | `−0.358R` · `−$1.272` · `$900.1` | `−0.210R` · `−$1.061` · `$565.7` | `−0.190R` · `−$1.131` · `$577.9` | **`−0.126R` · `−$0.898` · `$470.1`** |
| **$0.500** (`$1.00` RT) | `−0.418R` · `−$1.472` · `$1,040.5` | `−0.249R` · `−$1.261` · `$654.7` | `−0.224R` · `−$1.331` · `$657.9` | **`−0.156R` · `−$1.098` · `$542.1`** |

`075R MASTER` window (`entries ≥ 2026-09-15 06:00 UTC`):
- At **`$0.200/side` (`$0.40` RT):** `baseline` `−0.247R/t`, `structstop` `−0.125R/t`, `structstop1.0` `−0.122R/t`, `structstop1.5` **`−0.060R/t`** (`n = 580`, `39.6%` decisive WR, maxDD `$337.4`).
- At **`$0.275/side` (`$0.55` RT):** `baseline` `−0.290R/t`, `structstop` `−0.153R/t`, `structstop1.0` `−0.147R/t`, `structstop1.5` **`−0.082R/t`** (maxDD `$404.1`).
- At **`$0.280/side` (`$0.56` RT):** `baseline` `−0.293R/t`, `structstop` `−0.155R/t`, `structstop1.0` `−0.149R/t`, `structstop1.5` **`−0.084R/t`** (maxDD `$409.6`).

Conclusions from the sensitivity range:
1. **Every variant is net negative at every cost level (including `$0.00` gross on both the post-cutover era and the `075R MASTER` book)** now that the post-cutover sample has grown to `n = 477` ledger / `n = 493` replay trades (`structstop1.5` gross is `−0.008R/t` post-cutover and `−0.002R/t` on `075R MASTER`).
2. **Ordering across stop clearance remains strictly monotone at every cost:** `structstop1.5` beats live `structstop` by **`+0.066R/trade` at `$0.20/side`** and **`+0.073R/trade` at `$0.275–$0.280/side`** with ~`$67–$75` lower modelled drawdown, while the literal §7 `baseline` revert remains the worst cell at every cost (`−0.239R/t` at `$0.20/side`, `−0.284R/t` at `$0.275/side`).
3. **Registered cost constant (`$0.40` RT = `$0.20/side`) stays unchanged:**
   - Measured spread + swap is **`$0.56/trade`** (`$0.280/side`), which is below the **`$0.70/trade`** (`$0.350/side`) cost-override threshold in `docs/PREREG-2026-10-26-structstop1.5.md` §5.
   - Realized IOC fill slippage and broker deal commission/fee remain unmeasured until Step **B5** (DEMO execution).

---

## 6. Critical Timing Alert on `structstop1.5` (`2026-12-01 21:00 UTC` Date Gate)

`docs/PREREG-2026-10-26-structstop1.5.md` §3 registered the evaluation window as:
> **PASS/FAIL:** at **n = 150** closed trades **or 2026-12-01 21:00 UTC, whichever comes first**. ... Crossing n=150 *after* the date gate does **not** reopen PASS.

As of **`2026-11-19 09:00 UTC`**:
- **Step A2 has still not been deployed** (`engine.SL_CLEAR_ATR` is still `0.5`, and `strategy_lab.CLEAR15_CUTOVER` is `None`).
- Only **12.5 calendar days (~8.5 trading days)** remain before `2026-12-01 21:00 UTC`.
- At the `structstop1.5` replay pace of **10.6 trades/active day** (or the live 0.5 ATR pace of **12.9 trades/active day**), 8.5 trading days can produce only **~90–110 trades** before `2026-12-01 21:00 UTC`.
- Consequently, **the `n = 150` PASS arm is already mathematically unreachable before the `2026-12-01 21:00 UTC` date gate**, and if A2 remains undeployed for 1–2 more trading days, even the **`n = 100` SCREEN threshold** will not be reached before `2026-12-01 21:00 UTC` (`n < 60` is not a result in either direction).

**Guardrail compliance:** Per `docs/EXECUTION-PLAN.md` §0 and §1, an agent session must **never** bypass or retro-edit a signed pre-registration. `docs/PREREG-2026-10-26-structstop1.5.md` remains untouched. If the owner still wants a full ~3-week / `n = 150` evaluation window once A2 is deployed on the host, the owner must explicitly authorize a dated **pre-deploy** amendment to the date gate *before* A2 lands (while `CLEAR15_CUTOVER` is still `None` and zero post-change trades exist).

---

## 7. Exact Blockers & Next Eligible Steps

| Queue ID | Status | Exact Blocker / Next Action |
|---|---|---|
| **A2** (`SL_CLEAR_ATR = 0.5 → 1.5` deploy) | **BLOCKED (Host + Open Trade)** | (1) **`BUY #975 @ $3737.09` is currently open** in the synced snapshot (`entry_time: 2026-11-19 05:49:07 UTC`, SL `$3727.80`, TP `$3751.03`). (2) Production host (`/opt/gold`) cannot be checked from this sandbox checkout; A2 may only land in a verified flat-host window and must set `CLEAR15_CUTOVER` to the host's `autosync: merge upstream` commit timestamp. (3) **Owner decision needed** if the `2026-12-01 21:00 UTC` date gate should be amended pre-deploy so `n = 150` remains reachable after A2 deploys. |
| **B5** (`docs/DEMO-EVIDENCE.md`) | **BLOCKED (Host / Operator Action)** | All 17 code and data checks in `tools/live_readiness.py` are **PASS (`0 TODO`)**. Requires operator on the MT5/Wine host to attach an XM **DEMO** account with a separate `GOLD_DATA_DIR` (captured spec is `REAL`), exercise IOC fill, SL/TP, `+0.75R` BE `TRADE_ACTION_SLTP`, 240-min time stop, rejection handling, disconnect, restart, reconciliation, and `LIVE_HALT` kill switch over a 48 h stable run, and record the redacted report in `docs/DEMO-EVIDENCE.md`. |
| **A6** (All-in cost model) | **PARTIAL DONE (Repo data complete; Slippage/Deal Commission blocked on B5)** | Spread (`$0.55/trade` median across 34 days / 4 weekends / 396 matched trades), 5s spike envelope (`+$0.009/trade` mean), and overnight swap (`−$0.0091/trade` era, `−$0.0049/trade` whole book from 5 contract-spec snapshots) are now documented with full ledger and replay sensitivity tables (`§3–§5` above). Remaining blocker for `MANUAL cost_model`: realized IOC fill/stop slippage and `deal.commission`/`deal.fee` verification from B5 DEMO `history_deals_get` deals. Keep `$0.40` (`$0.20/side`) registered until then. |
| **B6** (`docs/RUNBOOK-LIVE.md` + drill log) | **GATED on B5** | Requires B5 completion and an operator kill-switch / arming drill log on the host. |
| **A8** (Private manual observation log) | **BLOCKED (Owner Rule Definition)** | Requires the owner to define the manual pressure/hold rule before any code is written. |

---

## 8. Reproduction

```bash
python3 tools/check_data.py
python3 tools/handoff_check.py
python3 tools/check_structural_stop.py
python3 tools/check_gap_rides.py
python3 tools/pressure_report.py --root .
python3 tools/xm_quote_report.py
python3 tools/equity_runway.py
python3 tools/win_rate_report.py --spread 0.40
python3 tools/win_rate_report.py --spread 0.55
python3 tools/strategy_lab.py --calib-only
python3 tools/strategy_lab.py --table --only baseline,structstop,structstop1.0,structstop1.5
python3 tools/live_readiness.py
python3 readiness.py
python3 tools/smoke_test.py
```
