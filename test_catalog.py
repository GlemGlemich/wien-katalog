"""Offline regression checks for prices, time boundaries, and safe partial imports."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from categories import classify
from selections import selection_flags, product_details
from parsers import parse_rewe, parse_spar, _vienna_date
from datetime import datetime


class PriceTests(unittest.TestCase):
    def test_bulk_and_loyalty_do_not_replace_single_price(self):
        product = {'sku': '1', 'name': 'Eier', 'slug': 'eier-1', 'amount': '6', 'volumeLabelShort': 'Stk',
                   'price': {'regular': {'value': 299, 'promotionQuantity': 2, 'promotionText': 'ab 2 Packungen'},
                             'standard': {'value': 399}, 'lowestPrice': 199, 'loyalty': {'value': 279}}}
        row = parse_rewe({'results': [product]}, 'billa')[0]
        self.assertEqual((row['price'], row['single_price'], row['regular_price']), (2.99, 3.99, 3.99))
        self.assertEqual(row['conditions'], ['ab 2 Packungen'])
        self.assertEqual(row['offers'][0]['price'], 2.79)
        self.assertIn('jö', row['offers'][0]['conditions'][0])

    def test_thirty_day_low_is_not_regular_price(self):
        row = parse_rewe({'results': [{'sku': '1', 'slug': 'test', 'name': 'Test', 'price': {'regular': {'value': 149}, 'lowestPrice': 299}}]}, 'penny')[0]
        self.assertIsNone(row['regular_price'])

    def test_spar_weight_price_uses_stated_quantity(self):
        row = parse_spar({'hits': [{'masterValues': {'product-number': '1', 'price': 1.09, 'best-price': 10.9,
                           'regular-price': 1.59, 'short-description-2': 'Schinken', 'short-description-3': '100 G',
                           'item-type': 'WeightProduct', 'price-per-unit': '10.90 €/kg'}}]})[0]
        self.assertEqual(row['price'], 1.09)
        self.assertEqual(row['unit'], '100 G')

    def test_vienna_date_crosses_midnight(self):
        self.assertEqual(_vienna_date(datetime.fromisoformat('2026-10-01T22:30:00+00:00').timestamp()), '2026-10-02')


class CategoryTests(unittest.TestCase):
    def test_selected_foods_exclude_pets_cosmetics_and_alcohol(self):
        cases = [
            ('Coca-Cola Zero', 'Limonaden', 1),
            ('Rauch Happy Day', 'Säfte', 1),
            ('High Protein Pudding', 'Desserts', 2),
            ('Eiweißbrot', 'Brot', 2),
            ('Proteinwasser Energy', 'Softdrinks', 3),
            ('ZooRoyal Mono-Protein Pastete Huhn', 'Nassfutter', 0),
            ('Protein Shampoo', 'Haarpflege', 0),
            ('Haribo Happy Cola', 'Fruchtgummi', 0),
            ('Coca-Cola Rum Cocktail', 'Getränke', 16),
            ('Mineralwasser still', 'Mineralwasser', 0),
            ('Milch', 'Milch', 4),
        ]
        for name, category, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(selection_flags({'name':name,'category':category}),expected)

    def test_retailer_categories_and_ingredient_ambiguity(self):
        cases = [
            ('Coca-Cola', 'Limonaden', 'drinks'),
            ('Sodawasser', 'prickelnd', 'drinks'),
            ('Milchschokolade', 'Tafelschokolade', 'sweets'),
            ('Schokomilch', 'Milchprodukte, Milch und Milchgetränke', 'dairy'),
            ('Erdbeer Shampoo', 'Haare · Beauty · Shampoo', 'other'),
            ('ZooRoyal Fleischstick Rind', 'Snacks', 'other'),
            ('Sonnenblumenöl', '', 'pantry'),
            ('Germ', 'Backpulver, Hefe & Natron', 'pantry'),
            ('Schinken Gratin Basis', 'Basis- & Fixprodukte', 'pantry'),
            ('Gurkensalat', 'Gemüse & Salate', 'produce'),
            ('Käsekrainer', '', 'meat'),
            ('Chicken Nuggets', '', 'prepared'),
            ('Grammelknödel', 'Pikante & Süße Knödel', 'prepared'),
            ('Kürbiscremesuppe', 'Beutel', 'prepared'),
            ('Unbekannter Artikel', '', 'other'),
        ]
        for name, category, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(classify({'name': name, 'category': category}), expected)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(app, 'DB', Path(self.tmp.name) / 'test.sqlite3')
        self.patch.start()
        app.initialize()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def row(self, ident='1', price=1.99, **kw):
        return {'store': 'spar', 'id': ident, 'name': 'Milch', 'price': price, **kw}

    def test_idempotency_and_update(self):
        app.save_page('spar', [self.row()], 'a', 'https://www.spar.at')
        app.save_page('spar', [self.row(price=2.39)], 'b', 'https://www.spar.at')
        found = app.products({})
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['items'][0]['price'], 2.39)

    def test_failed_import_preserves_older_products(self):
        app.save_page('spar', [self.row('old')], 'a', 'https://www.spar.at')
        def broken(_):
            yield [self.row('new')], {'new'}, 3, 'Page 1', 'https://www.spar.at'
            raise ValueError('Failed source')
        with patch.object(app, 'pages', broken):
            app.import_store('spar')
        self.assertEqual(app.products({})['total'], 2)
        self.assertEqual(app.state()['stores'][0]['status'], 'error')

    def test_complete_import_hides_missing_products(self):
        app.save_page('spar', [self.row('old')], 'a', 'https://www.spar.at')
        with patch.object(app, 'pages', lambda _: iter([([self.row('new')], {'new'}, 1, 'Page 1', 'https://www.spar.at')])):
            app.import_store('spar')
        self.assertEqual(app.products({})['total'], 1)
        self.assertEqual(app.products({})['items'][0]['id'], 'new')

    def test_dates_filter_and_sql_inputs(self):
        app.save_page('spar', [self.row('old', valid_to='2000-01-01'), self.row('future', valid_from='2099-01-01'), self.row('current')], 'a', 'https://www.spar.at')
        self.assertEqual(app.products({})['total'], 1)
        self.assertEqual(app.products({'period': ['all']})['total'], 3)
        self.assertEqual(app.products({'q': ["' OR 1=1 --"]})['total'], 0)
        self.assertEqual(app.products({'q': ['%']})['total'], 0)

    def test_category_filter_combines_with_search_and_period(self):
        app.save_page('spar', [self.row('milk', category='Milch'),
                              self.row('chocolate', category='Tafelschokolade'),
                              self.row('future', category='Milch', valid_from='2099-01-01')], 'a', 'https://www.spar.at')
        result = app.products({'store': ['spar'], 'category': ['dairy'], 'q': ['Milch']})
        self.assertEqual([row['id'] for row in result['items']], ['milk'])
        counts = {c['id']: c['count'] for c in result['categories']}
        self.assertEqual((counts['all'], counts['dairy'], counts['sweets']), (2, 1, 1))
        self.assertEqual(app.products({'category': ['dairy'], 'period': ['all']})['total'], 2)
        self.assertEqual(app.products({'category': ['meat']})['total'], 0)

    def test_discount_filter_includes_lower_member_and_bulk_prices(self):
        rows = [self.row('plain', category='Milch', conditions=['Pfand: 0.25']),
                self.row('sale', category='Milch', regular_price=2.99),
                self.row('bulk', category='Milch', single_price=2.49),
                self.row('member', category='Milch', offers=[{'price': 1.49, 'conditions': ['С картой']}]),
                self.row('equal', category='Milch', regular_price=1.99, offers=[{'price': 1.99}]),
                self.row('future', category='Milch', regular_price=2.99, valid_from='2099-01-01'),
                self.row('sweets', category='Tafelschokolade', regular_price=2.99)]
        app.save_page('spar', rows, 'a', 'https://www.spar.at')
        result = app.products({'discount': ['1'], 'store': ['spar'], 'category': ['dairy'], 'q': ['Milch']})
        self.assertEqual({r['id'] for r in result['items']}, {'sale', 'bulk', 'member'})
        self.assertEqual({c['id']: c['count'] for c in result['categories']}['all'], 4)
        self.assertEqual(app.products({'discount': ['1'], 'period': ['future']})['total'], 1)
        self.assertEqual(app.products({'discount': ['1'], 'store': ['billa']})['total'], 0)
        self.assertEqual(app.products({'discount': ['0']})['total'], 6)

    def test_selections_are_current_and_combine_with_discount_and_store(self):
        app.save_page('spar', [self.row('cola', name='Cola Zero', category='Limonaden', regular_price=2.99),
                              self.row('juice', name='Apfelsaft', category='Säfte'),
                              self.row('protein', name='Protein Pudding', category='Desserts'),
                              self.row('old', name='Cola', category='Limonaden', valid_to='2000-01-01'),
                              self.row('future', name='Cola', category='Limonaden', valid_from='2099-01-01')],
                      'a','https://www.spar.at')
        result=app.products({'selection':['sweet_drinks'],'period':['all'],'category':['dairy']})
        self.assertEqual({r['id'] for r in result['items']},{'cola','juice'})
        self.assertEqual([(s['count'],s['discount_count']) for s in result['selections']],[(2,1),(1,0),(0,0),(0,0),(0,0)])
        result=app.products({'selection':['sweet_drinks'],'discount':['1'],'store':['spar'],'q':['Cola']})
        self.assertEqual([r['id'] for r in result['items']],['cola'])
        self.assertEqual(app.products({'selection':['protein'],'store':['billa']})['total'],0)
        app.save_page('spar',[self.row('protein',name='Vanille Pudding',category='Desserts')],'b','https://www.spar.at')
        self.assertEqual(app.products({'selection':['protein']})['total'],0)

    def test_selection_migration_preserves_price_and_check_time(self):
        app.save_page('spar',[self.row('protein',name='Protein Riegel',category='Riegel')],'a','https://www.spar.at')
        before=app.products({})['items'][0]
        with app.connect() as db:
            db.execute('UPDATE products SET selection_flags=0')
            db.execute("DELETE FROM app_meta WHERE key='selection_version'")
        app.initialize()
        after=app.products({'selection':['protein']})['items'][0]
        self.assertEqual((after['price'],after['checked_at']),(before['price'],before['checked_at']))

    def test_migration_classifies_existing_rows_and_preserves_price(self):
        app.save_page('spar', [self.row('drink', category='Limonaden')], 'a', 'https://www.spar.at')
        with app.connect() as db:
            db.execute("UPDATE products SET group_id='other'")
            db.execute("DELETE FROM app_meta WHERE key='category_version'")
        app.initialize()
        result = app.products({'category': ['drinks']})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['price'], 1.99)


if __name__ == '__main__':
    unittest.main()
