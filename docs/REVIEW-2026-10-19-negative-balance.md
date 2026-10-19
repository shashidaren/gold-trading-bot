# Negative paper balance incident — 2026-10-19

## Verified evidence

Checked collection 276 / main 53366bc, status last updated 2026-10-18 23:59:04 UTC.
No production-host access was available in this investigation.

- Last valid row #625: BUY SL, entry 4168.71, exit 4164.01, P&L −$4.70,
  balance $150.69, exit 2026-10-16 20:54:03 UTC.
- Ten subsequent rows #626–635 (2026-10-18 23:05:06–23:58:08 UTC) all have
  blank Entry_Time/entry indicators and SL = TP = Exit_Price = 0.00.
- Every row is BUY, labelled TP, with Profit = −Entry_Price. Their total is
  −$41,806.88. $150.69 − $41,806.88 = **−$41,656.19**, exactly the raw status equity.
- Raw counts: 634 rows, 132 TP / 271 SL / 229 BE / 2 TIME. Ten TP labels are invalid.
  Valid subset remains 624 rows, 122W/271L/229BE/2TIME. Last valid ledger $150.69;
  $500 + valid summed P&L = $133.71 (existing $16.98 historical ledger drift).
- The owner's approximately −$58,000 reading is not present in this synced snapshot.
  Later host rows could explain it, but that is unverified.

### Update — extended to #626–645 (20 rows, 2026-10-19 02:33 UTC snapshot)

Synced snapshot at **2026-10-19 02:33 UTC** extends the suffix to **20 rows #626–645**
(2026-10-18 23:05:06 – 2026-10-19 02:23:04 UTC). All 20 share **blank Entry_Time and
zero Take_Profit** — the canonical incident signature. Variants observed:

- **BUY TP** with `SL=0.00/Exit=0.00/Profit=-Entry` (13 rows, #626–638)
- **BUY TP** with `SL=4172.00/Exit=0.00/Profit=-Entry` (2 rows, #644–645)
- **SELL TP** with `SL==Entry/TP=0/Exit=0/Profit=+Entry` (1 row, #639)
- **SELL BE** with `SL==Entry/TP=0/Exit==Entry/Profit=0` (3 rows, #640–642)
- **SELL SL** with `SL=4172/TP=0/Exit==SL/Profit=Entry-SL` (1 row, #643, −$4.31)

Total phantom P&L = **−$58,544.65**; **$150.69 − $58,544.65 = −$58,393.96**, exactly the
raw status equity at the 02:33 snapshot (644 rows, 138W/272L/232BE/2TIME; see
`trades.csv` lines 626–645). The 20-row suffix is contiguous, Trade_Num sequential
626→645, Balance_After continuous, and status `equity/total_trades` matches the ledger.
Reconciled ledger remains **624 rows, 122W/271L/229BE/2TIME, $150.69** (same $150.69
reference). The recovery tool now keys on `not Entry_Time and Take_Profit==0`,
covering all BUY/SELL TP/BE/SL variants; prior BUY-only zero-price check is superseded.
Evidence is preserved in `incident_backups/<UTC>/quarantined_trades.csv`
(originals + forward_test_log.csv copied). The checked-in `tools/repair_phantom_ledger.py`
was extended accordingly; `tools/test_repair_phantom_ledger.py` adds regression coverage
for SELL TP/BE/SL and full-20-row reconciliation.

## Mechanism and confidence

The malformed rows match the already documented PR #34 risk-sizer refusal bug
(HANDOFF §1 and PREREG-2026-10-17-risk-sizer.md): the old entry path armed a BUY
and assigned its entry before refusing an undersized position, leaving initial
zero targets/stops and no entry metadata. A subsequent candle sends zero TP to
check_position; for a BUY, 0 >= 0 is true and _pnl(0) subtracts the full gold price.
The TP label also increments wins instead of the daily SL breaker.

This is strong evidence of phantom paper accounting, not ten genuine market
losses. It does not establish the broker account balance or confirm the exact
production executable. The checked-in execute_simulated_trade now sizes/refuses
before arming, and size_lots keeps paper at fixed LOT_SIZE. Existing Scenario V
covers refusal and the next-candle phantom regression and passes. A stale running
process or different deployment is a leading explanation; verify on the host.

Additional recovery hazard: load_trade_stats only accepts positive Balance_After
values. Restarting against this corrupt ledger could silently select $150.69 while
retaining the invalid TP counts. A restart alone is not an audited ledger repair.

## Checks performed

- tools/check_data.py: **FAIL**, ten invalid entry times; raw status matches corrupt ledger.
- tools/check_structural_stop.py: PASS, validated structural-stop era n=127.
  This does not validate the ten malformed rows, which lack entry timestamps.
- tools/smoke_test.py: **SMOKE TEST PASSED**, including Scenario V.
- tools/handoff_check.py --update: refreshed snapshot. Its strategy_lab loader excludes
  malformed entries while engine_ledger_usd reads raw status, so mixed metrics are
  expected during this incident; freshness is not an integrity verdict.
- GitHub main API: main is the checked collection 276 revision at inspection time.

## Operator recovery prerequisites (not executed here)

1. Pause the paper engine to prevent more phantom rows. Preserve timestamped copies
   of trades.csv, status.json, forward_test_log.csv and service journal before editing.
2. Inspect systemctl status/cat goldbot and its PID command line, working directory,
   process start time and journal. Compare /opt/gold/engine.py's entry path with this
   checkout, and inspect autosync/restart logs. Do not hand-edit deployed source.
3. Reconcile any newer rows, and check for a real open position before restoring state.
   Quarantine invalid rows with an explicit audit trail; do not delete the evidence or
   blindly reset equity to $500. The $150.69 reference applies only to this snapshot.
4. Deploy/verify corrected code through the documented workflow, reconcile status
   counters/balance from the validated ledger, then explicitly restart the verified
   service and monitor its first accepted setup/exit and next autosync.
5. Require check_data to have zero failures on reconciled data before interpreting the
   structural-stop experiment. Missing legitimate trades cannot be invented: record
   the operational contamination/gap in the scheduled review.

No engine parameters, ledger rows, status state, deployment or real orders were
changed in this investigation. Remain paper-only.

## Recovery PR implementation

Owner requested a mergeable recovery PR. Added defense-in-depth price/geometry
validation before candle/tick paper exits; invalid positions now raise before
ratcheting or P&L mutation and retain evidence. Startup now preserves the latest
finite ledger balance even if zero/negative, rather than silently falling back to
an older positive value. These are accounting/integrity fixes, not strategy changes.

`tools/repair_phantom_ledger.py` defaults to read-only. It accepts only a contiguous
suffix matching the observed zero-exit BUY/negative-TP signature, checks sequential
IDs and balance continuity, refuses an active position or status mismatch, and
requires explicit stopped-engine acknowledgement to apply. It preserves both
original files and a quarantine CSV in private, Git-ignored `incident_backups/`,
then rewrites ledger/status from retained history. Never apply while engine or
scheduled autosync is running. It does not automatically repair on deployment.
Historical ledger drift is preserved, not silently reset. Trade IDs can be reused
after quarantine; identify archived rows by timestamp plus ID. The original status
last_update is retained as evidence, not rewritten to imply a new live heartbeat.

After merge/deploy, on the host (operator only):

1. Identify and suspend scheduled autosync (cron/timer per host configuration),
   stop `goldbot`, and capture its journal/process/deploy evidence. Confirm no writer
   remains and corrected code is installed. Merging may otherwise restart the engine
   through autosync; the new guard is defense-in-depth, not a substitute for this step.
2. Preview:
   `python3 /opt/gold/tools/repair_phantom_ledger.py --root /opt/gold`
3. Only if the preview matches the preserved evidence:
   `python3 /opt/gold/tools/repair_phantom_ledger.py --root /opt/gold --apply --engine-stopped`
4. Run `python3 /opt/gold/tools/check_data.py /opt/gold`. Require zero failures.
   If it fails, do not restart; reconcile remaining defects. Preserve the printed
   backup path. If interrupted during the two separate file replacements, restore
   BOTH originals while stopped before retrying.
5. Record the data repair via the host's normal data-collection workflow (do not
   leave tracked data changes that block deploy), then restart verified `goldbot`,
   monitor status/first trade, and restore the autosync schedule.

Validation: full smoke suite PASS (new zero-geometry, invalid-tick and negative-
balance restart cases), seven hermetic repair tests PASS (including SELL TP/BE/SL,
BUY with SL 4172, full-20-row ledger, backup/apply, repeat-apply refusal and dry-run),
py_compile PASS. Real snapshot dry-run identifies **20 rows** and $150.69 reference equity.

End-to-end rehearsal on a temporary copy of all four synced runtime files:
backup/apply quarantined 20 rows, restored $150.69, and check_data reported
**0 fail, 8 warn** (historical informational warnings). The repository's reconciled
trades.csv/status.json (624 rows, $150.69) replaces the corrupted snapshot; originals
preserved in `incident_backups/` (private, git-ignored). Replay calibration still reports
100% entry-stream / side+price recall for the 0.75R master and max-hold books;
structural-stop guard PASS. No experiment thresholds or cutovers changed.
No strategy parameters were altered; the engine was stopped for the repair.
