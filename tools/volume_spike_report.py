#!/usr/bin/env python3
"""volume_spike_report.py — printed form of the volume-spike localisation read.

Owner ask (2026-11-28): "step down from the 5-minute to the 1-minute chart to
find the exact price level where volume surges; check whether the spike sits
near a recent intraday swing (≈80% of them); and whether a channel-high/low
penetration triggered algorithmic order flow."

The read layer is `volume_spike.py` (repo root, stdlib only, no engine import,
no writes). This CLI is its printed form — the same split as
`manual_plan.py`/`tools/manual_trade.py` and `pressure.py`/`tools/pressure_report.py`.

Usage
-----
    python3 tools/volume_spike_report.py                 # the verdict + tables
    python3 tools/volume_spike_report.py --root DIR      # read DIR/forward_test_log.csv
    python3 tools/volume_spike_report.py --threshold 1.3 # a looser spike definition
    python3 tools/volume_spike_report.py --json          # machine-readable
    python3 tools/volume_spike_report.py --spikes 20     # list the top spikes

Exit 0 always: this is a report, not a gate. Display-only —
no order, no gate, no parameter, and nothing written.

Read this first: docs/ANALYSIS-2026-11-28-volume-spike-localisation.md.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import volume_spike as V  # noqa: E402


def _pct(value, width=5):
    return f"{value:{width}.1f}%" if value is not None else f"{'—':>{width}}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--threshold", type=float, default=V.SPIKE_RATIO,
                    help="seasonally-adjusted volume multiple that counts as a spike")
    ap.add_argument("--tolerance", type=float, default=V.NEAR_SWING_ATR,
                    help="'near a swing' tolerance, in 5m ATR")
    ap.add_argument("--spikes", type=int, default=0, metavar="N",
                    help="list the N largest spikes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = V.load_rows(os.path.join(args.root, "forward_test_log.csv"))
    if not rows:
        print(f"volume_spike_report: no forward_test_log.csv under {args.root}")
        return 2
    rep = V.report(rows, threshold=args.threshold, tolerance=args.tolerance)

    if args.json:
        print(json.dumps(rep, default=str, indent=2))
        return 0

    meta, summary = rep["meta"], rep["summary"]
    print("=" * 78)
    print("VOLUME SPIKE LOCALISATION — display-only, no edge claimed, no writes")
    print("=" * 78)
    print(f"  log            {meta['first_ts']} -> {meta['last_ts']}  ({meta['bars']:,} M1 bars)")
    print(f"  era            {meta['era_start']} onward (MT5 sidecar; pre-era tick counts are frozen)")
    print(f"  buckets        {summary['n_buckets']:,} complete 5m over {summary['days']} days")
    print(f"  spikes         {summary['n_spikes']} at >={meta['threshold']:.1f}x seasonal "
          f"({summary['spikes_per_day']:.1f}/day, {_pct(summary['spike_share_pct'])} of buckets)")
    print()

    print("1. FEED RESOLUTION — can this data localise a spike at all?")
    noise = rep["baseline_check"]
    if noise.get("n"):
        print(f"   within-bucket dispersion      {noise['dispersion_ratio']:.2f}x Poisson")
        print(f"   largest M1 share of the 5m    median {_pct(100*noise['top_minute_share_median'])}"
              f"  p90 {_pct(100*noise['top_minute_share_p90'])}")
        print(f"   spikes with one minute >=50%  {_pct(summary['one_minute_over_50_pct'])}")
        print(f"   penetration extreme in the top-volume minute: "
              f"{_pct(summary['extreme_in_top_minute_pct'])} "
              f"(n={summary['penetration_extreme_n']})")
    print()

    print("2. SESSION PROFILE — why a trailing mean is the wrong baseline")
    print(f"   {'hour':>4} {'buckets':>8} {'median vol':>11} {'median ratio':>13}")
    for row in rep["profile"]:
        if not row["n"]:
            continue
        ratio = row["median_ratio"]
        print(f"   {row['hour']:>4} {row['n']:>8} {row['median_volume']:>11.0f} "
              f"{(f'{ratio:.2f}x' if ratio is not None else '—'):>13}")
    print()

    print(f"3. SWING PROXIMITY — the '~80% of spikes' claim (tolerance {meta['tolerance_atr']:.2f} ATR)")
    print(f"   spikes near a confirmed swing   {_pct(summary['near_swing_pct'])}"
          f"   Wilson 95% [{summary['near_swing_wilson'][0]:.1f}"
          f"-{summary['near_swing_wilson'][1]:.1f}]" if summary["near_swing_pct"] is not None else "")
    print(f"   ALL buckets near a swing        {_pct(summary['near_swing_base_pct'])}"
          "   <- the control")
    print(f"   lift                            {summary['near_swing_lift_pp']:+.1f}pp")
    print(f"   median distance: spikes {summary['median_swing_distance_atr']} ATR, "
          f"all buckets {summary['base_median_swing_distance_atr']} ATR")
    print("   Read: the headline is the base rate of standing near a swing. Without the")
    print("   control row the claim looks true and means nothing.")
    print()

    print("4. CHANNEL PENETRATION — the only associated feature")
    print(f"   spikes that newly break the {V.CHANNEL_LOOKBACK}-bar channel  "
          f"{_pct(summary['penetration_pct'])}  (up {summary['penetration_up']}, "
          f"down {summary['penetration_down']})")
    print(f"   ALL buckets                     {_pct(summary['penetration_base_pct'])}")
    print(f"   lift                            {summary['penetration_lift_pp']:+.1f}pp")
    if summary["penetration_median_depth_atr"] is not None:
        print(f"   median depth                    {summary['penetration_median_depth_atr']:.2f} ATR")
    vop = rep["volume_on_penetration"]
    if vop.get("n_penetration"):
        print(f"   causality (volume ON the break bar): penetration {_pct(vop['p90_pen_pct'])} "
              f"reach the p90 volume percentile vs {_pct(vop['p90_normal_pct'])} normal "
              f"(lift {vop['p90_lift_pp']:+.1f}pp)")
        print(f"   n = {vop['n_penetration']} penetration bars vs {vop['n_normal']:,} normal")
    print()

    print(f"5. FOLLOW-THROUGH — {V.HOLD_MINUTES} min after the break, does it fade?")
    for label, name in (("penetration_with_spike", "with a volume spike"),
                       ("penetration_all", "all penetrations")):
        cell = rep["follow"].get(label, {})
        if not cell.get("n"):
            print(f"   {name:22s} (no judgeable breaks)")
            continue
        print(f"   {name:22s} n={cell['n']:>4}  closed back inside "
              f"{_pct(cell['back_inside_pct'])}  "
              f"median MFE {cell['median_mfe_atr']:.2f} / MAE {cell['median_mae_atr']:.2f} ATR")
    print()

    print("6. VERDICT")
    for line in rep["verdict"]:
        print("   •", line)
    print()

    if args.spikes:
        print(f"TOP {args.spikes} SPIKES — the step-down detail")
        print(f"   {'when':16} {'ratio':>6} {'vol':>6} {'top minute':>16} {'share':>6} "
              f"{'swing':>7} {'pen':>4}")
        for spike in sorted(rep["spikes"], key=lambda s: -(s["ratio"] or 0))[:args.spikes]:
            step = spike["stepdown"]
            swing = spike["swing"]
            print(f"   {spike['ts'].strftime('%m-%d %H:%M'):16} {spike['ratio']:>5.2f}x "
                  f"{spike['volume']:>6.0f} "
                  f"{(step.get('top_minute').strftime('%H:%M') if step.get('top_minute') else '—'):>16} "
                  f"{(100*step.get('top_minute_share', 0)):>5.0f}% "
                  f"{(('Y' if swing['near'] else 'n') if swing else '—'):>7} "
                  f"{(spike['penetration']['side'] if spike['penetration'] else '—'):>4}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
