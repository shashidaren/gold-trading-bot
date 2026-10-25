# REVIEW — duplicate trade number #697 in the paper ledger (found 2026-10-25)

**Date:** 2026-10-25 ~01:45 UTC
**Session:** "Execute the plan" — session-start checks on collection 334 (checked-in data through
2026-10-23 20:57 UTC).
**Status:** finding recorded. **No runtime change, no ledger change, no deploy in this session.**
The proposed fix below is for owner review; nothing was coded or shipped.

## 1. What was found

`trades.csv` (synced in autosync commit `fd7e5c4`, "data collection 334") contains
**two rows numbered 697**:

| Trade_Num | Type | Entry | Exit | Reason | P/L | Balance after |
|---|---|---|---|---|---|---|
| 697 | BUY | 2026-10-23 11:17:06 | 2026-10-23 13:46:06 | SL | −8.70 | 137.02 |
| 697 | SELL | 2026-10-23 15:15:07 | 2026-10-23 19:16:06 | TIME | −0.36 | 136.66 |

The SELL trade was opened after the BUY #697 closed, so it should have been numbered **#698**.
`status.json` (last update 2026-10-23 20:57:08) agrees with the CSV rows: `total_trades=697`,
`next_trade_num=698`, 140W/301L/253BE/3TIME — i.e. the *row count* and the balance chain are
internally consistent (137.02 − 0.36 = 136.66 = `equity`); only the `Trade_Num` key is wrong.

## 2. Root cause (latent engine bug)

The paper engine appends a `trades.csv` row **only when a trade closes** (`engine.py`
`log_trade()`), while `next_trade_num` is assigned **when a trade opens**
(`self.current_trade_num = self.next_trade_num; self.next_trade_num += 1`).

At startup the engine runs, in order (engine.py lines 347/349):

1. `load_trade_stats()` — sets `next_trade_num = max(Trade_Num in trades.csv) + 1`.
2. `restore_open_trade_from_status()` — restores an open trade from `status.json`, setting
   `current_trade_num` — **but never restores `next_trade_num`.**

Consequence: after **any restart while a trade is open**, the open trade's row is not in
`trades.csv` yet, so `max(Trade_Num) = open trade's number − 1` and `next_trade_num` is reset to
the open trade's own number. When that trade closes, its row writes correctly, but the
**next** trade opens with the same number.

Reconstruction for #697 (consistent with all checked-in facts):

- 11:17:06 — BUY opens as #697 (in memory `next_trade_num` = 698; `status.json` holds both).
- Engine restarts sometime before 15:15:07 (watchdog/autosync/crash — host-side, unverified).
  At restart, `trades.csv` ends at #696, so `next_trade_num` = 697; the open BUY is restored as
  #697 from `status.json`, but `next_trade_num` stays 697.
- 13:46:06 — BUY closes SL, row #697 written (correct number).
- 15:15:07 — SELL opens: `current_trade_num = next_trade_num = 697` ← **duplicate**;
  `next_trade_num` = 698.
- 19:16:06 — SELL closes TIME, row written as #697 again. `status.json` now shows
  `next_trade_num=698`, which is why the *following* trade (had the book kept trading) would
  have been numbered correctly again.

## 3. Precedent: this is a recurring failure, 5th occurrence

The same duplicate-number pattern appears earlier in the ledger, all left un-repaired:

- **#1, #2, #3** — each appears twice on 2026-09-04 (early era; the morning set 08:2x–08:3x and
  an afternoon set 15:3x–17:0x share numbers).
- **#171** — twice on 2026-09-15 (BE 03:06→03:09, then SL 03:09→03:18, one second apart).
- **#697** — this finding (2026-10-23).

The earlier duplicates pre-date the incident tooling and were never renumbered; the ledger has
simply carried them. `check_data.py` does not flag duplicate `Trade_Num` (it checks schema,
monotonic log timestamps, and status/CSV agreement — all of which hold).

## 4. Impact assessment

- **No current metric or judgement is affected.** Every tool in this repo is row-based:
  `handoff_check` (697 closed rows), `win_rate_report` (n=697; era n=200), the struct-stop
  SCREEN readings, and the gap-ride count (3/2 — keyed on #595/#610/#687, all unique). The
  balance chain and `status.json` counters are mutually consistent.
- **What is broken is the ledger key.** `Trade_Num` is no longer unique: any cross-reference to
  "the 2026-10-23 SELL" by number is ambiguous with the BUY, and number #698 was skipped
  (the SELL carries it). Downstream consumers that join on `Trade_Num` (e.g. the owner's private
  observation log's `bot_trade_id`, dashboard deep links) will hit the ambiguity.
- **It will recur.** The bug is live on the host (same code). Every future restart while a paper
  trade is open — and the autosync deploys restart the engine — will duplicate the next trade
  number, until the code is fixed and deployed.

## 5. Proposed fix (NOT applied — for owner review)

1. **Engine (two lines):** in `restore_open_trade_from_status()`, also restore
   `next_trade_num` from `status.json`, taking the max with the CSV-derived value:

   ```python
   stored_next = data.get("next_trade_num")
   if isinstance(stored_next, int) and stored_next > self.next_trade_num:
       self.next_trade_num = stored_next
   ```

   This cannot move the number backwards (max with the CSV-derived value) and is a no-op when
   no trade is open (the function returns early on `trade_active == false`).
2. **Smoke scenario:** a hermetic test that writes a ledger ending at #N, a `status.json`
   marking trade #N+1 open with `next_trade_num` N+2, restarts the state path, and asserts the
   next opened trade takes #N+2 (pins the 10-23 failure).
3. **Ledger correction (owner's call):** optionally renumber the SELL row #697 → #698 (and
   nothing else). Precedent in this repo is to leave historical rows as found (#1/#2/#3/#171
   are still duplicated), and any evidence modification follows the incident process
   (`docs/REVIEW-2026-10-19-negative-balance.md`: backups first). Either choice is fine for the
   metrics; renumbering makes the key unique, leaving it preserves byte-for-byte history.

**Not done this session, by design:** the plan authorizes the *first eligible step only*
(session-start checks + handoff refresh); an engine change means an engine restart on deploy
inside the open struct-stop window, and a ledger edit is an owner decision. Both are queued for
the owner's discussion.

## 6. Where this leaves the queue

- Gap-guard blocker: **unchanged** (owner-defined registration; do not re-ask the 10-20 three
  questions).
- Quote logger: 10/14 complete days, 1/2 weekends — target not met; $0.40 round trip stays
  registered. New ops note: 10-21 tick stalls up to ~1 h (max `tick_age_s` 3662, 119 STALE rows
  that day) — host-side `mt5quotes` health check belongs in the next host verification.
- DST: the discriminating window opened 2026-10-25 01:00 UTC (EU rule → +2 h). The newest
  checked-in quote row is 2026-10-24 14:59:30 (Saturday, market-closed frozen tick), so **no
  post-transition offset has been observed yet** — re-check from observed rows at the next
  sync; do not guess the rule.
- Next eligible repo action: the owner's review of the fix in §5 (engine two-liner + smoke
  scenario + optional row renumber), then a deploy decision. Until then the checked-in engine
  remains as-is and paper-only.
