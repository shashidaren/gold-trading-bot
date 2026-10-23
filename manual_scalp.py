#!/usr/bin/env python3
"""Manual scalping calculator and self-reported journal.

This module is deliberately outside the trading path.  It never imports the
engine, reads the bot ledger, or places an order.  Its only write is the JSON
journal passed to :class:`JournalStore` (``manual_scalp_journal.json`` on the
dashboard).  A row marked OPEN/CLOSED is something the operator says happened
elsewhere; it is not broker-verified and is not evidence for the automated
strategy.

Stdlib only.  The arithmetic is kept here, rather than in Javascript, so the
server can recalculate every submitted ticket and every close.  Browser-side
calculations are only a convenience preview.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1
SIDES = ("BUY", "SELL")
DECISIONS = ("taken", "skipped")
TIMEFRAMES = ("M1", "M5", "M15")
EXIT_REASONS = ("MANUAL", "SL", "TP", "SCRATCH", "TIME")
DEFAULT_SPREAD = 0.55
DEFAULT_CONTRACT_SIZE = 100.0
DEFAULT_VOLUME_STEP = 0.01
COST_WARN_PCT = 10.0


class ValidationError(ValueError):
    """A ticket or close contains values that cannot be recorded safely."""


class JournalError(RuntimeError):
    """The manual journal is unavailable or corrupt; never silently reset it."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _number(value, name, *, minimum=None, maximum=None, allow_zero=False):
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{name} is required")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number") from exc
    if not math.isfinite(out):
        raise ValidationError(f"{name} must be finite")
    if minimum is not None and (out < minimum or (not allow_zero and out == minimum)):
        comparator = "at least" if allow_zero else "greater than"
        raise ValidationError(f"{name} must be {comparator} {minimum}")
    if maximum is not None and out > maximum:
        raise ValidationError(f"{name} must be at most {maximum}")
    return out


def _text(value, name, limit, *, required=False):
    text = " ".join(str(value or "").split())
    if required and not text:
        raise ValidationError(f"{name} is required")
    if len(text) > limit:
        raise ValidationError(f"{name} must be {limit} characters or fewer")
    return text


def calculate(payload):
    """Return costed ticket geometry and risk-based size.

    Cost convention matches the existing placement cards: round-trip spread is
    added to the risk leg and subtracted from the reward leg.  Size is rounded
    DOWN to the broker volume step, never up beyond the requested cash risk.

    ``planned_risk_usd`` therefore includes the spread.  ``planned_reward_usd``
    is net of spread and can be negative when the target is inside the cost;
    that is a warning, not a reason to falsify or clamp the arithmetic.
    """
    side = str(payload.get("side") or "").upper().strip()
    if side not in SIDES:
        raise ValidationError("side must be BUY or SELL")
    entry = _number(payload.get("entry"), "entry", minimum=0)
    stop = _number(payload.get("stop"), "stop", minimum=0)
    target = _number(payload.get("target"), "target", minimum=0)
    balance = _number(payload.get("account_balance"), "account balance", minimum=0)
    risk_pct = _number(payload.get("risk_pct"), "risk %", minimum=0, maximum=100)
    spread = _number(payload.get("spread", DEFAULT_SPREAD), "spread", minimum=0, allow_zero=True)
    contract_size = _number(payload.get("contract_size", DEFAULT_CONTRACT_SIZE),
                            "contract size", minimum=0)
    volume_step = _number(payload.get("volume_step", DEFAULT_VOLUME_STEP),
                          "volume step", minimum=0)

    gross_risk = (entry - stop) if side == "BUY" else (stop - entry)
    gross_reward = (target - entry) if side == "BUY" else (entry - target)
    if gross_risk <= 0:
        raise ValidationError(f"for a {side}, the stop must be {'below' if side == 'BUY' else 'above'} entry")
    if gross_reward <= 0:
        raise ValidationError(f"for a {side}, the target must be {'above' if side == 'BUY' else 'below'} entry")

    net_risk = gross_risk + spread
    net_reward = gross_reward - spread
    risk_budget = balance * risk_pct / 100.0
    if not all(math.isfinite(value) for value in
               (gross_risk, gross_reward, net_risk, net_reward, risk_budget)):
        raise ValidationError("ticket numbers are too large")
    risk_per_lot = net_risk * contract_size
    if not math.isfinite(risk_per_lot) or risk_per_lot <= 0:
        raise ValidationError("ticket numbers are too large")
    raw_lots = risk_budget / risk_per_lot
    if not math.isfinite(raw_lots):
        raise ValidationError("ticket numbers are too large")
    scaled_lots = raw_lots / volume_step
    if not math.isfinite(scaled_lots):
        raise ValidationError("ticket numbers are too large")
    lots = round(math.floor(scaled_lots + 1e-12) * volume_step, 8)
    planned_risk = lots * net_risk * contract_size
    planned_reward = lots * net_reward * contract_size
    if not all(math.isfinite(value) for value in (lots, planned_risk, planned_reward)):
        raise ValidationError("ticket numbers are too large")
    net_rr = net_reward / net_risk
    gross_rr = gross_reward / gross_risk
    cost_pct = 100.0 * spread / gross_risk
    if not all(math.isfinite(value) for value in (net_rr, gross_rr, cost_pct)):
        raise ValidationError("ticket numbers are too large")

    warnings = []
    if lots <= 0:
        warnings.append("Size is below one volume step; do not round up beyond your cash-risk budget.")
    if cost_pct > COST_WARN_PCT:
        warnings.append(f"Spread is {cost_pct:.1f}% of gross stop distance (above the {COST_WARN_PCT:.0f}% guide).")
    if net_reward <= 0:
        warnings.append("The round-trip spread is greater than or equal to the gross reward.")
    elif net_rr < 1.0:
        warnings.append(f"Costed reward/risk is only {net_rr:.2f}:1; potential loss exceeds potential gain.")

    return {
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "account_balance": balance,
        "risk_pct": risk_pct,
        "spread": spread,
        "contract_size": contract_size,
        "volume_step": volume_step,
        "gross_risk_per_oz": gross_risk,
        "gross_reward_per_oz": gross_reward,
        "net_risk_per_oz": net_risk,
        "net_reward_per_oz": net_reward,
        "gross_rr": gross_rr,
        "net_rr": net_rr,
        "cost_pct": cost_pct,
        "risk_budget_usd": risk_budget,
        "raw_lots": raw_lots,
        "lots": lots,
        "planned_risk_usd": planned_risk,
        "planned_reward_usd": planned_reward,
        "breakeven_win_pct": (100.0 * net_risk / (net_risk + net_reward)) if net_reward > 0 else None,
        "warnings": warnings,
    }


def close_result(record, exit_price):
    """Calculate a self-reported close against the original sized risk."""
    exit_price = _number(exit_price, "exit price", minimum=0)
    side = record.get("side")
    if side not in SIDES:
        raise JournalError("journal row has an invalid side")
    direction = 1.0 if side == "BUY" else -1.0
    lots = _number(record.get("lots"), "journal lots", minimum=0)
    contract_size = _number(record.get("contract_size"), "journal contract size", minimum=0)
    spread = _number(record.get("spread"), "journal spread", minimum=0, allow_zero=True)
    planned_risk = _number(record.get("planned_risk_usd"), "journal planned risk", minimum=0)
    entry = _number(record.get("entry"), "journal entry", minimum=0)
    quantity = lots * contract_size
    gross_pnl = direction * (exit_price - entry) * quantity
    net_pnl = gross_pnl - spread * quantity
    result_r = net_pnl / planned_risk
    if not all(math.isfinite(value) for value in (gross_pnl, net_pnl, result_r)):
        raise ValidationError("close numbers are too large")
    return {
        "exit_price": exit_price,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "result_r": result_r,
    }


class JournalStore:
    """Small atomic JSON store for manual, self-reported decisions.

    The dashboard runs one process, so a thread lock is sufficient for its
    request handlers.  Every update writes a same-directory temporary file and
    atomically replaces the original.  A corrupt file raises instead of being
    replaced by an empty journal.
    """

    _lock = threading.RLock()

    def __init__(self, path):
        self.path = os.path.abspath(path)

    def _read_unlocked(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            raise JournalError(f"cannot read manual journal: {exc}") from exc
        if (not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION
                or not isinstance(payload.get("entries"), list)
                or any(not isinstance(row, dict) for row in payload["entries"])):
            raise JournalError("manual journal has an unsupported or corrupt schema")
        return payload["entries"]

    def _write_unlocked(self, entries):
        parent = os.path.dirname(self.path)
        try:
            os.makedirs(parent, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".manual-scalp-", suffix=".tmp", dir=parent)
            try:
                os.chmod(tmp, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"version": SCHEMA_VERSION, "entries": entries}, handle,
                              indent=2, sort_keys=True, allow_nan=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise JournalError(f"cannot write manual journal: {exc}") from exc

    def create(self, payload):
        """Validate, recalculate and append a TAKEN(open) or SKIPPED decision."""
        decision = str(payload.get("decision") or "").lower().strip()
        if decision not in DECISIONS:
            raise ValidationError("decision must be taken or skipped")
        calc = calculate(payload)
        if decision == "taken" and calc["lots"] <= 0:
            raise ValidationError("calculated size is below one volume step; skipped ideas can still be logged")
        timeframe = str(payload.get("timeframe") or "M5").upper().strip()
        if timeframe not in TIMEFRAMES:
            raise ValidationError("timeframe must be M1, M5 or M15")
        setup = _text(payload.get("setup"), "setup / reason", 160, required=True)
        notes = _text(payload.get("notes"), "notes", 2000)
        with self._lock:
            entries = self._read_unlocked()
            record = dict(calc)
            record.pop("warnings", None)
            record.pop("raw_lots", None)
            record.update({
                "id": uuid.uuid4().hex[:12],
                "created_utc": _utc_now(),
                "status": "OPEN" if decision == "taken" else "SKIPPED",
                "source": "manual-self-reported",
                "timeframe": timeframe,
                "setup": setup,
                "notes": notes,
                "warnings": list(calc["warnings"]),
                "closed_utc": None,
                "exit_price": None,
                "exit_reason": None,
                "close_notes": None,
                "gross_pnl": None,
                "net_pnl": None,
                "result_r": None,
            })
            entries.append(record)
            self._write_unlocked(entries)
            return dict(record)

    def close(self, record_id, payload):
        record_id = str(record_id or "").strip()
        if not record_id or len(record_id) > 32:
            raise ValidationError("invalid journal id")
        reason = str(payload.get("exit_reason") or "MANUAL").upper().strip()
        if reason not in EXIT_REASONS:
            raise ValidationError("invalid exit reason")
        notes = _text(payload.get("close_notes"), "close notes", 2000)
        with self._lock:
            entries = self._read_unlocked()
            matches = [row for row in entries if row.get("id") == record_id]
            if not matches:
                raise ValidationError("manual journal row not found")
            record = matches[0]
            if record.get("status") != "OPEN":
                raise ValidationError("only an open manual row can be closed")
            result = close_result(record, payload.get("exit_price"))
            record.update(result)
            record.update({"status": "CLOSED", "closed_utc": _utc_now(),
                           "exit_reason": reason, "close_notes": notes})
            self._write_unlocked(entries)
            return dict(record)

    def read(self, limit=100):
        """Return newest-first rows plus descriptive (not predictive) totals."""
        with self._lock:
            entries = self._read_unlocked()
        rows = list(reversed(entries))
        closed = [row for row in entries if row.get("status") == "CLOSED"]
        net_values = [float(row["net_pnl"]) for row in closed
                      if isinstance(row.get("net_pnl"), (int, float))
                      and math.isfinite(row["net_pnl"])]
        r_values = [float(row["result_r"]) for row in closed
                    if isinstance(row.get("result_r"), (int, float))
                    and math.isfinite(row["result_r"])]
        summary = {
            "total": len(entries),
            "open": sum(row.get("status") == "OPEN" for row in entries),
            "skipped": sum(row.get("status") == "SKIPPED" for row in entries),
            "closed": len(closed),
            "net_pnl": sum(net_values),
            "average_r": (sum(r_values) / len(r_values)) if r_values else None,
            "wins": sum(value > 0 for value in net_values),
            "losses": sum(value < 0 for value in net_values),
            "flat": sum(value == 0 for value in net_values),
            "review_remaining": max(0, 100 - len(closed)),
        }
        return {"rows": rows[:max(1, int(limit))], "summary": summary}
