"""Identity evidence, catalogue validity, parser retention and index updates."""
import json
import unittest
from unittest.mock import patch

import app
import matching
import parsers
import test_catalog


def code(body):
    return body + str(-sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(body[::-1])) % 10)


class BarcodeTests(unittest.TestCase):
    def test_check_digit_leading_zeros_and_gtin_formats(self):
        self.assertEqual(matching.gtin('4006381333931'), '04006381333931')
        for body in ('9638507', '03600029145', '902233752765', '1902233752765'):
            value = code(body)
            self.assertEqual(matching.gtin(value), value.zfill(14))
            self.assertEqual(matching.gtin(value.zfill(14)), value.zfill(14))
        for value in (None, 4006381333931, '00000000', '4006381333932', '4006 381333931', 'a4006381333931'):
            self.assertIsNone(matching.gtin(value))

    def test_restricted_circulation_codes_are_not_global_identity(self):
        for body in ('200123456789', '290123456789', '020123456789', '040123456789', '2001234'):
            self.assertIsNone(matching.gtin(code(body)))

    def test_only_explicit_product_identifiers(self):
        identity = matching.retailer_identity({'sku': '4006381333931', 'id': '4006381333931',
                                              'related': {'ean': '4006381333931'}, 'brand': {'name': 'Example'}})
        self.assertEqual(identity, {'brand': 'Example', 'gtins': []})


class MatchingTests(unittest.TestCase):
    setUp = test_catalog.PersistenceTests.setUp
    tearDown = test_catalog.PersistenceTests.tearDown

    def save(self, store, ident, **kw):
        row = {'store': store, 'id': ident, 'name': 'Coca-Cola Original', 'unit': '500 ml',
               'category': 'Limonaden', 'price': 1.5, **kw}
        app.save_page(store, [row], 'test', 'https://example.com')

    def query(self):
        with app.connect() as db:
            return matching.compare(db, 'spar', 'ref', '2026-10-12', app.STORES)

    def test_no_identity_from_same_name_or_sku(self):
        self.save('spar', 'ref')
        self.save('billa', 'ref')
        result = self.query()
        self.assertEqual(result['exact'], [])
        self.assertIsNone(result['barcode'])
        self.assertEqual(result['similar'][0]['product']['store'], 'billa')
        self.assertEqual(result['similar'][0]['size'], 'same')

    def test_global_code_matches_despite_different_names_and_categories(self):
        self.save('spar', 'ref', ean='4006381333931')
        self.save('billa', 'other', name='Entirely different title', category='Other', gtin='04006381333931')
        result = self.query()
        self.assertEqual(len(result['exact']), 1)
        self.assertEqual(result['exact'][0]['product']['id'], 'other')
        self.assertEqual(result['similar'], [])

    def test_conflicting_size_or_different_code_remains_alternative(self):
        self.save('spar', 'ref', ean='4006381333931')
        self.save('billa', 'big', unit='1 l', ean='4006381333931')
        self.save('penny', 'different', ean=code('902233752765'))
        result = self.query()
        self.assertEqual(result['exact'], [])
        self.assertEqual({e['reason'] for e in result['similar']}, {'size_conflict', 'different_code'})

    def test_assorted_codes_do_not_prove_identical_variant(self):
        self.save('spar', 'ref', ean='4006381333931')
        self.save('billa', 'variants', gtins=['4006381333931', code('902233752765')])
        result = self.query()
        self.assertEqual(result['exact'], [])
        self.assertEqual(len(result['similar']), 1)

    def test_only_active_current_other_stores_and_preserve_price_conditions(self):
        self.save('spar', 'ref')
        self.save('spar', 'same-store')
        self.save('billa', 'old', valid_to='2026-10-11')
        self.save('billa', 'future', valid_from='2026-10-13')
        self.save('billa', 'inactive')
        self.save('penny', 'valid', valid_from='2026-10-12', valid_to='2026-10-12',
                  price=1, single_price=2, conditions=['ab 2 Packungen'], offers=[{'price': .8, 'conditions': ['jö']}])
        with app.connect() as db:
            db.execute("UPDATE products SET active=0 WHERE id='inactive'")
        result = self.query()
        self.assertEqual(len(result['similar']), 1)
        p = result['similar'][0]['product']
        self.assertEqual((p['store'], p['price'], p['single_price']), ('penny', 1, 2))
        self.assertEqual(p['conditions'], ['ab 2 Packungen'])
        self.assertEqual(p['offers'][0]['price'], .8)
        with app.connect() as db:
            db.execute("UPDATE products SET active=0 WHERE id='ref'")
        self.assertFalse(self.query()['reference_current'])

    def test_index_updates_remove_old_barcode_and_name(self):
        self.save('spar', 'ref', ean='4006381333931')
        self.save('billa', 'changed', ean='4006381333931')
        self.assertEqual(len(self.query()['exact']), 1)
        self.save('billa', 'changed', name='Apple Juice', ean=code('902233752765'))
        self.assertEqual(self.query()['exact'], [])
        self.assertEqual(self.query()['similar'], [])
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM product_match_terms WHERE store='billa' AND term='cola'").fetchone()[0], 0)

    def test_existing_catalogue_backfill_keeps_price_check_time(self):
        self.save('spar', 'ref')
        self.save('billa', 'other')
        with app.connect() as db:
            before = db.execute('SELECT checked_at FROM products ORDER BY store,id').fetchall()
            db.execute('DELETE FROM product_match_terms')
            db.execute("DELETE FROM app_meta WHERE key='matching_version'")
        app.initialize()
        with app.connect() as db:
            self.assertEqual(before, db.execute('SELECT checked_at FROM products ORDER BY store,id').fetchall())
        self.assertEqual(len(self.query()['similar']), 1)

    def test_brand_only_is_not_a_similar_product(self):
        self.save('spar', 'ref', name='NÖM PRO Protein Drink', brand='NÖM')
        self.save('billa', 'different', name='NÖM Butter', brand='NÖM')
        self.assertEqual(self.query()['similar'], [])

    def test_missing_product_and_invalid_store(self):
        self.assertIsNone(self.query())
        with app.connect() as db, self.assertRaises(ValueError):
            matching.compare(db, "' OR 1=1 --", 'ref', '2026-10-12', app.STORES)


class ParserIdentityTests(unittest.TestCase):
    def test_rewe_and_spar_keep_explicit_codes_but_not_skus(self):
        p = {'sku': '4006381333931', 'slug': 'example', 'name': 'Example', 'brand': {'name': 'Example'},
             'price': {'regular': {'value': 100}}}
        self.assertEqual(parsers.parse_rewe({'results': [p]}, 'billa')[0]['gtins'], [])
        p['ean'] = '4006381333931'
        for store in ('billa', 'penny'):
            self.assertEqual(parsers.parse_rewe({'results': [p]}, store)[0]['gtins'], ['04006381333931'])
        spar = parsers.parse_spar({'hits': [{'masterValues': {'product-number': '4006381333931',
                                         'price': 1, 'title': 'Example', 'ecr-brand': 'Example'}}]})[0]
        self.assertEqual(spar['gtins'], [])
        self.assertEqual(spar['brand'], 'Example')

    def test_hofer_and_lidl_keep_explicit_identity(self):
        p = {'sku': 'abc', 'name': 'Example', 'brandName': 'Brand', 'price': {'amount': 100}, 'ean': '4006381333931'}
        with patch.object(parsers, 'decode_nuxt', return_value={'data': [p]}):
            parsed = parsers.parse_hofer('')[0]
            self.assertEqual(parsed['gtins'], ['04006381333931'])
            self.assertEqual(parsed['brand'], 'Brand')
        p = {'productId': 123, 'fullTitle': 'Example', 'brand': {'name': 'Brand'},
             'price': {'price': 1}, 'gtin13': '4006381333931'}
        with patch.object(parsers, 'decode_nuxt', return_value={'pinia': {'useProductStore': {'products': [p]}}}):
            self.assertEqual(parsers.parse_lidl('')[0]['gtins'], ['04006381333931'])


if __name__ == '__main__':
    unittest.main()
