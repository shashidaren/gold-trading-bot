#!/usr/bin/env python3
"""Dry-run by default. Quarantine ONLY a verified suffix of zero-price phantom BUYs.

Run with the engine AND autosync stopped. --apply requires --engine-stopped.
Backups are private runtime evidence, not repository deliverables. Two-file writes
are not transactional: on interruption restore BOTH originals from the backup.
"""
import argparse
import csv
import io
import json
import os
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
import tempfile


def phantom(row):
    try:
        return (row['Trade_Type'] == 'BUY' and row['Exit_Reason'] == 'TP'
                and not row['Entry_Time']
                and all(Decimal(row[k]) == 0 for k in
                        ('Stop_Loss', 'Take_Profit', 'Exit_Price'))
                and Decimal(row['Entry_Price']) > 0
                and Decimal(row['Profit']) == -Decimal(row['Entry_Price']))
    except (KeyError, ArithmeticError):
        return False


def plan(trade_bytes, status_bytes):
    reader = csv.DictReader(io.StringIO(trade_bytes.decode()))
    fields = reader.fieldnames
    rows = list(reader)
    status = json.loads(status_bytes)
    if status.get('trade_active'):
        raise ValueError('open position: manual reconciliation required')
    bad = [i for i, row in enumerate(rows) if phantom(row)]
    if not bad:
        raise ValueError('no matching phantom rows; nothing to repair')
    start = bad[0]
    if start == 0 or bad != list(range(start, len(rows))):
        raise ValueError('phantoms are not a contiguous suffix after valid history')
    good, removed = rows[:start], rows[start:]
    if any(not r['Entry_Time'] or not r['Exit_Time'] for r in good):
        raise ValueError('other invalid timestamps require manual reconciliation')
    balance = Decimal(good[-1]['Balance_After'])
    prev_num = int(good[-1]['Trade_Num'])
    for row in removed:
        balance += Decimal(row['Profit'])
        if abs(balance - Decimal(row['Balance_After'])) > Decimal('0.02'):
            raise ValueError('suffix balance continuity mismatch')
        if int(row['Trade_Num']) != prev_num + 1:
            raise ValueError('suffix numbering mismatch')
        prev_num += 1
    if (abs(Decimal(str(status['equity'])) - balance) > Decimal('0.02')
            or status['total_trades'] != len(rows)):
        raise ValueError('status/ledger mismatch: preserve and investigate newer data')
    counts = {reason: sum(r['Exit_Reason'] == reason for r in good)
              for reason in ('TP', 'SL', 'BE', 'TIME')}
    status.update(equity=float(Decimal(good[-1]['Balance_After'])),
                  total_trades=len(good), wins=counts['TP'], losses=counts['SL'],
                  be_exits=counts['BE'], time_exits=counts['TIME'],
                  next_trade_num=max(int(r['Trade_Num']) for r in good) + 1,
                  win_rate=round(100 * counts['TP'] / max(1, counts['TP'] + counts['SL']), 1))
    # Match startup numbering; identify quarantine records by timestamp + ID, not ID alone.
    def encode(data):
        out = io.StringIO(newline='')
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)
        return out.getvalue().encode()
    return encode(good), (json.dumps(status, indent=2) + '\n').encode(), encode(removed), len(removed)


def atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/gold'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--engine-stopped', action='store_true',
                        help='operator confirms engine AND autosync are stopped')
    args = parser.parse_args()
    root = args.root.resolve()
    trades, status = root / 'trades.csv', root / 'status.json'
    try:
        originals = trades.read_bytes(), status.read_bytes()
        clean, fixed, quarantine, n = plan(*originals)
        print(f'{n} phantom rows; restored reference equity {json.loads(fixed)["equity"]:.2f}')
        if not args.apply:
            print('DRY RUN: no files changed. Stop engine/autosync before --apply --engine-stopped.')
            return
        if not args.engine_stopped:
            raise ValueError('--apply requires --engine-stopped acknowledgement')
        backup = root / 'incident_backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup.mkdir(parents=True, mode=0o700)
        os.chmod(backup.parent, 0o700)
        for name, data in zip(('trades.csv', 'status.json'), originals):
            (backup / name).write_bytes(data)
        (backup / 'quarantined_trades.csv').write_bytes(quarantine)
        for name in ('forward_test_log.csv',):
            if (root / name).exists():
                import shutil
                shutil.copy2(root / name, backup / name)
        if (trades.read_bytes(), status.read_bytes()) != originals:
            raise ValueError('files changed during backup: aborting')
        print(f'Backup: {backup}; restore BOTH originals if interrupted')
        atomic_write(trades, clean)
        atomic_write(status, fixed)
        print('Reconciled. Run check_data.py before restarting the verified engine.')
    except (ValueError, KeyError, ArithmeticError, OSError) as exc:
        parser.exit(1, f'REFUSED: {exc}\n')


if __name__ == '__main__':
    main()
