# Analysis — 2026-09-28: "win ratio looks better when the gold price is reducing"

**Question (user):** the win rate seems to improve when gold is falling — is the
strategy doing better in a falling market?

**Verdict: partly, but not the way it sounds — and the naive version is
refuted by our own data.** Pooled across the book, falling-tape entries do have
a higher decisive WR (30.7% vs 25.0% on a 60-min lookback), and the last week —
the 09-22→09-25 bleed followed by the 09-27/09-28 slide — sharpened that gap.
But three tests break the simple reading:

1. **Day-level: nothing.** On days gold fell, the book went 27.9% decisive
   (−$0.59/trade); on days gold rose, 28.1% (−$0.72/trade). "Gold's daily
   direction" is not a predictor in this sample.
2. **It is the side, not the tape.** The trend gate makes momentum and side
   nearly collinear: 94% of falling-60m entries are SELLs and 96% of rising-60m
   entries are BUYs. The measured "falling-tape" effect is mostly the
   **SELL-vs-BUY** effect, and the whole-book SELL/BUY gap (34.0% vs 22.3%) is
   not statistically significant (Fisher p = 0.070).
3. **Within side, falling tape is *worse*.** BUYs that fire into falling tape
   are the single worst bucket in the book: 13 trades, 2W/11L, 15.4% decisive,
   −$2.12/trade. And in the one clean up-leg (09-17→09-18) the pattern inverts:
   BUY 45.0% decisive / +$10.01 vs SELL 12.5% / −$21.37.

Nobody should trade this as a filter yet: an entry-filter change during the
max-hold isolation window would break the isolation (§6).

Sample: **380 closed trades, 2026-09-04 08:20 → 2026-09-28 05:45 UTC**
(24,398 1-min bars), 0 TIME exits, 1 active trade (#382).
Reproduce:

```bash
python3 tools/check_data.py            # 0 fail / 9 warn
python3 tools/win_rate_report.py       # baseline, eras, side split
python3 tools/momentum_regime.py       # the new tool built for this question
```

---

## 1. The observation, quantified

Momentum = close-to-close change **strictly before entry** (bars up to entry − 1
min, honouring the ~1-min feed lag; no lookahead). Buckets are split at zero.

| Pre-entry window | Falling tape | Rising/flat tape | Fisher p |
|---|---|---|---|
| 30 min | n=205, 30.1% dec, −$0.42/t | n=175, 25.7%, −$0.87/t | 0.55 |
| 60 min | n=202, **30.7%** [23.0–39.7], −$0.38/t | n=178, **25.0%** [17.7–34.1], −$0.90/t | 0.37 |
| 120 min | n=206, 32.1%, −$0.35/t | n=174, 23.6%, −$0.95/t | 0.18 |
| 240 min | n=198, 33.6%, −$0.35/t | n=182, 22.5%, −$0.92/t | 0.072 |
| Since 00:00 UTC | n=211, 29.7%, −$0.48/t | n=169, 26.2%, −$0.81/t | 0.65 |

So the sign is consistent across windows (falling > rising in WR *and* in
P&L/trade) and it strengthens with the lookback — but **no window is
significant**, the CIs overlap heavily, and the effect is not independent of
side (§2).

Where the impression comes from: the recent slide.

| Window | n | Decisive WR | P&L | $/trade |
|---|---|---|---|---|
| 09-22 → 09-25 (the bleed) | 83 | 22.9% | −$93.55 | −$1.13 |
| 09-27 + 09-28 (the slide) | 12 | 66.7% | +$38.60 | +$3.22 |

09-28 alone was 9 SELLs: **5 TP / 1 SL / 3 BE, +$39.41**, all nine entered
between −7 and −36 dollars per 60 min (−4 to −9 · ATR), i.e. deep in a
−1.9% gold day. That single day is what "the win ratio is improving" is seeing.

## 2. Why "falling tape" is mostly "the SELL side"

The signal funnel gates BUY on EMA50 > EMA200 and SELL on EMA50 < EMA200. In
practice that couples direction to side almost perfectly:

| Momentum bucket | n | BUY share | SELL share |
|---|---|---|---|
| falling 60m | 202 | 13 (6%) | 189 (94%) |
| rising 60m | 178 | 171 (96%) | 7 (4%) |

And the side gap is the bigger, more stable number:

| Era | BUY | SELL | Fisher p |
|---|---|---|---|
| All data (n=380) | n=184, **22.3%** [15.6–30.9], −$1.05/t | n=196, **34.0%** [25.6–43.4], −$0.23/t | 0.070 |
| 0.75R era (n=205) | n=104, 26.6%, −$0.94/t | n=101, 33.8%, −$0.16/t | 0.37 |
| Max-hold era (n=110) | n=41, **14.3%**, −$2.05/t | n=69, **36.5%**, +$0.15/t | 0.041 |
| Max-hold era ex-09-28 | n=41, 14.3%, −$2.05/t | n=60, 30.4%, −$0.48/t | 0.16 |

SELL out-performs BUY in every era — that part is consistent — but the only
sample where the gap is nominally significant is the max-hold era, and **one
day (09-28) carries it**: drop that day and p → 0.16. n=380 with a 12-pp gap is
still a coin-flip test.

Structural note: nothing in the exit geometry differs between sides (2×ATR /
3×ATR / 0.75R ratchet are symmetric), but two risk gates are asymmetric — the
London blackout blocks BUYs only, and the daily breaker degrades to
trend-side-only. Those affect *which* trades are taken, not their outcome
geometry, so they cannot manufacture the measured WR gap; they only shrink the
BUY sample (184 vs 196 trades — small).

## 3. The three refutations

**(a) Day-level null.** Down days: 275 trades, 27.9% decisive, −$0.59/trade.
Up days: 105 trades, 28.1%, −$0.72/trade. If "gold falls → bot wins" were a
market-regime edge, this table — the bluntest version of the claim — would show
it. It does not.

**(b) Within-side refutation.** If falling price were good *per se*, BUYs in
falling tape should be fine. They are the worst thing in the book:

| | falling 60m | rising 60m |
|---|---|---|
| BUY | n=13, 2W/11L, **15.4%**, −$2.12/t | n=171, 23.2%, −$0.97/t |
| SELL | n=189, 32.7%, −$0.26/t | n=7, 3W/2L, 60.0%, +$0.61/t |

The falling-tape advantage lives entirely in the SELL row: it is "shorting into
a falling market works better than buying a bounce in a falling market", not
"falling price is good". Note the BUY/SELL split of the counter-trend buckets is
too thin to conclude anything on its own (13 and 7 trades).

**(c) Instability / up-day inversion.** 5-day chunks of the falling-vs-rising
60-min gap:

| Chunk | Falling | Rising |
|---|---|---|
| 09-04..09-08 | n=5, 0.0%, −$2.86/t | n=20, 15.0%, −$1.89/t |
| 09-09..09-13 | n=46, 13.3%, −$0.90/t | n=29, 23.5%, −$1.05/t |
| 09-14..09-18 | n=74, 36.1%, −$0.32/t | n=86, 36.8%, −$0.14/t |
| 09-19..09-23 | n=45, 22.9%, −$1.05/t | n=24, 25.0%, −$1.48/t |
| 09-24..09-28 | n=32, **52.2%, +$1.55/t** | n=19, **7.7%, −$2.38/t** |

The whole effect is **three trading days old** (09-24 → 09-28). Before that the
chunks are flat-to-reversed (09-14..09-18 is a dead heat; 09-04..09-13 slightly
favours rising tape).

The up-leg counter-case is concrete. Gold rose +1.74% on 09-17 and +0.72% on
09-18 (the only multi-day up-leg in the book — the 09-02/09-03 rally predates
the first trade on 09-04, and the book window is a net −6.7% slide from
$4479.68 to $4180.98):

| 09-17 + 09-18 | n | Decisive WR | P&L |
|---|---|---|---|
| BUY | 30 | **45.0%** | **+$10.01** |
| SELL | 10 | 12.5% | −$21.37 |

Exactly the mirror image of the last week. The honest one-line summary is:
**the bot is (weakly) trend-following, and it looks good when gold falls
because its SELL half is firing; it looks bad when gold rises because its BUY
half is firing.** That is a regime bet, not a "falling price" edge — and with
one up-leg in the sample we cannot yet tell whether the SELL half is genuinely
better or just the side that happened to be on during a −6.7% month.

## 4. What does survive (and what it is worth)

- **The recent bleed was the BUY side.** Max-hold era: BUY n=41, 4W/24L/13BE,
  14.3% decisive, −$84.07 (≈ −$2.05/trade); SELL n=69, 19W/33L/17BE, 36.5%,
  +$10.69. Ex-09-28 the SELL book is still 30.4% / −$0.48 — better than BUY but
  not profitable.
- **Directionally consistent across eras, never confirmed.** SELL > BUY in WR in
  every era; the trend-alignment cut (entering *with* the 240-min move) shows
  the same weak tilt: aligned 28.8% vs against 22.2% (p=0.65), and again the
  premium is almost entirely in SELL (35.5% aligned vs 23.1% against) while BUY
  is flat (22.4% vs 21.4%).
- **Nothing here rescues the headline.** The 0.75R era is at 30.5% decisive
  [23.5–38.5] / −$0.56 per trade, still below the −$0.40 falsification bar. The
  "improvement" the user noticed moved the era from −$0.78 to −$0.56; it did
  not flip the sign, and it rests on two days.

**Multiple-comparison caveat:** this question was asked after the fact, and the
cut was searched over 5 momentum windows × 2 sides × 5 eras × 2 directions.
A p≈0.07 in that search space is what noise looks like. The strongest single
number in this document (BUY-vs-SELL in the max-hold era, p=0.041) survives
exactly until 09-28 is removed.

## 5. Registered candidate (NOT adopted)

Refined, falsifiable version of the user's observation — registered here so the
next review can test it without moving goalposts:

> **H-side-awareness:** entries aligned with the prevailing move are better than
> counter-trend entries *within each side* (i.e. SELLs in falling tape and BUYs
> in rising tape beat their counter-trend counterparts), robustly across gold
> regimes.

**Pre-registered bar — any momentum/side gate must clear ALL of these at the
2026-10-05 max-hold re-review, otherwise it is dropped (no partial adoption,
no re-slicing):**

- **(a)** ≥25 decisive outcomes in the counter-trend bucket (the filter target);
- **(b)** ≥5 pp decisive-WR gap, same direction, **separately within BUY and
  within SELL** — a gap that lives only in the side mix is a regime effect, not
  a momentum edge;
- **(c)** the gap must also hold in at least one rising-gold sub-period
  (≥1 day, gold up ≥0.5%) — an effect that only exists while gold falls is a
  regime bet;
- **(d)** no worse than −$0.10 on P&L/trade vs the current book on the same
  sample;
- **(e)** a REVIEW/ANALYSIS doc + isolation window before it goes live.

Current scoreboard against that bar: **(a) fails** (13 and 7 trades), **(b)
fails in the BUY direction** (falling tape is *worse* for BUYs), **(c) fails**
(09-17/09-18 inverts), so nothing is adopted. The tool prints this bar on every
run (`tools/momentum_regime.py` §8).

**Explicitly rejected by this analysis:** "favour falling-tape entries" /
"trade less when gold rises" as blanket rules — direction-blind version is
refuted by §3(b), and the BUY-side-only version is under-powered.

The already-queued **BUY-side momentum gate** (HANDOFF §6 item 2(e), there named
`H-side-awareness`) should be read as the same hypothesis; it stays queued behind
the re-review and must be scored against the bar above.

## 6. Isolation window — why nothing changes today

The max-hold time stop (PR #15, live 09-21) is in its pre-registered ~2-week
isolation. Adding an entry filter now would (i) break the isolation and
(ii) confound the max-hold read with a filter that is, on this evidence, not
yet distinguished from noise. No parameter, gate, or engine change in this
cycle — this document plus the tool are the deliverable.

## 7. Ledger refresh (as of 2026-09-28 05:59 UTC, `status.json`)

| Book | n | Result | Decisive WR [95% CI] | P&L | $/trade |
|---|---|---|---|---|---|
| All | 380 | 61W/157L/162BE/0TIME | 28.0% [22.4–34.3] | −$238.19 | −$0.627 |
| 0.75R era (≥09-15 06:00) | 205 | 43W/98L/64BE | 30.5% [23.5–38.5] | −$113.99 | −$0.556 |
| Max-hold era (≥09-21 06:00) | 110 | 23W/57L/30BE | 28.8% [20.0–39.5] | −$73.38 | −$0.667 |
| 0.30R era (09-10→09-15) | 130 | 10W/22L/98BE | 31.2% [18.0–48.6] | −$41.69 | −$0.321 |
| Pre-ratchet (n=45) | 45 | 8W/37L/0BE | 17.8% [9.3–31.3] | −$82.51 | −$1.834 |

True P&L from $500: **−$238.19 → $261.81**; engine ledger $278.78 (drift
+$16.97, unchanged order of magnitude). 0 TIME exits; longest max-hold-era
hold is far below 240 min. Max-hold era improves to −$0.667/trade but remains
below the −$0.40 bar; fallback step 2 (ratchet-off) still queued behind the
10-05 re-review.

## 8. Data notes / gotchas hit while doing this

- **No lookahead on momentum:** the price log lags `trades.csv` entry times by
  ~1 min, so all momentum is measured at `entry − 1 min`. Measuring at the
  entry minute itself mixes the entry bar into the signal.
- `tools/momentum_regime.py` needs no ratchet geometry (outcomes come from
  `Exit_Reason`, P&L from `Profit`), so the
  `Stop_Loss == Entry_Price` logging quirk is irrelevant here — unlike the
  replay tools.
- Momentum sign is measured on the **broker demo GOLD feed** prices (~4.4k
  scale), not spot XAUUSD — the sign transfers, the dollar magnitudes do not.
- The first trade in the ledger is 09-04 08:20, so the 09-02/09-03 gold rally is
  *not* in the sample; the book contains exactly one up-leg.
- `status.json` reads 382 trades vs 380 closed rows in the ledger (1 active
  #382; the known stale-vs-ledger resync warning from `check_data.py`).
