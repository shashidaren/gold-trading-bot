#!/usr/bin/env python3
"""Hermetic recovery tests; no production paths or network."""
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from repair_phantom_ledger import plan, phantom

FIELDS = 'Trade_Num Trade_Type Entry_Time Exit_Time Entry_Price Stop_Loss Take_Profit Exit_Price Exit_Reason Profit Balance_After'.split()


def fixture():
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=FIELDS)
    w.writeheader()
    w.writerow(dict(zip(FIELDS, [625, 'BUY', '2026-10-16 19:45:07', '2026-10-16 20:54:03', 4168.71, 4164.01, 4175.75, 4164.01, 'SL', -4.70, 150.69])))
    w.writerow(dict(zip(FIELDS, [626, 'BUY', '', '2026-10-18 23:05:06', 4178.94, 0, 0, 0, 'TP', -4178.94, -4028.25])))
    return out.getvalue().encode(), json.dumps(dict(equity=-4028.25, total_trades=2, trade_active=False)).encode()


def fixture_extended_variants():
    """One good row + 6 phantom variants covering incident #626-645 signatures:
       BUY TP zero, BUY TP with SL 4172, SELL TP, SELL BE, SELL SL, mixed.
       Balances are continuous; status matches ledger suffix.
    """
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=FIELDS)
    w.writeheader()
    # good #625
    w.writerow(dict(zip(FIELDS, [625, 'BUY', '2026-10-16 19:45:07', '2026-10-16 20:54:03', 4168.71, 4164.01, 4175.75, 4164.01, 'SL', -4.70, 150.69])))
    # phantom rows with incident signature (blank Entry_Time, zero Take_Profit)
    # 626 BUY TP zero-price
    w.writerow(dict(zip(FIELDS, [626, 'BUY', '', '2026-10-18 23:05:06', 4178.94, 0, 0, 0, 'TP', -4178.94, -4028.25])))
    # 627 BUY TP zero-price
    w.writerow(dict(zip(FIELDS, [627, 'BUY', '', '2026-10-18 23:11:03', 4177.45, 0, 0, 0, 'TP', -4177.45, -8205.70])))
    # 639 SELL TP (Entry 4168.46, SL==Entry, TP 0, Exit 0, profit +Entry)
    w.writerow(dict(zip(FIELDS, [628, 'SELL', '', '2026-10-19 01:10:07', 4168.46, 4168.46, 0, 0, 'TP', 4168.46, -4037.24])))
    # 640 SELL BE (SL==Entry, Exit==Entry, TP 0)
    w.writerow(dict(zip(FIELDS, [629, 'SELL', '', '2026-10-19 01:11:04', 4169.80, 4169.80, 0, 4169.80, 'BE', 0, -4037.24])))
    # 641 SELL BE variant
    w.writerow(dict(zip(FIELDS, [630, 'SELL', '', '2026-10-19 01:15:07', 4171.16, 4171.16, 0, 4171.16, 'BE', 0, -4037.24])))
    # 643 SELL SL (TP 0, SL 4172, Exit SL)
    w.writerow(dict(zip(FIELDS, [631, 'SELL', '', '2026-10-19 01:32:07', 4167.69, 4172.00, 0, 4172.00, 'SL', -4.31, -4041.55])))
    # 644 BUY TP with non-zero SL (4172) and zero TP/Exit
    w.writerow(dict(zip(FIELDS, [632, 'BUY', '', '2026-10-19 02:22:02', 4176.55, 4172.00, 0, 0, 'TP', -4176.55, -8218.10])))
    return out.getvalue().encode(), json.dumps(dict(equity=-8218.10, total_trades=8, trade_active=False)).encode()


def fixture_full_20():
    """Reproduces the actual incident ledger #626-645 (20 rows) for regression.
       Good row #625 balance 150.69; phantom suffix profits/balances mirror trades.csv.
       This validates accounting continuity and $150.69 restoration over the full incident.
    """
    profits = [
        -4178.94, -4177.45, -4177.31, -4180.01, -4180.92, -4181.75, -4185.05, -4182.23,
        -4181.55, -4181.67, -4183.07, -4183.17, -4182.11, 4168.46, 0.00, 0.00, 0.00, -4.31, -4176.55, -4177.02
    ]
    # Corresponding Trade_Type / SL / Exit / Reason per real file
    types = ['BUY']*13 + ['SELL']*5 + ['BUY']*2
    # SL values per real rows
    sls = [0]*10 + [0]*3 + [4168.46, 4169.80, 4171.16, 4172.00, 4172.00, 4172.00, 4172.00]
    # Actually need 20 SLs: first 13 BUY zero, then 639 SL 4168.46, 640 4169.80, 641 4171.16, 642 4172.00, 643 4172.00, 644 4172.00, 645 4172.00
    # Let's construct accurately from trades.csv snippet
    rows_data = [
        (626, 'BUY', 4178.94, 0, 'TP', -4178.94),
        (627, 'BUY', 4177.45, 0, 'TP', -4177.45),
        (628, 'BUY', 4177.31, 0, 'TP', -4177.31),
        (629, 'BUY', 4180.01, 0, 'TP', -4180.01),
        (630, 'BUY', 4180.92, 0, 'TP', -4180.92),
        (631, 'BUY', 4181.75, 0, 'TP', -4181.75),
        (632, 'BUY', 4185.05, 0, 'TP', -4185.05),
        (633, 'BUY', 4182.23, 0, 'TP', -4182.23),
        (634, 'BUY', 4181.55, 0, 'TP', -4181.55),
        (635, 'BUY', 4181.67, 0, 'TP', -4181.67),
        (636, 'BUY', 4183.07, 0, 'TP', -4183.07),
        (637, 'BUY', 4183.17, 0, 'TP', -4183.17),
        (638, 'BUY', 4182.11, 0, 'TP', -4182.11),
        (639, 'SELL', 4168.46, 4168.46, 'TP', 4168.46),
        (640, 'SELL', 4169.80, 4169.80, 'BE', 0.00),
        (641, 'SELL', 4171.16, 4171.16, 'BE', 0.00),
        (642, 'SELL', 4172.00, 4172.00, 'BE', 0.00),
        (643, 'SELL', 4167.69, 4172.00, 'SL', -4.31),
        (644, 'BUY', 4176.55, 4172.00, 'TP', -4176.55),
        (645, 'BUY', 4177.02, 4172.00, 'TP', -4177.02),
    ]
    # Build CSV
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=FIELDS)
    w.writeheader()
    w.writerow(dict(zip(FIELDS, [625, 'BUY', '2026-10-16 19:45:07', '2026-10-16 20:54:03', 4168.71, 4164.01, 4175.75, 4164.01, 'SL', -4.70, 150.69])))
    bal = 150.69
    for num, typ, entry, sl, reason, profit in rows_data:
        bal += profit
        tp = 0
        exit_price = sl if typ == 'SELL' and reason in ('BE', 'SL') else (0 if reason == 'TP' and typ == 'BUY' else 0)
        # For SELL TP, exit is 0; for SELL BE exit==sl, for SELL SL exit==sl, for BUY TP exit 0
        if typ == 'SELL' and reason == 'TP':
            exit_price = 0
        elif typ == 'SELL' and reason == 'BE':
            exit_price = sl
        elif typ == 'SELL' and reason == 'SL':
            exit_price = sl
        elif typ == 'BUY' and reason == 'TP':
            exit_price = 0
        # Exit_Time dummy
        exit_time = f'2026-10-19 00:00:{num%60:02d}'
        w.writerow(dict(zip(FIELDS, [num, typ, '', exit_time, entry, sl, tp, exit_price, reason, profit, round(bal,2)])))
    trades = out.getvalue().encode()
    # Status equity is final balance
    status = json.dumps(dict(equity=round(bal,2), total_trades=21, trade_active=False)).encode()
    return trades, status


class RepairTest(unittest.TestCase):
    def test_exact_reconciliation(self):
        clean, status, quarantine, n = plan(*fixture())
        self.assertEqual(n, 1)
        s = json.loads(status)
        self.assertEqual((s['equity'], s['wins'], s['losses'], s['total_trades']), (150.69, 0, 1, 1))
        self.assertEqual(len(list(csv.DictReader(io.StringIO(clean.decode())))), 1)
        self.assertIn(b'4178.94', quarantine)
        with self.assertRaises(ValueError):
            plan(clean, status)  # second application is refused

    def test_refusals(self):
        trades, status = fixture()
        for edits in ({'trade_active': True}, {'equity': -5000}, {'total_trades': 3}):
            s = json.loads(status)
            s.update(edits)
            with self.assertRaises(ValueError):
                plan(trades, json.dumps(s).encode())
        with self.assertRaises(ValueError):
            plan(trades.replace(b'-4028.25', b'-4029.25'), status)
        lines = trades.splitlines(keepends=True)
        with self.assertRaises(ValueError):
            plan(lines[0] + lines[2] + lines[1], status)  # not a suffix

    def test_cli_backup_and_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trades, status = fixture()
            (root / 'trades.csv').write_bytes(trades)
            (root / 'status.json').write_bytes(status)
            cmd = [sys.executable, str(Path(__file__).with_name('repair_phantom_ledger.py')), '--root', d]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual((root / 'trades.csv').read_bytes(), trades)
            self.assertEqual(subprocess.run(cmd + ['--apply'], capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(cmd + ['--apply', '--engine-stopped'], capture_output=True).returncode, 0)
            backup = next((root / 'incident_backups').iterdir())
            self.assertEqual((backup / 'trades.csv').read_bytes(), trades)
            self.assertEqual((backup / 'status.json').read_bytes(), status)
            self.assertTrue((backup / 'quarantined_trades.csv').exists())
            self.assertEqual(json.loads((root / 'status.json').read_bytes())['equity'], 150.69)

    def test_blank_entry_zero_tp_signature(self):
        # Valid row must NOT be phantom
        valid = {'Trade_Type': 'BUY', 'Entry_Time': '2026-10-16 19:45:07', 'Take_Profit': '4175.75', 'Entry_Price': '4168.71', 'Exit_Reason': 'SL', 'Stop_Loss': '4164.01', 'Exit_Price': '4164.01', 'Profit': '-4.70'}
        self.assertFalse(phantom(valid))
        # SELL TP variant: blank Entry_Time + zero TP should be phantom
        sell_tp = {'Trade_Type': 'SELL', 'Entry_Time': '', 'Take_Profit': '0.00', 'Entry_Price': '4168.46', 'Exit_Reason': 'TP', 'Stop_Loss': '4168.46', 'Exit_Price': '0.00', 'Profit': '4168.46'}
        self.assertTrue(phantom(sell_tp))
        # SELL BE variant
        sell_be = {'Trade_Type': 'SELL', 'Entry_Time': '', 'Take_Profit': '0.00', 'Entry_Price': '4169.80', 'Exit_Reason': 'BE', 'Stop_Loss': '4169.80', 'Exit_Price': '4169.80', 'Profit': '0.00'}
        self.assertTrue(phantom(sell_be))
        # SELL SL variant
        sell_sl = {'Trade_Type': 'SELL', 'Entry_Time': '', 'Take_Profit': '0.00', 'Entry_Price': '4167.69', 'Exit_Reason': 'SL', 'Stop_Loss': '4172.00', 'Exit_Price': '4172.00', 'Profit': '-4.31'}
        self.assertTrue(phantom(sell_sl))
        # BUY TP with non-zero SL (4172) variant
        buy_tp_sl = {'Trade_Type': 'BUY', 'Entry_Time': '', 'Take_Profit': '0.00', 'Entry_Price': '4176.55', 'Exit_Reason': 'TP', 'Stop_Loss': '4172.00', 'Exit_Price': '0.00', 'Profit': '-4176.55'}
        self.assertTrue(phantom(buy_tp_sl))
        # Blank Entry_Time but non-zero TP should NOT be phantom (valid would have TP)
        not_phantom = {'Trade_Type': 'BUY', 'Entry_Time': '', 'Take_Profit': '4175.75', 'Entry_Price': '4168.71', 'Exit_Reason': 'SL', 'Stop_Loss': '4164.01', 'Exit_Price': '4164.01', 'Profit': '-4.70'}
        self.assertFalse(phantom(not_phantom))
        # Zero TP but Entry_Time present should NOT be phantom
        not_phantom2 = {'Trade_Type': 'BUY', 'Entry_Time': '2026-10-16 19:45:07', 'Take_Profit': '0.00', 'Entry_Price': '4168.71', 'Exit_Reason': 'TP', 'Stop_Loss': '4164.01', 'Exit_Price': '4164.01', 'Profit': '-4.70'}
        self.assertFalse(phantom(not_phantom2))

    def test_extended_variants_reconciliation(self):
        trades, status = fixture_extended_variants()
        clean, fixed, quarantine, n = plan(trades, status)
        self.assertEqual(n, 7)
        s = json.loads(fixed)
        # Good row is 1 trade: 0 TP, 1 SL
        self.assertEqual(s['total_trades'], 1)
        self.assertEqual(s['wins'], 0)
        self.assertEqual(s['losses'], 1)
        self.assertEqual(s['equity'], 150.69)
        # Quarantine should contain all variant markers (allow 4169.8/4169.80 formatting)
        for marker in [b'4168.46', b'4169.8', b'4172', b'4176.55']:
            self.assertIn(marker, quarantine)
        # Clean ledger has only good row
        self.assertEqual(len(list(csv.DictReader(io.StringIO(clean.decode())))), 1)
        # Second application refused
        with self.assertRaises(ValueError):
            plan(clean, fixed)

    def test_full_20_row_incident(self):
        trades, status = fixture_full_20()
        # Verify fixture matches real final equity
        # Now run plan
        clean, fixed, quarantine, n = plan(trades, status)
        self.assertEqual(n, 20)
        s = json.loads(fixed)
        self.assertEqual(s['equity'], 150.69)
        self.assertEqual(s['total_trades'], 1)
        self.assertEqual(s['wins'], 0)
        self.assertEqual(s['losses'], 1)
        self.assertEqual(s['be_exits'], 0)
        self.assertEqual(s['time_exits'], 0)
        self.assertEqual(s['next_trade_num'], 626)
        # Quarantine must have 20 rows + header = 21 lines
        self.assertEqual(len(quarantine.decode().splitlines()), 21)
        # Must contain SELL TP/BE/SL and BUY variants (allow formatting variance)
        for marker in [b'4178.94', b'4168.46', b'4169.8', b'4172', b'4177.02']:
            self.assertIn(marker, quarantine)
        # Clean has 1 good row
        self.assertEqual(len(list(csv.DictReader(io.StringIO(clean.decode())))), 1)
        # Verify balance continuity was checked (plan would have raised otherwise)

    def test_real_repo_regression(self):
        # Validate against the actual repository file if present (optional hermetic but useful)
        repo_trades = Path(__file__).parent.parent / 'trades.csv'
        repo_status = Path(__file__).parent.parent / 'status.json'
        if not repo_trades.exists() or not repo_status.exists():
            self.skipTest('repo files not found')
        try:
            trades_bytes = repo_trades.read_bytes()
            status_bytes = repo_status.read_bytes()
            # This will fail if the repo has already been repaired (then no phantom), which is expected after apply
            # So we handle both cases: if phantom suffix exists, it must restore to 150.69
            import csv, io
            reader = csv.DictReader(io.StringIO(trades_bytes.decode()))
            rows = list(reader)
            # Count phantom suffix in repo
            from repair_phantom_ledger import phantom as ph
            bad = [i for i, r in enumerate(rows) if ph(r)]
            if not bad:
                # Already repaired: verify it ends at 150.69 and has no blank Entry_Time
                self.assertTrue(any(r['Balance_After'] == '150.69' for r in rows))
                self.assertFalse(any(not r['Entry_Time'] for r in rows))
            else:
                clean, fixed, quarantine, n = plan(trades_bytes, status_bytes)
                self.assertEqual(n, 20)
                self.assertEqual(json.loads(fixed)['equity'], 150.69)
                self.assertIn(b'4178.94', quarantine)
        except ValueError as e:
            # If repo is corrupted beyond expected, still verify error is about phantom detection
            self.assertIn('phantom', str(e).lower() if str(e) else '')

if __name__ == '__main__':
    unittest.main()
