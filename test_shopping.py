"""Offline tests for complete baskets, whole packs and conditional prices."""
import json
import unittest
from decimal import Decimal

import app
import shopping
from quantities import product_quantity
import test_catalog


class BasketTests(unittest.TestCase):
    setUp = test_catalog.PersistenceTests.setUp
    tearDown = test_catalog.PersistenceTests.tearDown

    def save(self, store, ident, name, price, unit, **kwargs):
        app.save_page(store, [{'store': store, 'id': ident, 'name': name, 'price': price,
                              'unit': unit, 'url': 'https://example.com/product', **kwargs}], 'test', 'https://example.com')

    def item(self, query='milk', amount=1, unit='l', ident='1', **kwargs):
        return {'id': ident, 'query': query, 'amount': amount, 'unit': unit, **kwargs}

    def basket(self, items):
        with app.connect() as db:
            return shopping.calculate(db, items, '2026-10-10')

    def test_best_pair_assigns_each_line_and_never_counts_missing_as_zero(self):
        self.save('spar', 'milk', 'Vollmilch', 1, '1 l')
        self.save('spar', 'eggs', 'Freilandeier', 5, '10 Stück', category='Eier')
        self.save('billa', 'milk', 'Vollmilch', 3, '1 l')
        self.save('billa', 'eggs', 'Freilandeier', 2, '10 Stück', category='Eier')
        self.save('hofer', 'milk', 'Vollmilch', .9, '1 l')
        result = self.basket([self.item(), self.item('eggs', 10, 'pcs', '2')])
        self.assertEqual(result['best_single']['total_cents'], 500)
        self.assertEqual(result['best_two']['total_cents'], 290)
        self.assertEqual(result['best_two']['used_stores'], ['billa', 'hofer'])
        self.assertEqual(result['saving_cents'], 210)
        hofer = next(p for p in result['stores'] if p['stores'] == ['hofer'])
        self.assertIsNone(hofer['total_cents'])
        self.assertEqual((hofer['covered'], hofer['subtotal_cents']), (1, 90))

    def test_missing_line_prevents_full_total_and_recommendation(self):
        self.save('spar', 'milk', 'Vollmilch', 1, '1 l')
        result = self.basket([self.item(), self.item('absent-product', ident='2')])
        self.assertIsNone(result['best_single'])
        self.assertIsNone(result['best_two'])
        self.assertIsNone(result['saving_cents'])
        self.assertTrue(all(not plan['complete'] for plan in result['stores']))

    def test_two_stores_can_complete_list_when_no_single_store_can(self):
        self.save('spar', 'milk', 'Vollmilch', 1, '1 l')
        self.save('billa', 'eggs', 'Eier', 2, '10 Stück', category='Eier')
        result = self.basket([self.item(), self.item('eggs', 10, 'pcs', '2')])
        self.assertIsNone(result['best_single'])
        self.assertEqual(result['best_two']['total_cents'], 300)
        self.assertIsNone(result['saving_cents'])

    def test_second_store_is_not_required_when_it_cannot_save_money(self):
        self.save('spar', 'milk', 'Vollmilch', 1, '1 l')
        result = self.basket([self.item()])
        self.assertEqual(result['best_two']['used_stores'], ['spar'])
        self.assertEqual(result['saving_cents'], 0)

    def test_whole_packs_and_actual_cost_take_priority_over_unit_price(self):
        self.save('spar', 'small', 'Vollmilch', .8, '500 ml')
        self.save('spar', 'large', 'Vollmilch', 1.5, '1 l')
        result = self.basket([self.item(amount=.5)])
        choice = result['best_single']['lines'][0]['choice']
        self.assertEqual((choice['id'], choice['packs'], choice['cost_cents']), ('small', 1, 80))
        self.save('billa', 'eggs', 'Eier', 1.5, '6 Stück', category='Eier')
        result = self.basket([self.item('яйца', 10, 'pcs')])
        choice = result['best_single']['lines'][0]['choice']
        self.assertEqual((choice['bought'], choice['packs'], choice['cost_cents']), (12, 2, 300))

    def test_current_active_only_and_exact_product_stays_in_its_store(self):
        for ident, kwargs in [('old', {'valid_to': '2026-10-09'}), ('future', {'valid_from': '2026-10-11'}), ('inactive', {})]:
            self.save('spar', ident, 'Vollmilch', .2, '1 l', **kwargs)
        with app.connect() as db:
            db.execute("UPDATE products SET active=0 WHERE id='inactive'")
        self.save('billa', 'current', 'Vollmilch', 2, '1 l')
        self.assertEqual(self.basket([self.item()])['best_single']['total_cents'], 200)
        exact = self.item(product={'store': 'spar', 'id': 'current'})
        self.assertIsNone(self.basket([exact])['best_single'])
        exact['product']['store'] = 'billa'
        self.assertEqual(self.basket([exact])['best_single']['used_stores'], ['billa'])

    def test_generic_food_does_not_match_chocolate_or_egg_salad(self):
        self.save('spar', 'choc', 'Milchschokolade', .1, '1 l', category='Schokolade')
        self.save('spar', 'salad', 'Eiersalat', .1, '10 Stück', category='Molkerei')
        self.save('spar', 'milk', 'Vollmilch', 1, '1 l')
        self.save('spar', 'eggs', 'Freilandeier', 2, '10 Stück', category='Eier')
        result = self.basket([self.item('молоко'), self.item('яйца', 10, 'pcs', '2')])
        self.assertEqual(result['best_single']['total_cents'], 300)

    def test_unknown_prices_are_reported_as_excluded(self):
        self.save('spar', 'milk', 'Vollmilch', .5, '120/150 ml')
        result = self.basket([self.item()])
        self.assertEqual((result['items'][0]['matched'], result['items'][0]['excluded']), (1, 1))
        self.assertIsNone(result['best_single'])

    def test_validation_and_literal_search(self):
        for items in ([], [self.item(amount=-1)], [self.item(amount=True)], [self.item(amount=float('nan'))],
                      [self.item(unit='usd')], [self.item(unit='pcs', amount=1.5)],
                      [self.item(), self.item()], [self.item(product={'store': 'invalid', 'id': 'x'})],
                      [self.item(ident=str(i)) for i in range(31)]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                self.basket(items)
        self.save('spar', 'milk', 'Vollmilch', 1, '1 l')
        self.assertIsNone(self.basket([self.item("%' OR 1=1 --")])['best_single'])


class ShoppingPriceTests(unittest.TestCase):
    def quote(self, unit='1 l', amount=1, wanted='l', **kwargs):
        product = {'id': 'x', 'store': 'spar', 'name': 'Test', 'unit': unit, 'price': 1.99, **kwargs}
        return shopping.quote(product, product_quantity(product), '2026-10-10T12:00:00Z',
                              {'amount': amount, 'unit': wanted})

    def test_multipack_discount_not_applied_twice(self):
        value = self.quote(amount=3, price=.99, single_price=1.98, conditions=['1+1 gratis'])
        self.assertEqual((value['packs'], value['cost_cents'], value['single_price']), (4, 396, False))
        value = self.quote(amount=1, price=1, single_price=1.5, conditions=['ab 2 Stück'])
        self.assertEqual((value['packs'], value['cost_cents'], value['single_price']), (1, 150, True))

    def test_minimum_quantity_and_multipack_size(self):
        value = self.quote(unit='6 x 500 ml', amount=4, price=4)
        self.assertEqual((value['packs'], value['bought'], value['cost_cents']), (2, 6, 800))
        value = self.quote(amount=1, price=.99, conditions=['От 6 шт., цена за одну'])
        self.assertEqual((value['packs'], value['bought'], value['cost_cents']), (6, 6, 594))

    def test_unknown_conditions_and_loyalty_are_not_assumed(self):
        self.assertIsNone(self.quote(conditions=['mit Coupon']))
        self.assertIsNone(self.quote(membership_required=True))
        self.assertIsNone(self.quote(conditions=['ab 20 Euro Einkaufswert']))
        self.assertEqual(self.quote(single_price=3)['cost_cents'], 300)

    def test_single_price_can_replace_unknown_bulk_rule(self):
        value = self.quote(conditions=['Sortiment kombinieren'], single_price=3)
        self.assertEqual((value['cost_cents'], value['single_price']), (300, True))

    def test_variable_weights_cents_and_no_deposit(self):
        value = self.quote(unit='je kg', wanted='kg', amount=.333, price=9.99)
        self.assertEqual((value['cost_cents'], value['packs'], value['bought']), (333, None, .333))
        self.assertIsNone(self.quote(unit='je kg', wanted='pack'))
        self.assertEqual(self.quote(conditions=['+ Pfand 0.25 €'])['cost_cents'], 199)

    def test_reference_price_does_not_replace_pack_checkout_price(self):
        value = self.quote(unit='140 g', wanted='kg', amount=.14, price=1.49, unit_price_text='22.92 €/kg')
        self.assertEqual(value['cost_cents'], 149)


if __name__ == '__main__':
    unittest.main()
