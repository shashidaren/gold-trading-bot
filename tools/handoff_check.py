#!/usr/bin/env python3
"""
Freshness gate for docs/HANDOFF.md - "is the handoff still telling the truth?"
(port of bitcoin-trading-bot's tools/handoff_check.py, re-calibrated for gold)

Why this exists
---------------
HANDOFF.md is the file a new session boots from, and the live box pushes new data every 3 h
(tools/autosync.sh). A handoff that quietly drifts is worse than no handoff: the next agent
retunes on numbers that are days and dozens of trades old. Gold's own §1 was 8 days and 82
closed trades behind when this tool was written (it still said "493 closed, as of 10-05"
on 10-13 with 575 on the box), and the "daily job refreshes §1" in §10 had not produced a
refresh since 09-25. This project has also been bitten by numbers quoted as current from a
snapshot that was already stale.

So the snapshot block near the top of HANDOFF.md is machine-checked:

    <!-- HANDOFF-SNAPSHOT ... -->
    | key | value |
    ...
    <!-- /HANDOFF-SNAPSHOT -->

Every key in that block is recomputed from the live data files and compared. Prose is never
parsed and never touched - only the block is checked, and only the block is rewritten by
--update. The prose numbers still have to be written by whoever read the tools (§11's ritual);
this tool tells you WHEN that is overdue and removes the excuse that the block is a chore.

Verdicts
--------
  OK      doc value == live value
  DRIFT   doc value != live value, but inside tolerance (advisory only)
  STALE   outside tolerance: too many trades behind, snapshot too old, a referenced file
          missing, the cutover/cost config disagrees with the tools, the doc's own `--cost`
          commands disagree with the snapshot's cost assumption, or the doc is structurally
          broken (a required §N missing, a placeholder marker, a dangling §N reference)

Tolerance policy: 30 closed trades and 48 hours. Gold closes ~10-18 trades a weekday, so 30 is
about two trading days of normal drift; BTC's 5 trades would be ~7 hours here and would make
the digest line permanently STALE ("cry wolf" - and a muted digest protects nobody). Each key
is judged by what moves it, not by exact match:

  trade counts      closed_trades, structstop_era_trades: within TRADE_TOLERANCE.
  trade outcomes    outcomes / decisive_wr_pct / structstop_era_outcomes may differ only
                    because trades were ADDED (a changed outcome with an unchanged
                    trade count means the ledger was edited -> STALE); open_trade may differ
                    whenever a trade opened or closed.
  money             engine_ledger_usd / true_equity_usd / net_pnl_usd_at_cost may differ only
                    as far as the closed-trade gap can explain (MONEY_PER_TRADE $ per trade,
                    ~2x the largest single |P&L| ever booked / 3x the p95); with an unchanged
                    trade count they must not move at all.
  the price log     log_bars / log_last_bar_utc: within MAX_AGE_HOURS of M1 bars
                    (BAR_TOLERANCE rows). A snapshot NEWER than the data is STALE (lost data
                    or a stale checkout - never force-push data commits).
  config            cost_usd_per_side must match what the doc says (and the doc's --cost
                    commands); cutover_utc must equal strategy_lab.LIVE_CUTOVER exactly, so the
                    doc and the replay tools can never again disagree about the era boundary.
  as_of_utc, data_collection: advisory only (they move every 3 hours).

Structure is checked too (added 2026-10-15 after the daily doc job truncated the file to its
front matter and this gate still said FRESH): §1-§11 must all be present with their headings intact,
no placeholder markers, no dangling §N references. `--update` refuses to rewrite the snapshot block
of a structurally broken doc, so a truncation cannot be quietly stamped as verified.

Exit code: 0 = fresh (OK/DRIFT), 1 = STALE, 2 = snapshot block missing or unparseable.
tools/autosync.sh treats the exit code as ADVISORY: it prints the verdict in the Telegram
digest and never blocks a deploy on it (a doc that is a dozen trades behind is not an incident).

Usage:
  python3 tools/handoff_check.py [repo_root]      # check
  python3 tools/handoff_check.py --update         # rewrite the snapshot block from live data
  python3 tools/handoff_check.py --quiet          # one-line verdict (digests)

Read-only unless --update is passed. Pure stdlib; reuses tools/strategy_lab.py's loaders and
era constants so the numbers are produced by the same code as the rest of the suite.
"""
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BEGIN_MARK = "<!-- HANDOFF-SNAPSHOT"
END_MARK = "<!-- /HANDOFF-SNAPSHOT -->"

START_BALANCE = 500.0          # paper account start (check_data.py: "true P&L from $500")
DEFAULT_COST_PER_SIDE = 0.20   # strategy_lab's default cost model ($/side, BE included)

# Advisory-only keys: they move on their own (the box commits data every 3 h) and are recorded
# for provenance, not compared as pass/fail.
ADVISORY = {"as_of_utc", "data_collection"}

TRADE_TOLERANCE = 30       # closed trades of drift before the doc is STALE (~2 trading days)
MAX_AGE_HOURS = 48         # snapshot older than this is STALE even if counts match
BAR_TOLERANCE = MAX_AGE_HOURS * 60   # M1 log rows; derived from MAX_AGE_HOURS so they cannot disagree
SKIP_TOLERANCE = 200       # skipped-signal rows (6-83 a day, ~170 in 48 h at the busy end)
MONEY_PER_TRADE = 6.0      # $: what one closed trade can plausibly move a money key (mean |P&L| $2.96,
                           # p95 $7.9, max $15.4 over 575 trades; 30 trades -> $180)

TRADE_COUNT_KEYS = {"closed_trades", "structstop_era_trades"}
OUTCOME_KEYS = {"outcomes", "decisive_wr_pct", "structstop_era_outcomes"}   # change only if trades were added
OPEN_TRADE_KEYS = {"open_trade"}                                          # changes on every open/close
MONEY_KEYS = {"engine_ledger_usd", "true_equity_usd", "net_pnl_usd_at_cost"}

# --------------------------------------------------------------------------- #
# structure (2026-10-15)
# --------------------------------------------------------------------------- #
# Why this exists: on 2026-10-15 the daily doc job rewrote docs/HANDOFF.md twice - the first commit
# replaced all 886 lines with the single line "PLACEHOLDER - will replace", the second put back the
# front matter and §1 only. §2-§11 (the gates, the evidence base, next steps, the verification
# ritual, the data gotchas, the deploy runbook and the §11 protocol itself) were gone, and this tool
# said FRESH, because the snapshot block it reads was complete and current. A handoff can be
# perfectly fresh and still be a corpse.
#
# The file is an operating manual, not a status page, so its SHAPE is part of the verdict:
# every required section is present *and still says what it is*, no placeholder markers, and every
# `§N` reference resolves. Each rule is a direct response to the observed failure; the byte size is
# deliberately NOT checked (a floor would be arbitrary and would fire on honest edits).
REQUIRED_SECTIONS = (
    ("1", "Where things stand"),
    ("2", "Bot in one paragraph"),
    ("3", "Data feed"),
    ("4", "Current risk gates"),
    ("5", "Evidence base"),
    ("6", "Next steps"),
    ("7", "How to verify code changes"),
    ("8", "Data gotchas"),
    ("9", "Architecture quick map"),
    ("10", "Deploy & ops"),
    ("11", "How to keep this file honest"),
)
# Section titles must still contain these phrases - a renumbered or rewritten heading is how the
# 10-15 restore smuggled §2-§11 out of the file while keeping a §1 that looked fine. If a rename is
# intentional, update this table in the same commit.
SECTION_KEYWORDS = {
    "1": "where things stand",
    "2": "bot in one paragraph",
    "3": "data feed",
    "4": "risk gates",
    "5": "evidence base",
    "6": "next steps",
    "7": "verify code changes",
    "8": "data gotchas",
    "9": "architecture",
    "10": "deploy",
    "11": "keep this file honest",
}
# Bare-text markers of a machine-truncated or half-written file. Two rules keep this precise:
#   * scanned OUTSIDE code spans, so the docs may still quote them while telling this story (as §1
#     of HANDOFF.md does);
#   * scanned CASE-SENSITIVELY - the all-caps spellings are the truncation's signature, while
#     ordinary prose legitimately says "placeholder markers are flagged" in lower case (which is
#     exactly the false positive this rule produced on its first run).
PLACEHOLDER_MARKS = (
    "PLACEHOLDER",
    "[... rest of the",
    "[...rest of the",
    "rest of the original content",
    "omitted for brevity",
    "content omitted",
    "TO BE WRITTEN",
    "<full content",
    "TODO:",
    "FIXME",
    "XXX:",
)
MAX_SECTION_REF = 11       # §1-§11 are this file's own sections; higher numbers belong to other docs

# Order the block is written in. --update regenerates exactly these keys.
KEY_ORDER = [
    "as_of_utc",
    "data_collection",
    "closed_trades",
    "outcomes",
    "decisive_wr_pct",
    "engine_ledger_usd",
    "true_equity_usd",
    "cost_usd_per_side",
    "net_pnl_usd_at_cost",
    "cutover_utc",
    "structstop_era_trades",
    "structstop_era_outcomes",
    "log_bars",
    "log_last_bar_utc",
    "skip_rows",
    "open_trade",
]


# --------------------------------------------------------------------------- #
# live facts
# --------------------------------------------------------------------------- #
def _outcomes(trades):
    w = sum(1 for t in trades if t["reason"] == "TP")
    l = sum(1 for t in trades if t["reason"] == "SL")
    be = sum(1 for t in trades if t["reason"] == "BE")
    ti = sum(1 for t in trades if t["reason"] == "TIME")
    return w, l, be, ti, f"{w}W/{l}L/{be}BE/{ti}TIME"


def _scan_log(path):
    """(rows with a parseable timestamp, newest timestamp) without loading the bars."""
    n, last = 0, None
    if not os.path.exists(path):
        return 0, None
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if not row or not row[0] or row[0] == "Timestamp":
                continue
            try:
                last = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            n += 1
    return n, last


def live_facts(root, cost=None):
    """Recompute every snapshot key from the data files themselves."""
    import strategy_lab as SL  # noqa: E402  (sys.path set above)

    f = {}
    status = {}
    sp = os.path.join(root, "status.json")
    if os.path.exists(sp):
        with open(sp) as fh:
            status = json.load(fh)

    trades = SL.load_ledger(os.path.join(root, "trades.csv"))
    n_bars, last_bar = _scan_log(os.path.join(root, "forward_test_log.csv"))

    skips = 0
    skp = os.path.join(root, "skipped_trades.csv")
    if os.path.exists(skp):
        with open(skp, newline="") as fh:
            skips = max(0, sum(1 for _ in fh) - 1)

    if cost is None:
        cost = DEFAULT_COST_PER_SIDE
    w, l, _be, _ti, outcomes = _outcomes(trades)
    gross = sum(t["pnl"] for t in trades)
    era = [t for t in trades if t["et"] >= SL.LIVE_CUTOVER]

    f["closed_trades"] = str(len(trades))
    f["outcomes"] = outcomes
    f["decisive_wr_pct"] = f"{100.0 * w / (w + l):.1f}" if (w + l) else "0.0"
    f["engine_ledger_usd"] = f"{status.get('equity', 0):.2f}"
    f["true_equity_usd"] = f"{START_BALANCE + gross:.2f}"
    f["cost_usd_per_side"] = f"{cost:.2f}"
    f["net_pnl_usd_at_cost"] = f"{gross - 2.0 * cost * len(trades):+.2f}"
    f["cutover_utc"] = SL.LIVE_CUTOVER.strftime("%Y-%m-%d %H:%M")
    f["structstop_era_trades"] = str(len(era))
    f["structstop_era_outcomes"] = _outcomes(era)[4]
    f["log_bars"] = str(n_bars)
    f["log_last_bar_utc"] = last_bar.strftime("%Y-%m-%d %H:%M") if last_bar else "?"
    f["skip_rows"] = str(skips)

    if status.get("trade_active"):
        f["open_trade"] = "{} #{} @ {}".format(
            status.get("trade_type") or "?",
            status.get("current_trade_num") or "?",
            status.get("entry_price") or "?")
    else:
        f["open_trade"] = "none"

    # as-of = the engine's own last write; fall back to the newest log bar
    as_of = status.get("last_update") or ""
    as_of_dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            as_of_dt = datetime.strptime(as_of[:19], fmt)
            break
        except ValueError:
            continue
    if as_of_dt is None:
        as_of_dt = last_bar
    f["as_of_utc"] = as_of_dt.strftime("%Y-%m-%d %H:%M") if as_of_dt else "?"
    f["_as_of_dt"] = as_of_dt

    f["data_collection"] = _data_collection_number(root)
    return f


def _data_collection_number(root):
    """N from the newest 'data collection N' commit (autosync's own marker)."""
    try:
        out = subprocess.run(
            ["git", "log", "--format=%s", "-n", "50"],
            cwd=root, capture_output=True, text=True, timeout=20)
        nums = [int(m.group(1)) for m in
                (re.match(r"^data collection (\d+)$", line.strip())
                 for line in out.stdout.splitlines()) if m]
        return str(max(nums)) if nums else "unknown"
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------- #
# the snapshot block
# --------------------------------------------------------------------------- #
def read_block(path):
    """Return (lines, start_idx, end_idx, {key: value}) for the marked block."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    start = end = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith(BEGIN_MARK):
            start = i
        elif ln.strip() == END_MARK and start is not None:
            end = i
            break
    if start is None or end is None:
        return lines, None, None, {}
    doc = {}
    for ln in lines[start + 1:end]:
        m = re.match(r"^\|\s*([a-z_0-9]+)\s*\|\s*(.*?)\s*\|\s*$", ln.strip())
        if m:
            doc[m.group(1)] = m.group(2)
    return lines, start, end, doc


def render_block(facts, comment=None):
    head = BEGIN_MARK + (comment or
                         " machine-checked by tools/handoff_check.py;"
                         " refresh with --update -->")
    out = [head, "| key | value |", "|---|---|"]
    for k in KEY_ORDER:
        if k in facts:
            out.append(f"| {k} | {facts[k]} |")
    out.append(END_MARK)
    return out


# --------------------------------------------------------------------------- #
# comparisons
# --------------------------------------------------------------------------- #
def _num(s):
    try:
        return float(str(s).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _minute(s):
    """'2026-10-01 02:05' -> datetime, or None when it does not parse."""
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _closed_gap(doc, facts):
    """Signed closed-trade gap (live - doc), or None when it cannot be read."""
    dn, ln = _num(doc.get("closed_trades")), _num(facts.get("closed_trades"))
    return None if dn is None or ln is None else ln - dn


def compare(doc, facts):
    """[(key, doc_value, live_value, verdict, note)]

    A doc is STALE only when it is genuinely behind (more than TRADE_TOLERANCE closed trades
    or MAX_AGE_HOURS of log) or contradicts the data. Every other difference is normal drift
    and passes - see the header for the per-key rules.
    """
    rows = []
    cgap = _closed_gap(doc, facts)
    for k in KEY_ORDER:
        if k not in facts:
            continue
        d = doc.get(k)
        live = facts[k]
        if d is None:
            rows.append((k, "(missing)", live, "STALE", "key absent from the doc"))
            continue
        if d == live:
            rows.append((k, d, live, "OK", ""))
            continue
        if k in ADVISORY:
            rows.append((k, d, live, "DRIFT", "advisory"))
            continue

        if k == "log_last_bar_utc":
            dd, ld = _minute(d), _minute(live)
            if dd is not None and ld is not None:
                mins = (ld - dd).total_seconds() / 60.0
                if mins < 0:
                    rows.append((k, d, live, "STALE",
                                 "snapshot is newer than the data (lost data, or a stale checkout?)"))
                else:
                    ok = mins <= MAX_AGE_HOURS * 60
                    rows.append((k, d, live, "OK" if ok else "STALE",
                                 f"{mins / 60:+.1f} h of log since the snapshot"))
                continue

        if (k in OUTCOME_KEYS or k in OPEN_TRADE_KEYS) and cgap is not None:
            note = f"{cgap:+.0f} closed trades since the snapshot"
            if abs(cgap) > TRADE_TOLERANCE:
                rows.append((k, d, live, "STALE", note))
            elif k in OUTCOME_KEYS and cgap == 0:
                rows.append((k, d, live, "STALE",
                             "outcomes changed but the closed-trade count did not (ledger edited?)"))
            else:
                rows.append((k, d, live, "OK", note))
            continue

        dn, ln = _num(d), _num(live)
        if dn is not None and ln is not None:
            gap = abs(ln - dn)
            note = ""
            if (k in TRADE_COUNT_KEYS or k in ("log_bars", "skip_rows")) and ln < dn:
                # these only ever grow: a doc AHEAD of the box means rows were lost, or the
                # checkout is older than the doc (never force-push the data commits)
                rows.append((k, d, live, "STALE",
                             f"snapshot is AHEAD of the data by {dn - ln:.0f} (lost rows, or a stale checkout?)"))
                continue
            if k in TRADE_COUNT_KEYS:
                ok = gap <= TRADE_TOLERANCE
                note = f"{ln - dn:+.0f} trades since the snapshot"
            elif k == "log_bars":
                ok = gap <= BAR_TOLERANCE
                note = f"{ln - dn:+.0f} since the snapshot"
            elif k == "skip_rows":
                ok = gap <= SKIP_TOLERANCE
                note = f"{ln - dn:+.0f} since the snapshot"
            elif k in MONEY_KEYS:
                # money follows the trade count: judge it by what that many trades could move.
                # With an unchanged count the allowance is $0 - nothing may move (a ledger edit).
                allowed = MONEY_PER_TRADE * abs(cgap) if cgap is not None else MONEY_PER_TRADE * TRADE_TOLERANCE
                ok = gap <= allowed + 1e-9
                note = f"${ln - dn:+.2f} since the snapshot (allowed ${allowed:.2f} for {cgap:+.0f} trades)" \
                    if cgap is not None else f"${ln - dn:+.2f} since the snapshot"
            else:
                ok = False          # config (cost_usd_per_side, cutover_utc): exact
                note = "config must match exactly"
            rows.append((k, d, live, "OK" if ok else "STALE", note))
        else:
            rows.append((k, d, live, "STALE",
                         "config must match exactly" if k in {"cutover_utc", "cost_usd_per_side"}
                         else "value changed"))
    return rows


def doc_structure(text):
    """Is the handoff still WHOLE? (2026-10-15)

    Three rules, all from the 10-15 truncation (see the constants above). Returns a list of
    human-readable problems; an empty list means the file still has its shape.
    """
    problems = []

    # 1. every required section exists, and its heading still says what it is
    found = {}
    for num, title in REQUIRED_SECTIONS:
        m = re.search(rf"^##\s+{re.escape(num)}\.\s+(.+?)\s*$", text, flags=re.M)
        if not m:
            problems.append(f"missing §{num} ({title}) - the handoff is truncated, "
                            f"rewritten, or the section was renamed")
            continue
        found[num] = m.group(1)
        keyword = SECTION_KEYWORDS.get(num)
        if keyword and keyword not in found[num].lower():
            problems.append(f"§{num} now reads \"{found[num][:60]}\" and no longer mentions "
                            f"'{keyword}' - if that rename is intentional, update "
                            f"SECTION_KEYWORDS in tools/handoff_check.py")

    # 2. no bare placeholder markers (code spans are excluded: the docs quote these on purpose)
    scrubbed = re.sub(r"```.*?```", " ", text, flags=re.S)
    scrubbed = re.sub(r"`[^`\n]*`", " ", scrubbed)
    for mark in PLACEHOLDER_MARKS:
        if mark in scrubbed:
            problems.append(f"contains the placeholder marker \"{mark}\" - the file was "
                            f"truncated or never finished")

    # 3. every §N reference resolves to a section that exists
    dangling = sorted({int(n) for n in re.findall(r"§(\d{1,2})\b", text)
                       if int(n) <= MAX_SECTION_REF and str(int(n)) not in found})
    if dangling:
        problems.append("§" + ", §".join(str(n) for n in dangling) +
                        " referenced but not present - dangling cross-references mean content "
                        "was lost (a reader finds out the hard way)")
    return problems


def doc_consistency(root, doc, text):
    """Cross-checks that are about the doc agreeing with ITSELF.

    These catch the failure mode the BTC project hit on 2026-09-16: §1/§9 quoted the measured
    spread ($0.40) while §6's copy-paste command block still said --spread 0.25, so the next
    session reproduced numbers that did not match the doc it was following. Here the same trap
    exists for `strategy_lab.py --cost`.
    """
    problems = []

    # Only fenced code blocks count as "commands the next session will run". Prose
    # legitimately talks about other values ("at $0.30 round trip"), and scanning it produced
    # false positives.
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", text, flags=re.S)
    cost = _num(doc.get("cost_usd_per_side"))
    if cost is not None and blocks:
        used = sorted({float(m) for b in blocks
                       for m in re.findall(r"--cost\s+([0-9.]+)", b)})
        bad = [u for u in used if abs(u - cost) > 1e-9]
        if bad:
            problems.append(
                "command blocks pass --cost " +
                ", ".join(f"{b:g}" for b in bad) +
                f" but the snapshot's cost assumption is ${cost:.2f}/side")

    # Referenced files must exist - except placeholders like `docs/REVIEW-YYYY-MM-DD.md`,
    # which name a pattern, not a file.
    for m in re.finditer(r"`((?:docs|archive|tools)/[A-Za-z0-9._\-]+)`", text):
        ref = m.group(1)
        if re.search(r"YYYY|MM-DD|[*<>?]", ref):
            continue
        if not os.path.exists(os.path.join(root, ref)):
            problems.append(f"references `{ref}` which does not exist")
    return sorted(set(problems))


# --------------------------------------------------------------------------- #
def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    update = "--update" in args
    quiet = "--quiet" in args
    positional = [a for a in args if not a.startswith("--")]
    root = positional[0] if positional else os.path.dirname(HERE)

    path = os.path.join(root, "docs", "HANDOFF.md")
    if not os.path.exists(path):
        print(f"not run (no {path})" if quiet else f"handoff_check: {path} not found")
        return 2

    lines, start, end, doc = read_block(path)
    if start is None:
        if quiet:
            print("not run (no HANDOFF-SNAPSHOT block in docs/HANDOFF.md)")
        else:
            print(f"handoff_check: no {BEGIN_MARK} ... {END_MARK} block in {path}")
            print("               add one (see the file header) so the doc can be checked")
        return 2

    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    cost = _num(doc.get("cost_usd_per_side")) or DEFAULT_COST_PER_SIDE
    try:
        facts = live_facts(root, cost=cost)
    except Exception as e:  # never let a health check break the sync (one line for the digest)
        print(f"handoff_check failed to read the data: {type(e).__name__}: {e}")
        return 3

    # age of the snapshot, judged against the newest data the box has written.
    # Reported, never stored in the doc: a value that is out of date the moment it is
    # written would just be noise in the block.
    age_h = None
    age_txt = "?"
    if facts.get("_as_of_dt") and doc.get("as_of_utc"):
        try:
            snap = datetime.strptime(doc["as_of_utc"], "%Y-%m-%d %H:%M")
            age_h = (facts["_as_of_dt"] - snap).total_seconds() / 3600.0
            age_txt = f"{age_h:+.1f}"
        except ValueError:
            pass

    if update:
        # A refreshed snapshot on a truncated file just makes the corpse look verified (10-15).
        broken = doc_structure(text)
        if broken:
            print("handoff_check: refusing to --update a structurally broken docs/HANDOFF.md:")
            for prob in broken:
                print(f"  [STALE] {prob}")
            print("  restore the missing content first, e.g. "
                  "git show <last-good-commit>:docs/HANDOFF.md")
            return 1

        keep = {k: doc[k] for k in doc if k not in facts}
        new = dict(facts)
        new.update({k: v for k, v in keep.items()})
        block = render_block(new)
        out = lines[:start] + block + lines[end + 1:]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out))
        changed = [k for k in KEY_ORDER
                   if k in facts and doc.get(k) not in (None, facts[k])]
        print("handoff_check: snapshot block updated in docs/HANDOFF.md")
        for k in changed:
            print(f"  {k:24s} {doc.get(k)} -> {facts[k]}")
        if not changed:
            print("  (no values changed)")
        print("  prose numbers are NOT touched - re-read §11's ritual and update"
              " §1/§4/§5/§6 yourself")
        return 0

    rows = compare(doc, facts)
    problems = doc_consistency(root, doc, text) + doc_structure(text)

    stale = [r for r in rows if r[3] == "STALE"] + [("doc", "", "", "STALE", p) for p in problems]
    drift = [r for r in rows if r[3] == "DRIFT"]
    if age_h is not None and age_h > MAX_AGE_HOURS:
        stale.append(("as_of_utc", doc.get("as_of_utc"), facts["as_of_utc"],
                      "STALE", f"snapshot is {age_h:.0f} h older than the newest data"))

    if quiet:
        if stale:
            first = stale[0]
            print(f"STALE ({len(stale)} problem(s)): {first[0]} {first[4]}".rstrip())
        elif drift:
            print(f"fresh, {len(drift)} advisory drift (data moved since the snapshot)")
        else:
            print("fresh (snapshot matches the live data)")
        return 1 if stale else 0

    print(f"handoff_check - docs/HANDOFF.md vs live data in {root}")
    print(f"  snapshot as_of {doc.get('as_of_utc', '?')} | newest data "
          f"{facts['as_of_utc']} | age {age_txt} h")
    print()
    print(f"  {'key':24s} {'doc':>24s} {'live':>24s}  verdict")
    for k, d, live, verdict, note in rows:
        mark = {"OK": "  ok ", "DRIFT": " drift", "STALE": "STALE"}[verdict]
        print(f"  {k:24s} {str(d):>24s} {str(live):>24s}  [{mark}]"
              + (f"  {note}" if note else ""))
    if problems:
        print("\n== doc self-consistency ==")
        for p in problems:
            print(f"  [STALE] {p}")
    print()
    if stale:
        print(f"== result: HANDOFF STALE ({len(stale)} problem(s), "
              f"{len(drift)} advisory) ==")
        print("Fix: python3 tools/handoff_check.py --update   (snapshot block)")
        print("     then re-read §11's ritual and update the prose in §1/§4/§5/§6.")
        return 1
    print(f"== result: HANDOFF FRESH ({len(drift)} advisory drift) ==")
    if drift:
        print("Advisory drift is normal - the box trades while the doc sleeps.")
        print("Refresh the block with: python3 tools/handoff_check.py --update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
