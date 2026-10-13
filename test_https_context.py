"""TLS handshakes in memory; no network interception or OS certificate edits."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

import https_context
import offers
import sources


class VerifiedHttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Catalogue TLS test CA')])
        cls.now = datetime.now(timezone.utc)
        ca = (x509.CertificateBuilder().subject_name(cls.name).issuer_name(cls.name)
              .public_key(cls.key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(cls.now-timedelta(days=2)).not_valid_after(cls.now+timedelta(days=2))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
                  content_commitment=False, data_encipherment=False, key_agreement=False,
                  key_cert_sign=True, crl_sign=True, encipher_only=None, decipher_only=None), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(cls.key.public_key()), critical=False)
              .sign(cls.key, hashes.SHA256()))
        cls.ca_path = cls.root/'ca.pem'
        cls.ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tearDown(self):
        https_context.https_context.cache_clear()

    def server(self, hostname='localhost', expired=False):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
                .issuer_name(self.name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(self.now-timedelta(days=2))
                .not_valid_after(self.now+timedelta(days=-1 if expired else 1))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.key.public_key()), critical=False)
                .sign(self.key, hashes.SHA256()))
        cert_path, key_path = self.root/'server.pem', self.root/'server.key'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        return context

    def client(self, trusted=True):
        https_context.https_context.cache_clear()
        context = https_context.https_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        if trusted:
            context.load_verify_locations(cafile=str(self.ca_path))
        return context

    def handshake(self, hostname='localhost', expired=False, trusted=True):
        # Passing real handshake bytes through MemoryBIO avoids antivirus HTTPS
        # interception of localhost without changing antivirus or trust settings.
        client_in, client_out, server_in, server_out = (ssl.MemoryBIO() for _ in range(4))
        client = self.client(trusted).wrap_bio(client_in, client_out, server_hostname='localhost')
        server = self.server(hostname, expired).wrap_bio(server_in, server_out, server_side=True)
        complete = [False, False]
        for _ in range(20):
            for i, connection in enumerate((client, server)):
                if not complete[i]:
                    try:
                        connection.do_handshake()
                        complete[i] = True
                    except ssl.SSLWantReadError:
                        pass
            for outgoing, incoming in ((client_out, server_in), (server_out, client_in)):
                if outgoing.pending:
                    incoming.write(outgoing.read())
            if all(complete):
                return client
        self.fail('TLS handshake did not complete')

    def test_valid_certificate_succeeds(self):
        self.assertIn('TLS', self.handshake().version())

    def test_expired_wrong_hostname_and_untrusted_certificates_are_rejected(self):
        for hostname, expired, trusted in [('localhost', True, True),
                                            ('wrong.example', False, True),
                                            ('localhost', False, False)]:
            with self.subTest(hostname=hostname, expired=expired, trusted=trusted):
                with self.assertRaises(ssl.SSLCertVerificationError):
                    self.handshake(hostname, expired, trusted)

    def test_missing_windows_dependency_is_explicit(self):
        https_context.https_context.cache_clear()
        with patch.object(https_context.sys, 'platform', 'win32'), patch.dict(sys.modules, {'truststore': None}):
            with self.assertRaisesRegex(ValueError, 'requirements.txt'):
                https_context.https_context()

    def test_catalogue_and_pdf_downloads_both_use_verified_context(self):
        error = urllib.error.URLError(ssl.SSLCertVerificationError(1, 'Certificate failed'))
        context = https_context.https_context()
        with patch.object(urllib.request, 'urlopen', side_effect=error) as opened:
            with self.assertRaises(urllib.error.URLError):
                sources.fetch('https://example.test/catalogue')
            self.assertIs(opened.call_args.kwargs['context'], context)
            self.assertEqual(opened.call_count, 1)
            opened.reset_mock()
            with patch.object(offers, 'CACHE', self.root/'pdf-cache'), \
                 patch.object(offers, 'pdf_url', return_value='https://example.test/leaflet.pdf'):
                with self.assertRaises(urllib.error.URLError):
                    offers.download({'id': 'tls-failure'})
            self.assertIs(opened.call_args.kwargs['context'], context)
            self.assertEqual(opened.call_count, 1)
            self.assertFalse(any((self.root/'pdf-cache').iterdir()))


if __name__ == '__main__':
    unittest.main()
