"""Offline checks: printed offer dates and preserving saved leaflets on failures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import flyers


class FlyerParsingTests(unittest.TestCase):
    def test_printed_dates_years_and_footnotes(self):
        cases = [
            ('VON DONNERSTAG, 1. 10. BIS MITTWOCH, 7. 10. 20261)', ('2026-10-01', '2026-10-07')),
            ('Do., 01.10.26 - Mi., 07.10.26', ('2026-10-01', '2026-10-07')),
            ('Gültig ab Fr. 2.10. bis Do. 8.10', ('2026-10-02', '2026-10-08')),
            ('29.12. bis 04.01.2027', ('2026-12-29', '2027-01-04')),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(flyers.date_range(text, '2026-10-02'), expected)

    def test_current_includes_endpoints_and_excludes_future_expired_unknown(self):
        row = {'valid_from': '2026-10-01', 'valid_to': '2026-10-07'}
        for day, expected in [('2026-09-30', False), ('2026-10-01', True), ('2026-10-07', True), ('2026-10-08', False)]:
            self.assertEqual(flyers.current(row, day), expected)
        self.assertFalse(flyers.current({}, '2026-10-02'))

    def test_lidl_uses_offer_dates_not_publication_dates(self):
        data = {'success': True, 'flyer': {'countryCode': 'AT', 'startDate': '2026-09-27', 'endDate': '2026-10-07',
                'offerStartDate': '2026-10-01', 'offerEndDate': '2026-10-07', 'flyerUrlAbsolute': 'https://www.lidl.at/l/de/flugblatt/test/ar/0'}}
        row = flyers.parse_lidl(data)
        self.assertEqual(row['valid_from'], '2026-10-01')
        self.assertFalse(flyers.current(row, '2026-09-28'))

    def test_penny_reads_official_link_without_requesting_blocked_reader(self):
        html = '<a href="https://e.issuu.com/embed.html?d=penny_flugblatt_do_01.10._bis_mi_07.10.2026&amp;u=pennyat"><picture><img src="https://www.penny.at/cover.png"></picture></a>'
        with patch.object(flyers, 'fetch', return_value=html) as fetch:
            rows = flyers.read_penny('2026-10-02')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['valid_to'], '2026-10-07')
        self.assertEqual(rows[0]['image'], 'https://www.penny.at/cover.png')
        fetch.assert_called_once_with(flyers.SOURCES['penny'])


class FlyerPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(app, 'DB', Path(self.tmp.name) / 'test.sqlite3')
        self.patch.start()
        app.initialize()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def save(self, ident, start='2000-01-01', end='2099-01-01'):
        row = flyers.item('billa', 'https://www.billa.at/' + ident, (start, end))
        with patch.object(app, 'read_flyers', return_value=([row], '')):
            app.import_flyers('billa')
        return row

    def test_failed_refresh_preserves_rows_and_check_time(self):
        row = self.save('previous')
        before = app.flyer_state()['stores'][1]['checked_at']
        with patch.object(app, 'read_flyers', side_effect=TimeoutError('Network')):
            app.import_flyers('billa')
        state = app.flyer_state()
        self.assertEqual(state['items'][0]['id'], row['id'])
        self.assertEqual(state['stores'][1]['checked_at'], before)
        self.assertEqual(state['stores'][1]['status'], 'error')

    def test_success_replaces_missing_and_dates_expire_without_refresh(self):
        self.save('previous')
        row = self.save('current', '2026-10-01', '2026-10-07')
        with patch.object(app, '_vienna_date', return_value='2026-10-07'):
            self.assertEqual([r['id'] for r in app.flyer_state()['items']], [row['id']])
        with patch.object(app, '_vienna_date', return_value='2026-10-08'):
            self.assertEqual(app.flyer_state()['total'], 0)

    def test_malformed_batch_does_not_replace_saved_data(self):
        previous = self.save('previous')
        broken = flyers.item('billa', 'https://www.billa.at/broken', ('2026-10-09', '2026-10-01'))
        with patch.object(app, 'read_flyers', return_value=([broken], '')):
            app.import_flyers('billa')
        self.assertEqual(app.flyer_state()['items'][0]['id'], previous['id'])

    def test_partial_source_is_not_reported_as_complete(self):
        row = flyers.item('spar', 'https://flugblatt.spar.at/wien/spar/example/', ('2000-01-01', '2099-01-01'))
        with patch.object(app, 'read_flyers', return_value=([row], 'Index unavailable')):
            app.import_flyers('spar')
        state = app.flyer_state()
        self.assertEqual(state['stores'][0]['status'], 'partial')
        self.assertEqual(state['stores'][0]['error'], 'Index unavailable')
        self.assertEqual(state['total'], 1)


if __name__ == '__main__':
    unittest.main()
