"""Hermetic checks for manual watch references; no broker or engine imports."""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pressure as P

NOW = datetime(2026, 10, 20, 10)


def geometry(close=103, side=None):
    return dict(ok=True, as_of=NOW, close=close, atr=2,
                boxes=[dict(name='20-bar', high=106, low=100, width=6)],
                nearest=dict(box='20-bar'),
                trigger=dict(box='20-bar' if side else None,
                             state='break' if side else 'none', side=side))


def checks():
    return [dict(key=k, state='pass', detail=k) for k in
            ('feed', 'session', 'risk_state', 'volatility')]


class WatchTests(unittest.TestCase):
    def cards(self, close=103, side=None, now=NOW, health=None):
        return P.box_watch_cards(geometry(close, side), checks() if health is None else health,
                                 now, spread=.55)

    def test_mid_box_wait_and_symmetric_levels(self):
        buy, sell = self.cards()
        for card in (buy, sell):
            self.assertFalse(card['confirmed'])
            self.assertEqual(card['state'], 'WAIT — no breakout close')
            self.assertAlmostEqual(card['gross_rr'], 6 / card['risk'])
            self.assertAlmostEqual(card['net_rr'], 5.45 / (card['risk'] + .55))
            self.assertTrue(card['limited_reward'])
        self.assertGreater(buy['threshold'], 106)
        self.assertLess(sell['threshold'], 100)
        self.assertEqual(buy['stop'], 99)
        self.assertEqual(sell['stop'], 107)
        self.assertAlmostEqual(buy['risk'], sell['risk'])
        self.assertEqual(buy['target'], buy['entry'] + 6)
        self.assertEqual(sell['target'], sell['entry'] - 6)

    def test_breakout_uses_close_not_trigger_as_entry(self):
        for close, side, idx in ((107, 'BUY', 0), (99, 'SELL', 1)):
            card = self.cards(close, side)[idx]
            self.assertTrue(card['confirmed'])
            self.assertEqual(card['entry'], close)
            self.assertIn('not an entry signal', card['state'])

    def test_no_fresh_break_and_chase_warning(self):
        self.assertIn('no fresh break', self.cards(107)[0]['state'])
        for close, side, idx in ((109, 'BUY', 0), (97, 'SELL', 1)):
            card = self.cards(close, side)[idx]
            self.assertTrue(card['chasing'])
            self.assertEqual(card['state'], 'WAIT — do not chase')

    def test_stale_missing_health_and_closed_market_override(self):
        card = self.cards(107, 'BUY', NOW + timedelta(minutes=3))[0]
        self.assertEqual(card['state'], 'WAIT — health / risk check')
        for key in ('feed', 'session', 'risk_state', 'volatility'):
            health = checks()
            item = next(c for c in health if c['key'] == key)
            item.update(state='na', detail='unavailable or closed')
            card = self.cards(107, 'BUY', health=health)[0]
            self.assertEqual(card['state'], 'WAIT — health / risk check')
            self.assertIn('unavailable or closed', card['reasons'])

    def test_unavailable_geometry(self):
        self.assertEqual(P.box_watch_cards(dict(ok=False), [], NOW), [])

    def test_status_includes_cards_without_mutation(self):
        from test_box_report import flat
        geom = P.box_geometry(flat(0, n=30, atr=2))
        import copy
        original = copy.deepcopy(geom)
        result = P.box_status(geom, now=geom['as_of'])
        self.assertEqual(len(result['watch_cards']), 2)
        self.assertEqual(geom, original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
