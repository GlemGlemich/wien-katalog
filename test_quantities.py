"""Package weights must not be confused with the reference-price denominator."""
import unittest
import test_catalog
import app
from quantities import product_quantity


class QuantityTests(unittest.TestCase):
    def quantity(self, unit, price=2.99, reference=None, **kwargs):
        return product_quantity({'unit':unit,'price':price,'unit_price_text':reference,**kwargs})

    def test_pack_normalization_and_multipacks(self):
        for unit,key,price in [('500 G','kg:500',5.98),('0,5 kg','kg:500',5.98),
                                ('2x250g','kg:500',5.98),('2 × 3 x 100 g','kg:600',2.99/.6),
                                ('1 KG','kg:1000',2.99),('1000 g','kg:1000',2.99),
                                ('250 ml','l:250',11.96),('0.5 liter','l:500',5.98),
                                ('75 cl','l:750',2.99/.75),('Je 12x 0,5 l','l:6000',2.99/6),
                                ('3.000 ML MEHRWEG','l:3000',2.99/3),('0.275 liter','l:275',2.99/.275),
                                ('1.980 ML','l:1980',2.99/1.98)]:
            with self.subTest(unit=unit):
                result=self.quantity(unit)
                self.assertEqual(result['size_key'],key)
                self.assertAlmostEqual(result['unit_price'],price,places=5)

    def test_reference_formats_normalize_100g_and_500ml(self):
        for text,price,measure in [('2.39 € / 100 g',23.9,'kg'),('€ 0,74/500 ml',1.48,'l'),
                                    ('10.90 €/kg',10.9,'kg'),('€\u00a02,63/100g',26.3,'kg'),
                                    ('Je 500 g (1 kg = 5.98)',5.98,'kg'),
                                    ('Je 0,33 l (0,5 l = 1.20)',2.4,'l'),
                                    ('1160.00 € / 1 Liter',1160,'l'),('€ 1.160,00/1 l',1160,'l')]:
            with self.subTest(text=text):
                result=self.quantity('',reference=text)
                self.assertEqual(result['unit_price'],price)
                self.assertEqual(result['measure'],measure)
                self.assertEqual(result['source'],'retailer')

    def test_drained_reference_does_not_invent_package_weight(self):
        result=self.quantity('140 g',1.49,'22.92 € / 1 kg')
        self.assertEqual((result['unit_price'],result['size_key']),(22.92,'kg:140'))
        result=self.quantity('Je 425 ml',.49,'Bei 12 Stk. je 425 ml (1 kg Abtr. G. = 1.53)')
        self.assertEqual((result['unit_price'],result['measure'],result['size_key']),(1.53,'kg','l:425'))

    def test_bulk_condition_does_not_multiply_or_halve_pack(self):
        result=self.quantity('Bei 2 Stk. je 600 g',2.14,'Bei 2 Stk. je 600 g (1 kg = 3.57)',conditions=['1+1 gratis'])
        self.assertEqual((result['unit_price'],result['size_key']),(3.57,'kg:600'))

    def test_variable_weight_is_not_an_exact_pack(self):
        for unit,kwargs in [('1 KG',{'conditions':['Весовой товар; цена за указанное количество']}),
                             ('0.5 kg',{'is_variable_weight':True}),('ca. 1kg',{}),('ungefähr 1 kg/Stück',{})]:
            with self.subTest(unit=unit):
                result=self.quantity(unit,reference='10.90 €/kg',**kwargs)
                self.assertEqual(result['size_key'],'variable')
                self.assertEqual(result['unit_price'],10.9)
        result=self.quantity('Je kg',9.99)
        self.assertEqual((result['size_key'],result['unit_price']),('variable',9.99))
        self.assertIsNone(self.quantity('ungefähr 1 kg/Stück',9.99)['unit_price'])

    def test_unknown_ranges_non_weight_units_and_conflicting_prices(self):
        for unit in ('Je 120/150 g','Je 240 - 300 g / 400 ml','2x320/355 g','250 g + 50 g','6 Stück','30 x 18 x 5 cm',''):
            with self.subTest(unit=unit):
                result=self.quantity(unit)
                self.assertEqual(result['size_key'],'unknown')
                self.assertIsNone(result['unit_price'])
        self.assertIsNone(self.quantity('500 g',reference='1 kg = 5.98 / 6.98')['unit_price'])
        self.assertIsNone(self.quantity('500 g',reference='1 kg = 5.98; 1 kg = 6.98')['unit_price'])


class QuantityFilterTests(unittest.TestCase):
    tearDown=test_catalog.PersistenceTests.tearDown
    row=test_catalog.PersistenceTests.row

    def setUp(self):
        test_catalog.PersistenceTests.setUp(self)
        app.save_page('spar',[
            self.row('small',name='Hühnerfilet',category='Fleisch',unit='250 g',price=2.5),
            self.row('large',name='Hühnerfilet',category='Fleisch',unit='1 kg',price=6,regular_price=8),
            self.row('half',name='Hühnerfilet',category='Fleisch',unit='500 g',price=4),
            self.row('loose',name='Hühnerfilet',category='Fleisch',unit='1 kg',price=5,conditions=['Весовой товар'],unit_price_text='5.00 €/kg'),
            self.row('unknown',name='Hühnerfilet',category='Fleisch',price=1),
            self.row('milk',name='Laktosefreie Vollmilch',category='Milch',unit='1 liter',price=1.2),
            self.row('expired',name='Hühnerfilet',category='Fleisch',unit='1 kg',price=3,valid_to='2000-01-01'),
        ],'a','https://www.spar.at')

    def test_unit_sort_differs_from_package_sort_and_never_mixes_volume(self):
        result=app.products({'price_basis':['kg'],'sort':['price_asc']})
        self.assertEqual([r['id'] for r in result['items']],['loose','large','half','small'])
        result=app.products({'price_basis':['kg'],'sort':['price_desc']})
        self.assertEqual([r['id'] for r in result['items']],['small','half','large','loose'])
        self.assertEqual(app.products({'price_basis':['l']})['items'][0]['id'],'milk')
        self.assertEqual(app.products({'sort':['price_asc']})['items'][0]['id'],'unknown')

    def test_size_with_category_details_discount_and_period(self):
        params={'price_basis':['kg'],'package_size':['kg:1000'],'selection':['meat'],'meat_kind':['chicken']}
        result=app.products(params)
        self.assertEqual([r['id'] for r in result['items']],['large'])
        self.assertEqual({s['id']:s['count'] for s in result['sizes']}['kg:500'],1)
        self.assertEqual(app.products({**params,'discount':['1']})['total'],1)
        self.assertEqual(app.products({**params,'store':['billa']})['total'],0)
        self.assertEqual(app.products({**params,'q':['unknown']})['total'],0)
        self.assertEqual(app.products({'category':['meat'],'package_size':['kg:500']})['total'],1)
        self.assertEqual(app.products({'package_size':['unknown']})['total'],1)
        self.assertEqual(app.products({'package_size':['variable']})['total'],1)
        self.assertEqual(app.products({'package_size':['kg:1000'],'period':['all']})['total'],2)
        self.assertEqual(app.products({'selection':['milk'],'milk_lactose':['free'],'price_basis':['l'],'package_size':['l:1000']})['total'],1)
        for params in ({'price_basis':['oz']},{'package_size':["kg:500 OR 1=1"]}):
            with self.assertRaises(ValueError):app.products(params)

    def test_existing_prices_migrate_and_refresh_replaces_size(self):
        before=app.products({'package_size':['kg:1000']})['items'][0]
        with app.connect() as db:
            db.execute("UPDATE products SET quantity='{}'")
            db.execute("DELETE FROM app_meta WHERE key='quantity_version'")
        app.initialize()
        self.assertEqual(app.products({'package_size':['kg:1000']})['items'][0],before)
        app.save_page('spar',[self.row('large',name='Hühnerfilet',unit='750 g',price=6)],'b','https://www.spar.at')
        self.assertEqual(app.products({'package_size':['kg:1000']})['total'],0)
        self.assertEqual(app.products({'package_size':['kg:750']})['items'][0]['quantity']['unit_price'],8)

    def test_comparison_uses_all_stores_current_prices_and_matching_filters(self):
        app.save_page('billa',[{**self.row('billa-half',name='Hühnerfilet',category='Fleisch',unit='500 g',price=2),'store':'billa'},
                               {**self.row('billa-expired',name='Hühnerfilet',category='Fleisch',unit='500 g',price=1,valid_to='2000-01-01'),'store':'billa'}],
                      'a','https://www.billa.at')
        params={'store':['spar'],'selection':['meat'],'meat_kind':['chicken'],'price_basis':['kg'],'period':['all']}
        result=app.products(params,comparison=True)
        self.assertEqual(len(result['stores']),5)
        self.assertEqual(result['lowest'],4)
        self.assertEqual(result['stores'][0]['store'],'billa')
        self.assertEqual(result['stores'][0]['product']['id'],'billa-half')
        self.assertEqual(result['stores'][0]['count'],1)
        self.assertEqual(result['stores'][1]['store'],'spar')
        self.assertEqual(result['stores'][1]['difference'],1)
        self.assertFalse(result['stores'][1]['best'])
        self.assertTrue(all(r['product'] is None for r in result['stores'][2:]))
        result=app.products({**params,'package_size':['kg:1000']},comparison=True)
        self.assertEqual(result['stores'][0]['product']['id'],'large')
        self.assertEqual(result['lowest'],6)
        result=app.products({**params,'discount':['1']},comparison=True)
        self.assertEqual(result['stores'][0]['product']['id'],'large')
        result=app.products({**params,'q':['Not found']},comparison=True)
        self.assertIsNone(result['lowest'])
        self.assertTrue(all(not r['best'] for r in result['stores']))
        with self.assertRaises(ValueError):app.products({},comparison=True)


if __name__=='__main__':unittest.main()
