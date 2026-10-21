# ANALYSIS 2026-10-21 — is the tape choppy, what is the last break doing, and when should the box watch say something?

**Status:** display + tooling only. **No** `engine.py` / `trade_filter.py` change, no
parameter, gate, exit or strategy change. The open **struct-stop window** (entries ≥
2026-10-06 03:00 UTC) and its 2026-10-19 judgement are untouched. The Telegram
notifier in §5 places no order and is not installed by this change.

**Owner ask:** *"buy watch above and sell watch below is pretty accurate, but maybe
market is choppy past few days .. is there anything u can improve further or maybe
also include a telegram message once we get good indicators."*

**Short answer, in three parts:**

1. **"Is it choppy?" is now measured, and the answer on today's tape is: not
   unusually.** 14 of the 18 box breaks in the last 24 h closed back inside within
   15 min (78%) against a 74% baseline over the 50 days in view. What *is* true is
   that the tape is **range-bound and compressed**: the efficiency ratio is 0.04
   over 60 bars and the 20-bar box is 3.0 ATR wide against a 4.7 ATR median.
2. **The chop intuition does not survive measurement as a filter — and my first
   measurement said it did.** The 10 pp separation I found on overlapping events
   (§2) vanished, and in places reversed, under this repo's one-position
   convention. That is the same trap as the 09-28 pooled-momentum error, so it is
   written down here rather than quietly dropped.
3. **Retests are now tracked** on a box frozen at the break — 94% of breaks are
   retested within 30 bars, median 3 — and **entering the held retest showed no
   edge** (59.0% vs a 57.2% reference, the same −$0.31/trade as entering the
   break). So the tracker is a *status* read, not a filter, and the dashboard says
   so on the card.

**Files:** `pressure.py` (`box_chop`, `box_retest`, `box_regime`, `box_alert`,
`box_alert_suppressed`, `box_alert_record`), `tools/box_alert.py` (new, the sender),
`deploy/boxalert.service` (new, optional), `tools/box_report.py` (`--alert-scan` +
the §4b regime section), the dashboard's 📦 tab, `tools/test_box_alert.py` (new, 22
tests), `tools/autosync.sh` (advisory digest line + optional restart).
Everything is reproducible with `python3 tools/box_report.py --alert-scan`.

---

## 1. What was added, and what each piece is allowed to do

| piece | where | what it is | what it is **not** |
|---|---|---|---|
| **Chop read** | `pressure.box_chop()` → dashboard "🌊 Is the tape choppy?" + `box_report` §4b | the false-break share of the engine's own 20-bar box, recent 24 h vs the span in view, plus the efficiency ratio and box-width-vs-median | a filter. It never changes the verdict, the cards or an alert (§2) |
| **Retest tracker** | `pressure.box_retest()` → both watch cards | the last break of the 20-bar box, on a box **frozen at the break bar**, classified `extended` / `retesting` / `held` / `failed` | an entry rule. Entering the held retest measured no edge (§3) |
| **Telegram notifier** | `tools/box_alert.py` + `deploy/boxalert.service` | one message when the display conditions all line up, rate-limited | a signal, an edge, or a trading path (§4–§5) |
| **Alert preview** | dashboard 📦 tab | the exact text the sidecar would send, or why it is held | a sender. The dashboard never sends anything |

The decision itself lives in `pressure.box_alert()` and the rate limiter in
`pressure.box_alert_suppressed()` / `box_alert_record()`, both pure. The sidecar,
the dashboard preview and the `--alert-scan` replay therefore run the **same** code
and cannot disagree — the reason `box_report.py` does not re-implement the rule.

## 2. Is the tape choppy? — and does chop matter? (the negative result)

### 2.1 The read that shipped

A **break event** = a close outside the 20-bar box built from the bars strictly
before it (the engine's own level). Its **false-break** flag = any close back inside
that box within 15 min. Events are counted **sequentially** (the next one is only
considered after the previous one's 60-min forward window closes), which is
`tools/box_report.scan()`'s convention, and the newest event is excluded while its
15-min window is still open, so a break in progress cannot bias the read.

At the 2026-10-21 14:59 UTC snapshot:

| read | value |
|---|---|
| breaks, last 24 h | 18 (14 closed back inside within 15 min = **78%**) |
| baseline in view | **74%** of 115 completed events over 50 days |
| efficiency ratio (|net| / Σ|step|) | 60 bars **0.04** · 240 bars **0.02** |
| 20-bar box width | **3.0 ATR** now vs **4.7 ATR** median in view |
| verdict shown | `normal` chop — the tape is behaving like its own baseline |

The honest reading: **breaks are failing at the usual rate, but the tape is going
nowhere** (efficiency 0.04 is deep in the sideways range) **and the box is
compressed** (3.0 vs 4.7 ATR). Those two facts, not "unusual chop", are what the
last few days look like on this log.

### 2.2 The trap: overlapping events manufacture a filter

Measured on every close-outside-the-box (**6083 overlapping events** — wrong sample,
kept here because it is the mistake):

| pre-break read | n | target-first | 95% CI | ref | E/trade |
|---|---|---|---|---|---|
| prev-20-break false-break share ≤ 0.60 ("clean") | 812 | 62.9% | 59.6–66.2 | 54.6% | **+$1.04** |
| 0.60–0.80 | 1913 | 55.7% | 53.4–57.9 | 55.1% | −$0.34 |
| > 0.80 ("choppy") | 1179 | 52.3% | 49.5–55.2 | 55.2% | **−$1.24** |
| ER60 > 0.20 ("trending in") | 1041 | 59.0% | 56.0–61.9 | 55.3% | +$0.24 |

A clean 10 pp separation, an "EDGE" cell, a filter that looks worth gating on.

### 2.3 The same read under the one-position convention (681 sequential breaks)

| pre-break read | n | target-first | 95% CI | ref | E/trade | verdict |
|---|---|---|---|---|---|---|
| prev false-break share ≤ 0.55 ("clean") | 55 | 60.0% | 46.8–71.9 | 54.9% | +$0.51 | no edge |
| 0.55–0.80 | 332 | 54.2% | 48.8–59.5 | 55.3% | −$0.74 | no edge |
| > 0.80 ("choppy") | 118 | 61.9% | 52.9–70.1 | 56.0% | +$0.54 | no edge |
| ER60 > 0.20 | 117 | 58.1% | 49.1–66.7 | 55.6% | +$0.28 | no edge |
| ER60 ≤ 0.20 | 388 | 56.2% | 51.2–61.0 | 55.3% | −$0.49 | no edge |
| clean **and** ER60 > 0.15 | 30 | 63.3% | 45.5–78.1 | 55.3% | +$1.37 | no edge |

The ordering **reverses**: the "choppy" bucket is the best of the three. Why the
first table lied: with overlapping events the "previous 20 breaks" are the previous
few *minutes* of the same move, so the read is mechanically correlated with the
outcome it is supposed to predict.

### 2.4 And the version that cannot cheat: the **prior trading day**

A pre-known, non-overlapping read (43 day-clusters, so very low power — stated, not
hidden):

| prior day | n | target-first | 95% CI | ref | E/trade |
|---|---|---|---|---|---|
| false-break share ≤ 0.60 | 88 | 51.1% | 40.9–61.3 | 55.1% | −$0.60 |
| false-break share > 0.60 | 413 | 58.1% | 53.3–62.8 | 55.4% | −$0.21 |

Wrong way round again, and nothing clears its reference. **Conclusion: the chop read
is context. It is displayed with these numbers attached (`BOX_CHOP_MEASURED` travels
with every read) and it gates nothing.** If it is ever proposed as a gate, §2.2–§2.4
is the evidence that has to be beaten first, with a pre-registered bar (§11).

## 3. What is the last break doing? — the retest tracker

The rolling bounds in `box_geometry()` move every bar, so they cannot answer "was
that level retested and did it hold?" — the 2026-10-20 cards said so explicitly.
`box_retest()` now freezes the box **at the break bar** and walks forward:

| state | meaning |
|---|---|
| `extended` | still beyond the edge; the edge has not been touched again |
| `retesting` | the frozen edge was touched (≤ 0.25 ATR) and the close has not got back beyond it |
| `held` | after that touch, a close back beyond the edge |
| `failed` | a close back inside the box by > 0.10 ATR — the break is dead |

A break **episode** is taken as the first bar of the last run of same-side fresh
breaks. Without that, the lagging box makes *every* bar of a sustained move a fresh
break and the tracker freezes on the newest bar instead of the move's start (found
while writing the tests, not before).

Measured on the 681 sequential breaks:

| fact | value |
|---|---|
| touched the frozen edge within 30 bars | **642 / 681 = 94%** (median wait **3** bars, p90 15) |
| re-broke after the touch ("held") | 554 (86% of those touched) |
| touched, never re-broke | 84 — and **98%** of them were false breaks |
| entry at the break (G3: stop past the far edge, TP 1 box) | 56.6% [52.3–60.9] vs **55.4%** ref · **−$0.31**/trade |
| entry on the **held retest**, same geometry | 59.0% [54.1–63.7] vs **57.2%** ref · **−$0.31**/trade |

So: a retest is nearly always coming, waiting for it raises both the hit rate *and*
the reference by about the same amount, and expectancy is identical. **The tracker
tells you what the break is doing right now — including the `failed` state, which is
the one worth seeing before you add to a position — and it filters nothing.**

## 4. When should the watch say something? (the alert rule)

`pressure.box_alert()` fires only when **all** of these are true:

1. a **fresh close beyond a box edge** (the checklist's own trigger) — never a
   rejection/fade: fades measured worst of the four geometries, 66% of R in cost and
   10.4% vs a 10.4% reference;
2. `feed`, `session`, `risk_state` and `volatility` all **pass** (an unavailable
   read blocks — the same rule the cards already apply);
3. the spread is ≤ **10% of R** on the far-edge stop (`BOX_COST_SHARE_OK`);
4. the close is not more than **1 ATR** beyond the edge (the cards' do-not-chase
   line);
5. the last break of that box has not `failed`.

Anything else returns `fire: False` **with the reasons in words**, which is what the
dashboard's "Held" panel prints. The message body carries the levels, the costed
payoff, the retest state, the chop read and the measured base rate, because the
message is a notice that the conditions line up — not a forecast:

```
📦 gold box watch — BUY candidate (context, not a signal)
box: 20-bar level (engine's own) 4128.72-4135.10
break: closed 4135.62 beyond the high 4135.10 (0.33 ATR) at 14:59 UTC
entry ref 4135.62 · stop 4128.40 (past the far edge) · target 4142.00 (1 box)
risk $7.22 · reward $6.38 · gross 0.88:1 · costed 0.75:1 · spread 8% of R
retest: extended — closed beyond $4135.10 1 bar(s) ago and is still out there …
tape: 14 of 18 breaks in the last 24 h closed back inside within 15 min (78%) vs 74% …
measured: 8 box geometries tested, 0 cleared the no-edge reference; 74% of breaks fail within 15 min
display only — no order placed, engine unchanged. Max 1 per 30 min overall, 1 per 90 min per box edge, 6/day.
```

### 4.1 How loud is it? (measured, not guessed)

`python3 tools/box_report.py --alert-scan` replays the last 7 days through the live
decision **and** the live limiter:

| | |
|---|---|
| fresh-break bars replayed | 722 |
| **messages** | **36 = 5.1/day** (median 6, busiest day 6, 6 of 7 days with at least one) |
| suppressed | 87 by the 30-min spacing · 0 by the per-edge cooldown · 203 by the daily cap |
| sides | BUY 17 · SELL 19 |
| declined because | feed 131 · volatility 101 · session 78 · no fresh break 7 · chase 3 · spread share 3 |

The 30-min **global** spacing was added after the first replay: without it, three
boxes breaking in the same minute produced three messages 60 seconds apart
(03:30/03:31/03:32 on 10-21). The daily cap binds most days, so `GOLD_BOX_ALERT_DAILY_CAP`
is the knob that actually controls volume.

**Two honesty notes printed with that table:** the portfolio gates (SL cooldown,
daily breaker) are not in the tape, so the replay assumes neither is active and the
feed is fresh — this is an **upper bound**; and a message count says nothing about
expectancy. **The cooldowns are spam control, not a claim that waiting pays** — §2
and §3 are the measurements that would have to say otherwise, and they do not.

## 5. Running it

```bash
python3 tools/box_report.py --alert-scan          # live boxes + regime + the alert replay
cd /opt/gold && set -a && . ./.env && set +a
python3 tools/box_alert.py --once --dry-run       # the decision + the text, nothing sent
python3 tools/box_alert.py --test                 # proves the bot/chat work
python3 tools/box_alert.py --quiet                # the autosync digest line
sudo cp deploy/boxalert.service /etc/systemd/system/boxalert-gold.service
sudo systemctl daemon-reload && sudo systemctl enable --now boxalert-gold
```

Stdlib only; the only file it writes is its own `box_alert_state.json`
(git-ignored). `GOLD_BOX_ALERTS=0` disables it without uninstalling. Autosync
restarts it when `tools/box_alert.py` or `pressure.py` changes, and its digest line
(`🔔 box alerts: …`) is advisory — it never blocks a deploy and never touches
`goldbot`. A dashboard/pressure change is still a **dashboard-only** deploy.

## 6. Verification (what was actually run)

| check | result |
|---|---|
| `tools/test_box_alert.py` (new) | **22 tests pass** — chop states, the 5 retest states + SELL mirror, every alert blocker, the limiter (spacing → per-edge → cap → day rollover), the sender with no credentials, `decide_once` with an injected sender |
| `tools/test_box_watch.py` | 6 pass (unchanged strings still hold; retest enrichment only applies when a retest exists) |
| `tools/test_box_report.py` | 14 pass, including the "imports only stdlib + pressure" and "never writes" guards |
| `tools/test_dashboard_context.py` | 13 pass with Flask 3.1.3 in a local venv; the render test now pins the chop panel, the alert preview and the absence of the old "Retest: not tracked" line |
| `tools/smoke_test.py` | **SMOKE TEST PASSED** — including Scenario U's `pressure.py` read-only AST check and the mirrored-constant gate |
| `tools/box_report.py --alert-scan` | runs clean on the checked-in 47,379-bar log (~22 s) |
| `bash -n tools/autosync.sh` | syntax ok |
| **not run** | a real Telegram send (no outbound access to `api.telegram.org` from the sandbox), and nothing on the production host — install and merge remain the owner's actions |

## 7. Limits

- 50 days, one instrument, one venue, one regime. §2 and §3 are screens with low
  power (43 day-clusters for the prior-day read, n=55–118 per sequential bucket) and
  were **not** pre-registered. They can justify displaying a number; they cannot
  justify a gate (§11).
- The dashboard's chop baseline is the loaded tail (~50 days at 9000 rows); the CLI's
  is the whole log. The read prints which span it used, because the two numbers are
  not interchangeable.
- The retest tracker freezes the **20-bar** box only, matching the engine's own
  level. A retest of the 1h/4h/prior-day box is not tracked.
- Cost is still the assumed $0.55 round trip (`docs/XM-LOGGER.md`), not a measured
  fill. No slippage, commission or swap.

## 8. Next steps (in order, all optional)

1. Install the sidecar and let it run a week; judge it on **usefulness**, not on
   outcomes — the message count is the thing to tune (`GOLD_BOX_ALERT_DAILY_CAP`).
2. Log manual box trades with the §4.9 fields of the 2026-10-20 analysis and add the
   retest state at entry, so "did waiting for the retest help *me*" becomes a
   measurable question instead of a memory.
3. If anyone wants chop or retest as a **gate**: pre-register a bar first, and beat
   §2.3/§2.4 under the one-position convention. The overlapping-event version (§2.2)
   is not admissible evidence.
