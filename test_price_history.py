"""Price observations, honest baselines, comparison terms and atomic imports."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import app
import price_history
import test_catalog

NOW = '2026-10-12T12:00:00+00:00'


class HistoryTests(unittest.TestCase):
    setUp = test_catalog.PersistenceTests.setUp
    tearDown = test_catalog.PersistenceTests.tearDown

    def save(self, price=2, at='2026-10-01T12:00:00+00:00', store='spar', **kw):
        row = {'store': store, 'id': 'ref', 'name': 'Example Milk', 'unit': '1 l', 'price': price, **kw}
        with patch.object(app, 'now', return_value=at):
            app.save_page(store, [row], 'test', 'https://example.com')

    def query(self, days=90, store='spar'):
        with app.connect() as db:
            return price_history.query(db, store, 'ref', days, NOW, app.STORES)

    def test_baseline_uses_real_check_date_and_never_crossed_out_price(self):
        self.save(2, regular_price=3, offers=[{'price': 1, 'conditions': ['jö']}])
        with app.connect() as db:
            db.execute('DROP TABLE price_history')
        app.initialize()
        app.initialize()
        result = self.query()
        self.assertEqual(len(result['entries']), 1)
        entry = result['entries'][0]
        self.assertEqual(entry['observed_at'], ['2026-10-01T12:00:00+00:00'])
        self.assertEqual((entry['price_cents'], entry['regular_cents']), (200, 300))
        self.assertEqual(entry['offers'][0]['price_cents'], 100)
        self.assertEqual(result['minimum_cents'], 200)
        self.assertEqual(result['product']['checked_at'], entry['first_seen'])

    def test_equal_prices_compact_and_returning_price_creates_a_new_observation(self):
        self.save(2)
        self.save(2, at='2026-10-02T12:00:00+00:00')
        self.save(2, at='2026-10-02T12:00:00+00:00')
        self.save(1.5, at='2026-10-03T12:00:00+00:00')
        self.save(2, at='2026-10-04T12:00:00+00:00')
        result = self.query()
        self.assertEqual([p['price_cents'] for p in result['entries']], [200, 150, 200])
        self.assertEqual(len(result['entries'][0]['observed_at']), 2)
        self.assertEqual((result['minimum_cents'], result['change_cents']), (150, 50))

    def test_package_membership_name_or_terms_changes_are_not_simple_savings(self):
        cases = [{'unit': '500 ml'}, {'conditions': ['ab 2 Packungen']},
                 {'membership_required': True}, {'name': 'Different Milk'}, {'is_variable_weight': True}]
        for index, change in enumerate(cases):
            with self.subTest(change=change):
                self.save(3, at=f'2026-10-0{index+1}T10:00:00+00:00')
                self.save(1, at=f'2026-10-0{index+1}T11:00:00+00:00', **change)
                result = self.query()
                self.assertIsNone(result['change_cents'])
                self.assertEqual(result['minimum_cents'], 100)
                self.save(.5, at=f'2026-10-0{index+1}T12:00:00+00:00')
                result = self.query()
                self.assertIsNone(result['change_cents'])
                self.assertEqual(result['minimum_cents'], 50)

    def test_missing_pack_size_is_not_comparable(self):
        self.save(2, unit='')
        self.save(1, at='2026-10-02T12:00:00+00:00', unit='')
        result = self.query()
        self.assertIsNone(result['change_cents'])
        self.assertIsNone(result['minimum_cents'])

    def test_conditions_and_validity_survive_price_updates(self):
        self.save(1.49, single_price=1.99, conditions=['ab 2 Flaschen'], valid_from='2026-10-02', valid_to='2026-10-06')
        self.save(1.99, at='2026-10-07T12:00:00+00:00')
        first = self.query()['entries'][0]
        self.assertEqual(first['single_cents'], 199)
        self.assertEqual(first['conditions'], ['ab 2 Flaschen'])
        self.assertEqual((first['valid_from'], first['valid_to']), ('2026-10-02', '2026-10-06'))

    def test_period_uses_actual_checks_without_inventing_boundary_points(self):
        self.save(2, at='2026-08-01T12:00:00+00:00')
        self.assertEqual(self.query(30)['entries'], [])
        self.save(2, at='2026-10-01T12:00:00+00:00')
        entry = self.query(30)['entries'][0]
        self.assertEqual(entry['observed_at'], ['2026-10-01T12:00:00+00:00'])
        self.assertEqual(len(self.query(0)['entries'][0]['observed_at']), 2)

    def test_empty_period_and_inactive_product_keep_all_history(self):
        self.save(2, at='2026-01-01T12:00:00+00:00')
        with app.connect() as db:
            db.execute("UPDATE products SET active=0 WHERE id='ref'")
        self.assertEqual(self.query()['entries'], [])
        result = self.query(0)
        self.assertFalse(result['active'])
        self.assertEqual(len(result['entries']), 1)

    def test_other_stores_with_same_sku_have_separate_histories(self):
        self.save(2)
        self.save(1, store='billa')
        self.assertEqual(self.query()['minimum_cents'], 200)
        self.assertEqual(self.query(store='billa')['minimum_cents'], 100)

    def test_import_and_history_commit_or_rollback_together(self):
        self.save(2)
        with patch.object(price_history, 'record', side_effect=RuntimeError('test disk failure')):
            with self.assertRaises(RuntimeError):
                self.save(1, at='2026-10-02T12:00:00+00:00')
        result = self.query()
        self.assertEqual(result['product']['price'], 2)
        self.assertEqual(len(result['entries']), 1)
        with self.assertRaises(ValueError):
            self.save(-1)
        self.assertEqual(len(self.query()['entries']), 1)

    def test_failed_refresh_does_not_add_check_timestamp(self):
        self.save(2)
        before = self.query()
        with patch.object(app, 'pages', side_effect=OSError('test offline')):
            app.import_store('spar')
        self.assertEqual(self.query()['entries'], before['entries'])

    def test_older_observation_cannot_rewrite_history(self):
        self.save(2)
        with app.connect() as db:
            price_history.record(db, 'spar', 'ref', {'name': 'Example Milk', 'unit': '1 l', 'price': 1}, '2026-09-01T12:00:00+00:00')
        self.assertEqual(len(self.query()['entries']), 1)
        self.assertEqual(self.query()['minimum_cents'], 200)

    def test_history_is_bounded_and_reports_truncation(self):
        self.save(2)
        with app.connect() as db:
            for i in range(501):
                at = (datetime(2026, 10, 2, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat(timespec='seconds')
                price_history.record(db, 'spar', 'ref', {'name': 'Example Milk', 'unit': '1 l', 'price': 1+i%2}, at)
        result = self.query()
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['entries']), 500)

    def test_missing_or_invalid_reference(self):
        self.assertIsNone(self.query())
        self.save()
        with self.assertRaises(ValueError):
            self.query(365)
        with self.assertRaises(ValueError):
            self.query(store="' OR 1=1 --")


if __name__ == '__main__':
    unittest.main()
