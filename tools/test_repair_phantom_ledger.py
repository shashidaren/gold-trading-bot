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
from repair_phantom_ledger import plan

FIELDS = 'Trade_Num Trade_Type Entry_Time Exit_Time Entry_Price Stop_Loss Take_Profit Exit_Price Exit_Reason Profit Balance_After'.split()


def fixture():
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=FIELDS)
    w.writeheader()
    w.writerow(dict(zip(FIELDS, [625, 'BUY', '2026-10-16 19:45:07', '2026-10-16 20:54:03', 4168.71, 4164.01, 4175.75, 4164.01, 'SL', -4.70, 150.69])))
    w.writerow(dict(zip(FIELDS, [626, 'BUY', '', '2026-10-18 23:05:06', 4178.94, 0, 0, 0, 'TP', -4178.94, -4028.25])))
    return out.getvalue().encode(), json.dumps(dict(equity=-4028.25, total_trades=2, trade_active=False)).encode()


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


if __name__ == '__main__':
    unittest.main()
