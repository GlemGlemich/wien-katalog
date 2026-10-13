"""Offline checks for network restrictions, bounded retries, and saved prices."""
import errno
import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import app
import sources
import offers


def windows_error(code):
    # Explicitly set winerror so these checks also work outside Windows.
    error = OSError(0, 'Connection unavailable')
    error.winerror = code
    return urllib.error.URLError(error)


def certificate_error(code=10):
    error = ssl.SSLCertVerificationError(ssl.SSL_ERROR_SSL, 'Certificate verification failed')
    error.verify_code = code
    return error


class NetworkFailureTests(unittest.TestCase):
    def test_ssl_codes_do_not_collide_with_permission_errors(self):
        cases = [(certificate_error(10), 'certificate_expired'),
                 (certificate_error(9), 'certificate_not_yet_valid'),
                 (certificate_error(20), 'certificate_invalid'),
                 (ssl.SSLError(ssl.SSL_ERROR_SSL, 'Handshake failed'), 'tls_error')]
        for error, expected in cases:
            for wrapped in (error, urllib.error.URLError(error)):
                with self.subTest(kind=expected, wrapped=isinstance(wrapped, urllib.error.URLError)):
                    self.assertEqual(sources.network_error_kind(wrapped), expected)
                    self.assertIn('HTTPS', sources.network_error_message(wrapped))
                    self.assertNotIn('запретила', sources.network_error_message(wrapped))

    def test_expired_certificate_fails_without_retrying(self):
        error = urllib.error.URLError(certificate_error())
        with patch.object(sources.urllib.request, 'urlopen', side_effect=error) as request, \
             patch.object(sources.time, 'sleep') as sleep:
            with self.assertRaises(urllib.error.URLError):
                sources.fetch('https://example.test/catalog')
            request.assert_called_once()
            sleep.assert_not_called()

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

    def test_certificate_failure_is_explained_without_losing_catalogue_data(self):
        for code in (10, 9, 20):
            error = urllib.error.URLError(certificate_error(code))
            with patch.object(app, 'pages', side_effect=error), patch('builtins.print'):
                app.import_store('spar')
            after = app.products({})['items'][0]
            self.assertEqual((after['price'], after['checked_at']),
                             (self.before['price'], self.before['checked_at']))
            with app.connect() as db:
                row = db.execute("SELECT error,last_success FROM imports WHERE store='spar'").fetchone()
            self.assertEqual(tuple(row), (sources.network_error_message(error), self.stamp))

    def test_certificate_failure_is_shared_by_leaflet_and_pdf_imports(self):
        flyer = {'id': 'saved-flyer', 'store': 'hofer', 'url': 'https://example.test/leaflet',
                 'valid_from': '2026-10-01', 'valid_to': '2026-10-31'}
        with patch.object(app, 'read_flyers', return_value=([flyer], '')), \
             patch.object(app, 'now', return_value=self.stamp), patch('builtins.print'):
            app.import_flyers('hofer')
        with app.connect() as db:
            db.execute("INSERT INTO flyer_offers VALUES ('hofer','saved-offer','{}')")
            db.execute("UPDATE offer_imports SET checked_at=? WHERE store='hofer'", (self.stamp,))
            saved_flyer = tuple(db.execute("SELECT * FROM flyers WHERE store='hofer'").fetchone())
        error = urllib.error.URLError(certificate_error())
        with patch.object(app, 'read_flyers', side_effect=error), patch('builtins.print'):
            app.import_flyers('hofer')
        with patch.object(offers, 'read_offers', side_effect=error), patch('builtins.print'):
            offers.import_store('hofer', app.connect, '2026-10-13T08:00:00Z', '2026-10-13')
        with app.connect() as db:
            self.assertEqual(tuple(db.execute("SELECT * FROM flyers WHERE store='hofer'").fetchone()), saved_flyer)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM flyer_offers WHERE store='hofer'").fetchone()[0], 1)
            for table in ('flyer_imports', 'offer_imports'):
                row = db.execute(f"SELECT error,checked_at,status FROM {table} WHERE store='hofer'").fetchone()
                self.assertEqual(tuple(row), (sources.network_error_message(error), self.stamp, 'error'))


if __name__ == '__main__':
    unittest.main()
