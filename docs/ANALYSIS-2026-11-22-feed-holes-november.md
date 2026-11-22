# ANALYSIS 2026-11-22 — November feed holes: two unexplained outages and one unreviewable trade

**Precedence:** `docs/EXECUTION-PLAN.md` §6 rule 1 — *"a data-integrity failure or a feed outage —
fix/report first; no judgement on bad data."* This document is the **report** half. No judgement was
made on the affected period, no trade was deleted or re-booked, and nothing in the ledger was edited.

**Tool:** `python3 tools/feed_forensics.py` (**new**, read-only, stdlib only, never imports `engine.py`)
and `python3 tools/test_feed_forensics.py` (**new**, 13 hermetic tests).

**Snapshot:** price log 76 726 bars through `2026-11-20 21:57:03 UTC`; quote logger 75 495 *fresh* rows
through `2026-11-20 21:59:30 UTC`. The two feeds only overlap from `2026-10-13 15:48` (the logger was
installed then), so the tool judges from there and says so instead of calling the earlier silence an
outage.

---

## 1. Why this needed a tool

`tools/xm_quote_report.py` already separates a **scheduled closure** from a **feed stall** — but only
for the *quote* feed, and only using time-of-day heuristics. It cannot answer "was the broker actually
ticking while our bar log was silent?", because that needs the *other* feed.

That is the discriminating evidence this tool uses: the quote logger keeps writing rows even while the
market is shut, but those rows carry `STALE` and `xm_quote_report.usable()` rejects them. So **"a fresh
quote exists during an expected-open minute with no bar" is proof the terminal had a live tick** — the
broker was open and we lost the bar. Conversely "no bar AND no fresh quote" in an expected-open minute
means the whole MT5 side went quiet, which is an outage rather than a logger problem.

Four outcomes are separated:

| kind | meaning |
|---|---|
| `MARKET CLOSED` | inside `xm_quote_report.in_closed_window` — not reported at all |
| `BOTH FEEDS DOWN` | no bars **and** no fresh quotes in an expected-open minute → terminal / MT5 / host outage |
| `PRICE-FEED ONLY` | quotes advancing, bars missing → `mt5feed` / `goldbot` sick, terminal fine |
| `QUOTE-FEED ONLY` | bars arriving, quotes missing → `mt5quotes` sick, engine unaffected |

Everything is worked **minute by minute**, with a ±2 min coverage tolerance (the two loggers sample on
different clocks: M1 bars vs 30 s quotes). That de-duplicates a hole seen by both feeds, makes a closure
impossible to double-count, and avoids the failure mode of an hour-of-day heuristic.

---

## 2. Findings (45-day window, `2026-10-13 15:48` → `2026-11-22 12:17 UTC`)

| kind | start (UTC) | end (UTC) | open min | exposure |
|---|---|---|---|---|
| PRICE-FEED ONLY | 2026-10-19 02:37 | 2026-10-19 02:47 | 10 | — |
| PRICE-FEED ONLY | 2026-10-25 23:10 | 2026-10-25 23:57 | 47 | — |
| **BOTH FEEDS DOWN** | **2026-11-04 08:17** | **2026-11-04 19:33** | **676** | — |
| **BOTH FEEDS DOWN** | **2026-11-05 03:00** | **2026-11-05 03:26** | **26** | **#819 BUY** |
| **BOTH FEEDS DOWN** | **2026-11-06 13:50** | **2026-11-06 20:55** | **425** | — |

**1 184 expected-open minutes lost, 5 holes, 3 of them the terminal going silent.**

The two PRICE-FEED-ONLY rows are the already-documented "Sunday-reopen price-bar hole" family
(`docs/REVIEW-2026-10-26-full-system-audit.md`): quotes fresh, bars resuming late. They are reported
here for completeness, not as new findings.

### 2.1 — `2026-11-04 08:17 → 19:33 UTC` (676 min, 11.3 h)

This is the hole that had been logged only as *"a mid-day feed outage"* in
`docs/ANALYSIS-2026-10-16-dashboard-pressure.md`-era notes and as an **"exceptional" logger gap** in
`docs/ANALYSIS-2026-11-12-b4-live-order-safety.md` §"quote + price feed healthy". Both feeds stopped
together, inside the London/NY session, for over eleven hours.

What the tool can prove from the data:

* `xm_data/quotes-2026-11-04.csv` has **zero rows at all** between 09:00 and 19:20 — not STALE rows,
  *no rows*. The logger process itself was not running.
* The price log resumes at `19:35:14` with a normal bar cadence (`19:36:14`, `19:37:09`, `19:38:09`…).
* The last trade before the hole is **#814, closed 08:07:05**. The next entry is **#815 at 20:08:05**,
  after the reopen. **No position was open across it.**
* The bar log carries **one corrupt row (NUL bytes) immediately after the gap**, which `check_data.py`
  reports as *"1 row with unparsable timestamp/OHLC (skipped)"*. It is cosmetic, but it is a second
  symptom of the same restart.

**The pattern in that file is consistent with a lost VM session rather than a killed process:** after
the resume, bar timestamps sit at `:09`/`:14` seconds instead of the `:01`–`:06` they had before, the
watchdog cannot open a second process against one terminal, and both an independent logger and the feed
stopped in the same minute. **This is a hypothesis about the host, not a fact in the repo** — it cannot
be verified from a checkout, so it is written here as a hypothesis and nothing depends on it.

### 2.2 — `2026-11-06 13:50 → 20:55 UTC` (425 min, 7.1 h) — **correction to the 2026-11-12 analysis**

`docs/ANALYSIS-2026-11-12-b4-live-order-safety.md` concluded that *"the 2026-11-06 STALE flag was a
collection-boundary artifact of the prior snapshot, not a dead logger"* and that *"no host action is
implied by this checkout."* **The first half of that was wrong.** The quote logger did keep writing
rows — but every row from `13:49:30` onwards is flagged `STALE`, and the **price log stopped in the same
minute** (`last bar 13:47:03`). Both feeds were dead in the middle of the NY session. The 11-12 snapshot
simply ended before the hole became visible, and the review read "quotes continuous" off the *logger
rows* rather than off *fresh* rows.

No trade was open (`#844` closed at 13:25:05; the next entry is `#845` on Sunday `23:32:07`), and the
already-registered **daily-break observation** stands unaffected: the *first post-DST break* was
verified on 10-27 and the 11-02 schedule change was recorded from the price log's own reopen times
(`PREREG-2026-10-25-gap-guard-daily-closure.md` §2.3, done). This document does **not** reopen that
verification; it corrects the feed-health claim attached to it.

### 2.3 — `2026-11-05 03:00 → 03:26 UTC` (26 min) — **#819 is not judgeable**

Both feeds stopped for 26 minutes while a live paper position was open. **#819 BUY** (entry
`02:05:03`, SL/TP `4131.33 / 4147.79`, ATR at entry 3.85) ran `02:05 → 05:18` and exited **BE
(0.00)** with its stop ratcheted to entry.

The honest statement: **we cannot know what happened to #819 between 03:00 and 03:26.** Under the
engine's own fill convention a ratcheted stop at entry means it *could* have been touched in the gap and
booked as a scratch on the first bar back — but the bar that would prove it is one of the 26 missing
ones. The P&L is a scratch either way, so **no P&L claim rests on it**; what it costs is the ability to
say the BE path was observed rather than assumed for that trade. It is excluded from any future BE-path
audit and listed as such, never silently counted as a clean observation.

---

## 3. What this does and does not change

**Does:**

* classifies the November holes properly for the first time, and **corrects a published claim**
  (11-12 B4 analysis: "logger STALE flag was a collection-boundary artifact ... no host action implied").
* gives the host work a precise list instead of a vague "check the logger": three windows on
  **2026-11-04, 11-05 and 11-06** where the MT5 side went silent inside an open session, on a host that
  is documented to keep a ~15 min cadence in both feeds even when idle.
* marks **#819** as not judgeable on bar data, so no later review can claim the BE path was "observed".

**Does not:**

* change any trade, ledger row, `status.json` value, parameter or registered bar. The 26 missing minutes
  are a *gap in observation*, not a retroactive edit.
* reopen the §7 gap-ride judgement, the daily-break verification, or any A-track reading. Nothing here
  judges an outcome.
* claim the host cause. The lost-session reading of 11-04 is a **hypothesis**; 11-05 and 11-06 are
  consistent with it but prove nothing on their own.

---

## 4. Host actions (the only place this can be fixed)

Cannot be done from a repo checkout; reported, not simulated:

1. **`journalctl -u mt5feed -u goldbot -u mt5quotes-gold --since 2026-11-03 --until 2026-11-07`** — was
   there a restart, an OOM kill, a Wine crash or a lost VM session at `11-04 08:1x`, `11-05 02:5x` and
   `11-06 13:4x`?
2. **Durability:** if 11-04 was a lost VM session, the three services need `Restart=always` plus a boot
   `WantedBy=multi-user.target` (they are declared in `deploy/`, but the box's installed units are what
   matter), and the watchdog must be able to restart them as a group.
3. **A feed-health alarm that reads the PRICE log, not the quote log.** Both 11-04 and 11-06 were visible
   only in the bar log while the quote logger's row count kept looking healthy.
4. **Re-run `python3 tools/feed_forensics.py` after the fix** — the acceptance test is "no
   `BOTH FEEDS DOWN` row in the trailing 14 days".

Suggested addition to the autosync digest: a `🔌 feeds:` line naming the last hole of ≥10 expected-open
minutes, the same way `📈 candles:` already names a stale bar feed.

---

## 5. Verification

```
python3 tools/feed_forensics.py --days 45     # the table in §2, exit 0
python3 tools/test_feed_forensics.py          # 13 tests, OK
python3 tools/check_data.py                   # 0 fail / 9 documented warnings (unchanged)
python3 tools/xm_quote_report.py              # the quote-side view this tool complements
python3 tools/pressure_report.py --root .     # §7 feed health, hour-of-day heuristic (unchanged)
```

The tool reuses `xm_quote_report.usable`, `xm_quote_report.in_closed_window` and
`strategy_lab.load_ledger` rather than restating any of them — one definition per question, so this new
view cannot drift from the existing ones. `tests/test_feed_forensics.py` pins both the
"the repo rule is the rule" property and the write/import bans.

---

## 6. One-line answer for the plan

**Three `BOTH FEEDS DOWN` outages in November (11-04 676 min, 11-05 26 min, 11-06 425 min); no trade was
open except #819, which is therefore not judgeable on bar data; nothing was edited; the only fix is on
the host, and `feed_forensics.py` is the acceptance test.**
