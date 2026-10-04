"""Offline checks for network restrictions, bounded retries, and saved prices."""
import errno
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import app
import sources


def windows_error(code):
    # Explicitly set winerror so these checks also work outside Windows.
    error = OSError(0, 'Connection unavailable')
    error.winerror = code
    return urllib.error.URLError(error)


class NetworkFailureTests(unittest.TestCase):
    def test_wrapped_windows_errors_are_classified(self):
        for code, expected in [(10013, 'access_denied'), (10050, 'unreachable'),
                               (10051, 'unreachable'), (10065, 'unreachable')]:
            with self.subTest(code=code):
                self.assertEqual(sources.network_error_kind(windows_error(code)), expected)

    def test_posix_errors_are_classified_directly_and_wrapped(self):
        for code, expected in [(errno.EACCES, 'access_denied'), (errno.EPERM, 'access_denied'),
                               (errno.ENETUNREACH, 'unreachable'), (errno.ENETDOWN, 'unreachable'),
                               (errno.EHOSTUNREACH, 'unreachable')]:
            for wrapped in (False, True):
                with self.subTest(code=code, wrapped=wrapped):
                    error = OSError(code, 'Connection unavailable')
                    if wrapped:
                        error = urllib.error.URLError(error)
                    self.assertEqual(sources.network_error_kind(error), expected)

    def test_temporary_errors_are_not_classified_as_restrictions(self):
        for error in [TimeoutError('Timed out'), urllib.error.URLError(TimeoutError('Timed out')),
                      urllib.error.URLError('Temporary DNS failure')]:
            with self.subTest(error=repr(error)):
                self.assertNotIn(sources.network_error_kind(error), ('access_denied', 'unreachable'))

    def test_restricted_or_unreachable_network_does_not_retry_or_sleep(self):
        failures = [windows_error(code) for code in (10013, 10050, 10051, 10065)]
        failures.extend(urllib.error.URLError(OSError(code, 'Connection unavailable'))
                        for code in (errno.EACCES, errno.EPERM, errno.ENETUNREACH,
                                     errno.ENETDOWN, errno.EHOSTUNREACH))
        for error in failures:
            with self.subTest(error=repr(error.reason)):
                with patch.object(sources.urllib.request, 'urlopen', side_effect=error) as request, \
                     patch.object(sources.time, 'sleep') as sleep:
                    with self.assertRaises(urllib.error.URLError) as raised:
                        sources.fetch('https://example.test/catalog')
                    self.assertIs(raised.exception, error)
                    request.assert_called_once()
                    sleep.assert_not_called()

    def test_temporary_timeout_and_service_unavailable_can_recover(self):
        failures = [urllib.error.URLError(TimeoutError('Timed out')),
                    urllib.error.HTTPError('https://example.test/catalog', 503,
                                           'Service unavailable', {}, None)]
        for error in failures:
            with self.subTest(error=repr(error)):
                response = MagicMock()
                response.__enter__.return_value = response
                response.headers = {}
                response.read.side_effect = [b'{"products": []}', b'']
                with patch.object(sources.urllib.request, 'urlopen', side_effect=[error, response]) as request, \
                     patch.object(sources.time, 'sleep') as sleep:
                    self.assertEqual(sources.fetch('https://example.test/catalog'), '{"products": []}')
                    self.assertEqual(request.call_count, 2)
                    sleep.assert_called_once()

    def test_temporary_failure_stops_after_three_attempts(self):
        error = urllib.error.URLError(TimeoutError('Timed out'))
        with patch.object(sources.urllib.request, 'urlopen', side_effect=error) as request, \
             patch.object(sources.time, 'sleep') as sleep:
            with self.assertRaises(urllib.error.URLError):
                sources.fetch('https://example.test/catalog')
            self.assertEqual(request.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_http_forbidden_does_not_retry(self):
        error = urllib.error.HTTPError('https://example.test/catalog', 403, 'Forbidden', {}, None)
        with patch.object(sources.urllib.request, 'urlopen', side_effect=error) as request, \
             patch.object(sources.time, 'sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                sources.fetch('https://example.test/catalog')
            request.assert_called_once()
            sleep.assert_not_called()


class FailedRefreshPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(app, 'DB', Path(self.tmp.name) / 'test.sqlite3')
        self.db_patch.start()
        app.initialize()
        self.stamp = '2026-10-01T08:00:00+00:00'
        self.row = {'store': 'spar', 'id': 'saved', 'name': 'Milch', 'price': 1.99}
        with patch.object(app, 'now', return_value=self.stamp):
            app.save_page('spar', [dict(self.row)], 'old-run', 'https://example.test/catalog')
        with app.connect() as db:
            db.execute("UPDATE imports SET status='complete',last_success=? WHERE store='spar'", (self.stamp,))
        self.before = app.products({})['items'][0]

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_failed_network_refresh_preserves_data_and_explains_different_causes(self):
        messages = []
        for code in (10013, 10051):
            with self.subTest(code=code):
                with patch.object(app, 'pages', side_effect=windows_error(code)), patch('builtins.print'):
                    app.import_store('spar')
                result = app.products({})
                self.assertEqual(result['total'], 1)
                after = result['items'][0]
                self.assertEqual((after['id'], after['price'], after['checked_at']),
                                 (self.before['id'], self.before['price'], self.before['checked_at']))
                with app.connect() as db:
                    self.assertEqual(db.execute("SELECT active FROM products WHERE store='spar'").fetchone()[0], 1)
                    status = dict(db.execute("SELECT * FROM imports WHERE store='spar'").fetchone())
                self.assertEqual(status['status'], 'error')
                self.assertEqual(status['last_success'], self.stamp)
                self.assertTrue(status['error'])
                messages.append(status['error'])
        self.assertNotEqual(messages[0], messages[1], 'Blocked and unreachable networks need different explanations')

    def test_successful_retry_clears_failure_and_updates_saved_price(self):
        with patch.object(app, 'pages', side_effect=windows_error(10013)), patch('builtins.print'):
            app.import_store('spar')
        new_stamp = '2026-10-04T09:00:00+00:00'
        updated = {**self.row, 'price': 2.49}
        page = ([updated], {'saved'}, 1, 'Page 1', 'https://example.test/catalog')
        with patch.object(app, 'pages', return_value=iter([page])), \
             patch.object(app, 'now', return_value=new_stamp), patch('builtins.print'):
            app.import_store('spar')
        with app.connect() as db:
            status = dict(db.execute("SELECT * FROM imports WHERE store='spar'").fetchone())
        self.assertEqual((status['status'], status['error'], status['last_success']), ('complete', '', new_stamp))
        after = app.products({})['items'][0]
        self.assertEqual((after['price'], after['checked_at']), (2.49, new_stamp))


if __name__ == '__main__':
    unittest.main()
