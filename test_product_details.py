"""Milk/meat labels, intersecting filters and existing-catalog migration."""
import unittest
from selections import product_details
import test_catalog
import app


class DetailTests(unittest.TestCase):
    def details(self, name, category=''):
        return product_details({'name':name,'category':category})

    def test_lactose_and_fat_are_independent(self):
        self.assertEqual(self.details('Minus-L H-Vollmilch 3,5%', 'Milch'),
                         {'milk_kind':'plain','milk_lactose':'free','milk_fat':'whole','milk_storage':'uht'})
        self.assertEqual(self.details('Frische Leichtmilch 1,5%')['milk_storage'],'fresh')
        self.assertEqual(self.details('Vollmilch länger frisch')['milk_storage'],'esl')
        self.assertEqual(self.details('H-Milch 0,1%')['milk_fat'],'skim')
        self.assertEqual(self.details('Vollmilch')['milk_lactose'],'unmarked')

    def test_plant_and_flavoured_milk(self):
        for name in ('Haferdrink','Kokosnussmilch','Alpro Not M*lk'):
            with self.subTest(name=name):
                details=self.details(name)
                self.assertEqual(details['milk_kind'],'plant')
                self.assertEqual(details['milk_fat'],'not_applicable')
        self.assertEqual(self.details('Kakaomilch')['milk_kind'],'flavoured')

    def test_milk_ingredients_do_not_make_milk(self):
        for name,category in [('Cremeseife Mandelmilch',''),('Cremeseife Milch & Honig',''),
                              ('Vollmilch Schokolade',''),('Milchpulver','Babynahrung'),
                              ('SalzburgMilch Käse','Milchprodukte'),('Milchreis','Dessert')]:
            with self.subTest(name=name):
                self.assertNotIn('milk_kind',self.details(name,category))

    def test_meat_species_forms_and_unknowns(self):
        for name,kind,form in [('Hühnerbrustfilet','chicken','cuts'),('Schweineschnitzel','pork','cuts'),
                                ('Rinderfaschiertes','beef','minced'),('Putenbrust','turkey','cuts'),
                                ('Faschiertes gemischt','mixed','minced'),('Wildschweingulasch','game','cuts'),
                                ('Räucherlachs','fish','processed'),('Kalbsschnitzel','veal','cuts'),
                                ('Salami','unknown','processed')]:
            with self.subTest(name=name):
                details=self.details(name,'Wurst, Fleisch & Fisch')
                self.assertEqual((details['meat_kind'],details['meat_form']),(kind,form))

    def test_non_meat_and_flavours_are_excluded(self):
        for name,category in [('Vegane Chicken Nuggets','Fertiggerichte'),('Eiermuschelsuppe','Beutel'),
                              ('Instant Noodles Chicken Taste','Fertiggerichte'),('ZooRoyal Huhn','Nassfutter'),
                              ('Rindfleisch Zubereitung','Babynahrung · Mit Fleisch & Fisch')]:
            with self.subTest(name=name):
                self.assertNotIn('meat_kind',self.details(name,category))


class FacetTests(unittest.TestCase):
    tearDown = test_catalog.PersistenceTests.tearDown
    row = test_catalog.PersistenceTests.row

    def setUp(self):
        test_catalog.PersistenceTests.setUp(self)
        app.save_page('spar',[
            self.row('lf',name='Laktosefreie H-Vollmilch 3,5%',category='Milch',regular_price=2.99),
            self.row('light',name='Laktosefreie Leichtmilch 1,5%',category='Milch'),
            self.row('whole',name='Vollmilch frisch 3,5%',category='Milch'),
            self.row('plant',name='Haferdrink',category='Milchalternativen'),
            self.row('old',name='Laktosefreie Vollmilch',category='Milch',valid_to='2000-01-01'),
            self.row('chicken',name='Hühnerbrustfilet',category='Fleisch'),
            self.row('pork',name='Schweineschnitzel',category='Fleisch')], 'a','https://www.spar.at')

    def test_intersection_counts_dates_and_discounts(self):
        params={'selection':['milk'],'milk_lactose':['free'],'milk_fat':['whole']}
        data=app.products(params)
        self.assertEqual([r['id'] for r in data['items']],['lf'])
        fat=next(f for f in data['facets'] if f['id']=='milk_fat')
        self.assertEqual({o['id']:o['count'] for o in fat['options']}['light'],1)
        self.assertEqual(app.products({**params,'discount':['1']})['total'],1)
        self.assertEqual(app.products({**params,'store':['billa']})['total'],0)
        self.assertEqual(app.products({**params,'q':['Missing']})['total'],0)
        self.assertEqual(app.products({**params,'period':['all']})['total'],1)
        self.assertEqual(app.products({'category':['dairy'],'milk_fat':['whole']})['total'],2)
        self.assertEqual(app.products({'selection':['meat'],'meat_kind':['chicken'],'meat_form':['cuts']})['total'],1)
        self.assertFalse(app.products({'selection':['protein']})['facets'])
        with self.assertRaises(ValueError):
            app.products({'selection':['milk'],'milk_fat':["' OR 1=1"]})

    def test_migration_and_reimport_replace_details(self):
        before=app.products({'selection':['milk'],'milk_lactose':['free']})['items']
        with app.connect() as db:
            db.execute("UPDATE products SET details='{}',selection_flags=0")
            db.execute("UPDATE app_meta SET value='1' WHERE key='selection_version'")
        app.initialize()
        self.assertEqual(app.products({'selection':['milk'],'milk_lactose':['free']})['items'],before)
        app.save_page('spar',[self.row('lf',name='Leichtmilch 1,5%',category='Milch')],'b','https://www.spar.at')
        self.assertEqual(app.products({'selection':['milk'],'milk_lactose':['free'],'milk_fat':['whole']})['total'],0)


if __name__=='__main__':
    unittest.main()
