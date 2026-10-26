#!/usr/bin/env python3
"""live_readiness — read-only scorecard for the LIVE execution path (2026-10-26).

    python3 tools/live_readiness.py             # human-readable scorecard
    python3 tools/live_readiness.py --json      # machine-readable
    python3 tools/live_readiness.py --strict    # exit 1 while the live gate is CLOSED

This is a CHECKLIST, not proof. It inspects engine.py with the AST (no import, no
network, no /opt/gold) and reads the checked-in quote/spec data. A PASS means the
code construct exists; it does NOT mean the behaviour has been demonstrated on a
demo account. Three checks are deliberately MANUAL: demo-account evidence, a
complete cost model, and independent evidence of positive expectancy. Those are
operator/evidence gates and no source inspection can satisfy them.

The live gate is CLOSED while ANY blocking check is not PASS. It must stay closed
until every check passes AND the owner separately, explicitly approves real
orders. TRADING_MODE stays FORWARD_TEST until then.

See docs/REVIEW-2026-10-26-full-system-audit.md and docs/EXECUTION-PLAN.md.
"""
import argparse
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

PASS, TODO, MANUAL = "PASS", "TODO", "MANUAL"


def _check(cid, area, title, status, evidence, blocking=True):
    return dict(id=cid, area=area, title=title, status=status,
                evidence=evidence, blocking=bool(blocking))


def _function_src(tree, source, name, cls="GoldEngine"):
    """Source text of GoldEngine.<name>, or '' (AST, not import)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                    return ast.get_source_segment(source, fn) or ""
    return ""


def _module_constant(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        return None
    return None


def _uses_attribute(source, attr):
    """True when source code references `*.attr` (comments/docstrings ignored)."""
    try:
        fn_tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(n, ast.Attribute) and n.attr == attr
               for n in ast.walk(fn_tree))


def code_checks(root=ROOT):
    """Static LIVE-path checks against engine.py."""
    path = os.path.join(root, "engine.py")
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError) as exc:
        return [_check("engine_parse", "code", "engine.py parses", TODO,
                       f"cannot read/parse engine.py: {exc}")]

    run_live = _function_src(tree, src, "run_live")
    order = _function_src(tree, src, "execute_live_trade")
    status = _function_src(tree, src, "save_status")
    init = _function_src(tree, src, "__init__")
    mode = _module_constant(tree, "TRADING_MODE")
    out = []

    out.append(_check(
        "mode_paper", "code", "TRADING_MODE stays FORWARD_TEST",
        PASS if mode == "FORWARD_TEST" else TODO,
        f"TRADING_MODE = {mode!r} (only an explicit owner decision may change it)"))

    armed = "live_armed()" in run_live and "live_armed()" in order
    out.append(_check(
        "arm_gate", "code", "explicit arming + kill switch on both order paths",
        PASS if armed else TODO,
        "live_armed() in run_live and execute_live_trade" if armed else
        "live_armed() missing from run_live or execute_live_trade"))

    filling = ("resolve_order_filling(" in order and '"type_filling": filling' in order
               and not _uses_attribute(order, "ORDER_FILLING_FOK"))
    out.append(_check(
        "filling_spec", "code", "order filling read from the symbol spec",
        PASS if filling else TODO,
        "request uses resolve_order_filling(); captured XM spec is IOC-only" if filling else
        "hard-coded/unresolved filling policy found in the order request"))

    closed = "TIMEFRAME_M1, 1, 1" in run_live and "TIMEFRAME_M1, 0, 1" not in run_live
    out.append(_check(
        "closed_bars", "code", "LIVE evaluates CLOSED M1 bars only",
        PASS if closed else TODO,
        "copy_rates_from_pos(..., 1, 1)" if closed else
        "run_live still reads the forming bar (position 0)"))

    dedup = ("self.mt5_next_candle(rates, last_ts)" in run_live
             and "live_last_candle_ts" in status
             and "restore_live_bar_ts_from_status" in init)
    out.append(_check(
        "bar_dedup", "code", "one evaluation per closed bar, restart-safe",
        PASS if dedup else TODO,
        "mt5_next_candle + persisted live_last_candle_ts" if dedup else
        "no persisted closed-bar watermark in the LIVE loop"))

    out.append(_check(
        "spread_filter", "code", "live spread passed into the risk gate",
        PASS if "current_spread_points=live_spread_points" in src else TODO,
        "MIN_SPREAD_POINTS filter is wired into evaluate_candle" if
        "current_spread_points=live_spread_points" in src else "spread never reaches the gate"))

    out.append(_check(
        "broker_be", "code", "broker-side breakeven ratchet (TRADE_ACTION_SLTP)",
        PASS if "TRADE_ACTION_SLTP" in src else TODO,
        "SL modification present" if "TRADE_ACTION_SLTP" in src else
        "BE_TRIGGER_R is engine-side only; run_live never modifies the broker SL. "
        "Either implement SLTP or register the divergence explicitly."))

    time_stop = "ORDER_TIME_SPECIFIED" in src or "live_time_stop" in src
    out.append(_check(
        "broker_time_stop", "code", "broker-side 240-min time stop / close",
        PASS if time_stop else TODO,
        "broker-side time exit present" if time_stop else
        "MAX_HOLD_MINUTES cannot fire in LIVE (no check_position on the live loop)"))

    reconcile_fn = any(
        "positions_get" in _function_src(tree, src, n.name)
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name not in ("evaluate_candle", "run_live")
    )
    reconciled = bool(reconcile_fn) and "history_deals_get" in src
    out.append(_check(
        "position_reconcile", "code", "startup position/deal reconciliation",
        PASS if reconciled else TODO,
        "startup adoption + deal history present" if reconciled else
        "positions_get used only as an in-trade flag; no adoption of an existing "
        "broker position, no duplicate-order check on restart",
    ))

    out.append(_check(
        "deal_reconcile", "code", "realized P&L from broker deals",
        PASS if "history_deals_get" in src else TODO,
        "history_deals_get present" if "history_deals_get" in src else
        "no deal-level P&L; the daily-loss breaker and ledger cannot be trusted in LIVE"))

    out.append(_check(
        "disconnect_safety", "code", "terminal connection checked before orders",
        PASS if "terminal_info" in src else TODO,
        "terminal_info() gating present" if "terminal_info" in src else
        "no connected/disconnect check; a dead terminal can leave stale orders"))

    out.append(_check(
        "sizing_limits", "code", "volume max/step from the live symbol spec",
        PASS if "volume_max" in src else TODO,
        "symbol volume limits consulted" if "volume_max" in src else
        "VOLUME_MIN/STEP are hard-coded; volume_max and stops/freeze levels are not checked"))

    out.append(_check(
        "cost_guard", "code", "cost measured against R before entry",
        PASS if "cost_guard" in src else TODO,
        "risk-relative cost veto present" if "cost_guard" in src else
        "MIN_SPREAD_POINTS=60 ($0.60) allows the measured $0.55 median spread, "
        "which is ~10% of median 1R; no spread-as-%-of-risk veto"))

    return out


def quote_progress(root=ROOT):
    """Structured cost-sample progress — ONE quote read, shared with the dashboard tab.

    Everything here is a measurement of `xm_data/`; nothing is inferred or written.
    `newest_ts` is a UTC epoch float (or None). Kept in this tool so the CLI
    scorecard and the readiness tab can never disagree about the sample target.
    """
    qdir = os.path.join(root, "xm_data")
    import xm_quote_report as QR  # stdlib-only, read-only
    samples, bad, files = QR.load_quotes(qdir)
    cov = QR.coverage(samples)
    good = sorted(s.spread for s in samples if QR.usable(s))
    spec = QR.load_spec(qdir) or {}
    return dict(
        complete_days=len(cov["complete"]) if cov else 0,
        weekends=len(cov["weekends"]) if cov else 0,
        target_days=getattr(QR, "TARGET_DAYS", 14),
        target_weekends=getattr(QR, "TARGET_WEEKENDS", 2),
        rows=len(samples),
        files=files,
        malformed=bad,
        newest_ts=max((s.t for s in samples), default=None),
        median_spread=QR.pct(good, .5) if good else None,
        offsets=sorted({s.off for s in samples if getattr(s, "off", None) is not None}),
        spec=spec,
        filling_mode=(spec.get("symbol_info") or {}).get("filling_mode"),
        filling_flags=(spec.get("decoded") or {}).get("filling_allowed_flags"),
    )


def data_checks(root=ROOT, progress=None):
    """Evidence checks from the checked-in quote/spec data (read-only)."""
    out = []
    try:
        pg = progress if progress is not None else quote_progress(root)
    except Exception as exc:  # a missing/invalid data dir is a TODO, never a crash
        out.append(_check("data_available", "data", "quote/spec data readable", TODO, str(exc)))
        return out

    days, weekends = pg["complete_days"], pg["weekends"]
    target_days, target_weekends = pg["target_days"], pg["target_weekends"]
    out.append(_check(
        "quote_sample", "data", f"cost sample {target_days} days / {target_weekends} weekends",
        PASS if days >= target_days and weekends >= target_weekends else TODO,
        f"{days}/{target_days} complete UTC days, {weekends}/{target_weekends} weekends; "
        f"keep the registered $0.40 round trip until met"))

    med = pg["median_spread"]
    offsets = pg["offsets"]
    out.append(_check(
        "dst_offsets", "data", "post-DST broker offset observed",
        PASS if len(offsets) >= 2 else TODO,
        f"observed server offsets (seconds): {offsets}"))

    raw_filling = pg["filling_mode"]
    out.append(_check(
        "spec_filling", "data", "captured symbol filling policy",
        PASS if raw_filling is not None else TODO,
        f"filling_mode={raw_filling} (1=FOK, 2=IOC, 4=BOC) — "
        f"decoded {pg['filling_flags']}"))

    # The logger already allow-lists what it writes. Only the `account` block can
    # carry an identifier; `terminal.name` is a product name, not an account id.
    forbidden = {"login", "server", "balance", "password", "token", "investor",
                 "email", "broker", "account_name"}
    account = (pg["spec"] or {}).get("account") or {}
    hits = sorted(k for k in account if any(f in k.lower() for f in forbidden))
    out.append(_check(
        "no_account_ids", "data", "no account identifiers in the repo",
        PASS if not hits else TODO,
        f"account block has {len(account)} allow-listed fields, no identifiers" if not hits else
        f"forbidden keys present in account block: {hits}"))

    out.append(_check(
        "cost_model", "evidence", "measured all-in cost (spread + slippage + commission + swap)",
        MANUAL,
        f"median spread-only ${med:.2f}/trade vs the registered $0.40 assumption; "
        "spread alone is a LOWER bound. Needs a dated cost doc before any re-costing."
        if med is not None else "no usable quote rows yet"))

    demo = os.environ.get("GOLD_DEMO_EVIDENCE", os.path.join(root, "docs", "DEMO-EVIDENCE.md"))
    out.append(_check(
        "demo_evidence", "evidence", "demo-account execution evidence",
        PASS if os.path.isfile(demo) else MANUAL,
        f"report present: {demo}" if os.path.isfile(demo) else
        f"HOST/operator task: no {demo}. Must cover fill, SL/TP, BE/time management, "
        "restart, rejection, disconnect and reconciliation on a DEMO account."))

    out.append(_check(
        "edge_evidence", "evidence", "independent forward sample with positive net expectancy",
        MANUAL,
        "paper book is net negative after cost; requires a completed pre-registered "
        "forward window on one unchanged strategy (docs/EXECUTION-PLAN.md Track A)."))

    return out


def all_checks(root=ROOT):
    return code_checks(root) + data_checks(root)


def snapshot(root=ROOT):
    """(checks, progress) with ONE quote read — the dashboard tab's entry point."""
    try:
        pg = quote_progress(root)
    except Exception:
        pg = None
    return code_checks(root) + data_checks(root, progress=pg), pg


def gate_open(checks):
    return all(c["status"] == PASS for c in checks if c["blocking"])


def render(checks):
    lines = ["live_readiness — LIVE execution gate (read-only)",
             "=" * 78]
    for area in ("code", "data", "evidence"):
        group = [c for c in checks if c["area"] == area]
        if not group:
            continue
        lines.append(f"\n[{area.upper()}]")
        for c in group:
            lines.append(f"  {c['status']:<6} {c['id']:<22} {c['title']}")
            lines.append(f"         {c['evidence']}")
    n = {s: sum(1 for c in checks if c["status"] == s) for s in (PASS, TODO, MANUAL)}
    lines.append("")
    lines.append(f"summary: {n[PASS]} PASS · {n[TODO]} TODO · {n[MANUAL]} MANUAL "
                 f"of {len(checks)} checks")
    lines.append("LIVE GATE: " + ("OPEN (subject to explicit owner approval)"
                                  if gate_open(checks) else "CLOSED — no real orders"))
    lines.append("A PASS is a code/evidence check, NOT a demo-test result. "
                 "MANUAL items need operator evidence.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=ROOT, help="repository root (default: this checkout)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--strict", action="store_true", help="exit 1 while the live gate is closed")
    a = ap.parse_args(argv)
    checks = all_checks(a.root)
    if a.json:
        print(json.dumps(dict(checks=checks, gate_open=gate_open(checks)), indent=2))
    else:
        print(render(checks))
    return 0 if (not a.strict or gate_open(checks)) else 1


if __name__ == "__main__":
    sys.exit(main())
