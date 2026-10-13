"""Use the platform certificate verifier for retailer HTTPS connections."""
import ssl
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def https_context():
    if sys.platform == 'win32':
        try:
            import truststore
        except ImportError as error:
            raise ValueError('Не установлена поддержка сертификатов Windows. Установите зависимости из requirements.txt и перезапустите каталог.') from error
        # Windows builds the chain using its current certificate stores instead
        # of copying cached intermediates into OpenSSL's trusted certificate set.
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    else:
        context = ssl.create_default_context()
    context.set_alpn_protocols(['http/1.1'])
    return context
