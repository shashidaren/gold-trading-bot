"""Hermetic tests for the display-only dashboard panels."""
import os
import sys
import unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pressure as P


class DashboardContextTests(unittest.TestCase):
    def test_costed_scratches_and_exit_order(self):
        rows = [dict(Entry_Time='2026-10-07 01:00:00', Exit_Time=f'2026-10-07 02:0{i}:00',
                     Entry_Price='100', Take_Profit='103', Profit=str(p), Trade_Type=side)
                for i, (p, side) in enumerate([(3, 'BUY'), (-2, 'SELL'), (0, 'BUY')])]
        all_, buy, sell = P.evidence_read(list(reversed(rows)))
        self.assertAlmostEqual(all_['net'], -.2)
        self.assertAlmostEqual(all_['dd'], 2.8)
        self.assertAlmostEqual(all_['expectancy'], -.2/6)
        self.assertEqual((buy['n'], sell['n']), (2, 1))
        self.assertIsNone(P.evidence_read([])[0]['expectancy'])

    def test_completed_buckets_and_gap(self):
        start = datetime(2026, 10, 19)
        rows = [dict(Timestamp=str(start+timedelta(minutes=i)), High=i+2, Low=i,
                     Close=i+1, ATR=2) for i in range(241)]
        result = P.market_map(rows)
        self.assertEqual(result['trends'][1]['delta'], 180)
        # Last forming H1 close must not enter the measurement.
        rows[-1]['Close'] = 99999
        self.assertEqual(P.market_map(rows)['trends'][1]['delta'], 180)
        del rows[100]
        self.assertIsNone(P.market_map(rows)['trends'][1]['delta'])
        self.assertIsNone(P.market_map([]))

    def test_quote_freshness_and_closure(self):
        now = datetime(2026, 10, 19, 20)
        status = dict(trade_active=True, entry_time='2026-10-19 19:00:00')
        quote = dict(ts_utc='2026-10-19 19:59:30', spread='.55', n_ok='6', flags='')
        r = P.risk_read(status, [quote], now)
        self.assertTrue(r['spans'])
        self.assertFalse(r['quote']['stale'])
        self.assertTrue(P.risk_read(status, [quote], now+timedelta(minutes=3))['quote']['stale'])
        quote['flags'] = 'bad'
        self.assertIsNone(P.risk_read({}, [quote], now)['quote'])
        self.assertIsNone(P.risk_read({}, [], now)['remaining'])

    def test_render(self):
        os.environ['GOLD_DATA_DIR'] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import dashboard
        response = dashboard.app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        for title in ('Risk now', 'Market map', 'Costed evidence'):
            self.assertIn(title, response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
