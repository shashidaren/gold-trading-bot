# ANALYSIS — 2026-10-16: the Telegram ping layer (`notifier.py`)

**Session type: tooling + dashboard, no runtime change.** `engine.py`, `trade_filter.py`,
every parameter, gate and exit: untouched. The struct-stop window (entries ≥ 2026-10-06
03:00 UTC) remains the only live experiment and stays un-stacked. This doc records what
shipped, why each design choice was made, and — the part that matters most here — what a
ping is allowed to say.

## 0. The request and the honest reading of it

> "The buy/sell indicator in dashboard works well. Could we add a telegram message to
> ping the best time to start buying or selling."

The dashboard's buy/sell indicator is the 2026-10-16 read layer (`pressure.py`): the tape
composite and the engine's own gates read back on the last closed bar. Its calibration
(`docs/ANALYSIS-2026-10-16-dashboard-pressure.md`) says plainly that the composite is
**collinear with side — not separable within-side**: the trend gate keys side on
EMA50 vs EMA200, so "buy pressure" is high at BUY entries by construction. There is
therefore no honest reading of "the best time to buy or sell" that this repo can push to
a phone **as a signal**. What it *can* push, without inventing an edge it does not have:

1. **When the engine's own 8 entry gates are all green on a closed bar** — the closest
   thing to "a good time" that is not an opinion: it is the bot's own rule, read back.
   The engine already pings when it *takes* such a bar; what is new is the ping when it
   **cannot** — cooldown, blackout, breaker, or already in a position. Context: 28 setups
   were blocked in the last 24 h at the 14:59 UTC view (19 cooldown, 9 blackout); every
   one of them passed the entry gates first.
2. **When the tape gauge the user watches flips into its strong band** — as *context*,
   with the calibration verdict in the message footer, every time.

Both are descriptions of the same read-only layer the dashboard renders. Neither is an
entry condition; neither can become one without a pre-registered bar (HANDOFF §6.7/§11).

## 1. What shipped

| File | Change |
|---|---|
| `notifier.py` (new, repo root) | The ping module: pure decision core `evaluate()`, message renderers, stdlib-only Telegram sender (urllib — no `requests`/`dotenv`, so it imports anywhere the dashboard does), state dot-file for dedupe across restarts, CLI (`--once` default, `--loop`, `--dry-run`, `--test`, `--status`, `--root DIR`). |
| `dashboard.py` | Import guard + `start_notifier_thread()` (daemon, idempotent, `GOLD_NOTIFIER=0` kill switch), started in `__main__` before `app.run`; a header line `🔔 Telegram pings: on · last ping …`. |
| `tools/smoke_test.py` | **Scenario V** (29 checks): module hygiene (AST: stdlib+`pressure` only; the only writes are `save_state`'s own state file; `evaluate()` and renderers are pure — no clock/network/files), full trigger semantics, state round-trip, CLI end-to-end on a synthetic root, static dashboard-wiring checks (no flask import needed to run the smoke gate). |
| `docs/HANDOFF.md`, `README.md`, `.gitignore` | Handoff §1/§6/§9/§10 + era row; README rows; state dot-file ignored. |

**Deploy classification (autosync, `docs/AUTOSYNC.md` §2):** `dashboard.py` changed →
`DASH_CHANGED` → the dashboard service restarts, **`goldbot` does not**. `engine.py` /
`trade_filter.py` byte-identical to `main` (verified below). One caveat to remember: a
future **`notifier.py`-only** change does not touch `dashboard.py`, so autosync will NOT
restart the dashboard and the running process keeps the old notifier in memory — pair
such a change with a dashboard restart (or any `dashboard.py` edit) in the same merge.

## 2. Trigger semantics (what fires, what never does)

State: `.pressure_notifier_state.json` in the data dir (gitignored; the only file the
module writes, atomic tmp+rename; an unwritable path degrades to in-memory state).

**Common guards — a ping needs all of them:**
- **Fresh feed only**: last bar ≤ 240 s old (`GOLD_NOTIFIER_FEED_MAX_AGE`). A closed or
  stalled market must not re-ping Friday's tape all weekend; this is also why the
  2026-09-29 outage signature (frozen file) can never produce pings.
- **Each closed bar evaluated exactly once** (`as_of` dedupe) — edge semantics are
  per-bar, and a re-poll of the same bar can never double-fire.
- **First bar after a fresh state is recorded, never pinged** — a process restart (or a
  wiped state file) must not spam. Consequence found by Scenario V and fixed: the state
  is persisted on *every* evaluated bar, not only when something fired — otherwise the
  module could never get past "first bar" and would stay silent forever.
- **Rate limits**: per trigger+side (setup 20 min, tape 45 min) and a global 5-min gap
  between any two pings. Two triggers firing on the same bar count as one event and both
  go out (the global gap is checked across evaluations, not within one — that was the
  first design bug Scenario V caught).

**🎯 Setup ping** — fires on the *rising edge* of `setup[side]["ready"]` (all 8 active
gates green on the last closed bar), re-armed when the side goes not-ready. Message
carries: gates count, bar stamp, close/level/distance in ATR, RSI/ATR, the tape read,
and one honest **engine state line**:
- `Engine: free to trade — its own entry alert follows if it takes the bar`
- `Engine: BLOCKED — SL cooldown 34 min left (2 consecutive SLs → 60 min window)`
- `Engine: BLOCKED — London Open & Early Session Kill-Zone` (blackout)
- `Engine: BREAKER ON — 10/10 daily SLs, trend-side-only`
- `Engine: already in a SELL (#620) — one position at a time, this setup passes unused`

**Suppression rule:** if `status.json` shows the engine opened a trade within the last
5 minutes, the setup ping stays quiet — the engine's own "GOLD BUY SETUP #N" message is
already the ping; a duplicate adds noise, not information. (Race: the notifier polls
every 60 s and can beat the engine's write by seconds; worst case is two messages for
one entry, documented here, accepted.)

**🌡️ Tape ping** — fires when the composite enters the strong band (≥ 70% one way, the
same 70 the dashboard's "Tape pushed … hard" label uses; `GOLD_NOTIFIER_TAPE_STRONG`),
re-armed only after the tape returns to the middle 40–60 band
(`GOLD_NOTIFIER_TAPE_REARM`) or flips to the other strong side. A tape that oscillates
around 70/58 does not machine-gun; a full flip DOWN→UP fires again because it is a new
event. Message carries the composite, its five components (raw values, auditable — same
stance as the dashboard panel) and the setup read.

**Wording (binding):** every message ends with the honesty footer — "context, not a
signal" — and the tape message additionally cites the calibration verdict verbatim.
No message may contain advice phrasing ("buy now", "entry", "go long"); Scenario V pins
the footer and the phrase list on the renderers.

## 3. Run paths (pick ONE)

1. **Default — the dashboard thread.** The dashboard is already a long-running service
   reading the same files; hosting the loop there means zero new services to install and
   autosync restarts exactly the right process on a `dashboard.py` deploy. Credentials
   come from the environment or `<GOLD_DATA_DIR>/.env` (parsed the same way
   `tools/autosync.sh` parses it — values never enter the repo). `GOLD_NOTIFIER=0`
   disables without a code change; `GOLD_NOTIFIER_INTERVAL` (default 60 s, min 30).
2. **Standalone** — `python3 notifier.py --loop` (own process/timer). If used, set
   `GOLD_NOTIFIER=0` for the dashboard thread: both paths share the same state file, but
   two live loops can still race a bar and double-send within the poll window.

Ops on the box, after the merge deploys:
```bash
python3 notifier.py --test        # one test message through the real credentials
systemctl restart <dashboard-unit>   # picks the thread up (autosync does this on deploy)
journalctl -u <dashboard-unit> -f    # "notifier:" lines are the loop's notes/failures
```
The dashboard header shows `🔔 Telegram pings: on · last ping <ts> UTC` — if it says
`off (GOLD_NOTIFIER=0)` or an import error, the badge says so.

## 4. What this does NOT authorize

- No gate, no threshold, no entry condition changed. `engine.py`/`trade_filter.py` are
  byte-identical to `main` (git diff empty; smoke A–T all still green).
- No number the notifier reads may become an entry condition without a pre-registered
  bar (HANDOFF §11) — the setup ping is a *read-back of existing gates*, not a new one.
- The struct-stop window judgement (2026-10-19 21:00 UTC or n=150) is untouched; the
  notifier's "setup ready" counts the same 8 gates the engine has always counted.
- Pings are not evidence. They are not a backtest, not a sample, and must never be cited
  in a review as one.
- The engine's own alerts (entry/TP/SL/BE/TIME, stale feed) are unchanged and remain the
  authoritative stream; the notifier only adds the two reads above.

## 5. Verification (2026-10-16, this session)

- `python3 tools/smoke_test.py` → **SMOKE TEST PASSED** (A–V; Scenario V = 29 new checks,
  hermetic: synthetic data, injected clock, no network — dry-run/`sender=None` paths).
- `python3 -m py_compile engine.py trade_filter.py notifier.py dashboard.py` + all of
  `tools/*.py` → clean.
- `python3 tools/check_data.py` → **0 fail**, 8 warn (unchanged warnings).
- `python3 tools/win_rate_report.py`, `momentum_regime.py`, `strategy_lab.py
  --calib-only`, `check_structural_stop.py` (PASS, cutover bracket intact),
  `pressure_report.py`, `strategy_lab.py --bars forward_test_log.csv` → all run clean.
- `git diff main -- engine.py trade_filter.py` → empty (no runtime change).
- Dashboard exercised locally on this checkout with flask: page renders 200 with the
  badge; thread starts once, is idempotent, daemon, and `GOLD_NOTIFIER=0` kills it.

Known limitations (accepted, recorded):
- Two messages can arrive for one engine entry (notifier races the engine's own alert by
  seconds on the same bar) — see the suppression rule above.
- In-memory state fallback (unwritable data dir) weakens restart protection to
  per-process; pings still dedupe within the process.
- A gunicorn-style multi-process dashboard would run one loop per worker; the deployed
  run path is the single-process `python3 dashboard.py` service (if that ever changes,
  move the loop to `notifier.py --loop` under its own unit and set `GOLD_NOTIFIER=0`).
