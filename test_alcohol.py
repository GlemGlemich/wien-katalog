import unittest
import app
import test_catalog
from categories import classify, alcohol_kind
from selections import product_details, selection_flags


class AlcoholTests(unittest.TestCase):
    def test_weight_products_with_alcohol_names_are_not_drinks(self):
        for name,category,unit in [('Baumkuchenspitzen Jamaica Rum','Weihnachten','150 g'),
                                    ('Glühwein-Fix','Früchtetee','12 G'),
                                    ('Blue Farm Matcha Oat Latte Pulver','Dosenbier','200 g')]:
            self.assertIsNone(alcohol_kind({'name':name,'category':category,'unit':unit}))

    def test_types_and_retailer_parent_categories(self):
        for name,category,kind in [
            ('Gösser Märzen','Flaschenbier','beer'),('Strongbow Cider','Bier & Cider','beer'),
            ('Grüner Veltliner','Weißwein','wine'),('Spumante','Sekt & Champagner','sparkling'),
            ('Hennessy Very Special','Cognac & Whiskey','spirits'),('Gin Tonic','Cocktails','mixed'),
            ('Blaufränkisch','Bedürfniswelten/Wein, Bier und Spirituosen/Wein/Rotwein','wine'),
            ('Weißwein','Produkte · Getränke · Weißwein · Wein & Schaumwein','wine'),
            ('Whisky','Produkte · Getränke · Whisky/Whiskey · Spirituosen','spirits'),
            ('Pfaffl Grüner Veltliner Reserve Hund','Getränke · Weißwein · Wein & Schaumwein','wine'),
        ]:
            with self.subTest(name=name):
                p={'name':name,'category':category}
                self.assertEqual(classify(p),'alcohol')
                self.assertEqual(product_details(p)['alcohol_kind'],kind)
                self.assertEqual(selection_flags(p),16)

    def test_non_alcohol_food_and_household_exclusions(self):
        for name,category in [
            ('Heineken 0,0','Bier'),('Henkell Sekt Alkoholfrei','Sekt'),
            ('Martini Floreale','Alkoholfreie Spirituosen'),('Chardonnay entalkoholisiert','Weißwein'),
            ('Rum Rosinen Schokolade','Schokolade'),('Rum Aroma','Backzutaten'),
            ('Rotweinessig','Essig'),('Weinviertler Erdäpfel','Kartoffeln'),
            ('Gin Tonic Gläser','Haushalt'),('Schweinefleisch','Fleisch'),
            ('Coca-Cola Zero','Limonaden'),('Ginger Beer','Limonaden'),
            ('Ottakringer Germ','Backzutaten'),('Joghurt Eierlikör','Fruchtjoghurt'),
            ('Rum Schokoriegel','Balkan'),('Edelmarzipan-Riegel Rum Traube','Weihnachten'),
            ('SPAR Frucht-Cocktail','Obst'),('Helles Dinkelkrusterl','Brot und Backwaren'),
            ('Whiskas Sticks','Snacks'),('Schweppes Virgin Orange Spritz','Tonic & Bitter Getränke'),
        ]:
            with self.subTest(name=name):
                p={'name':name,'category':category}
                self.assertIsNone(alcohol_kind(p))
                self.assertNotEqual(classify(p),'alcohol')
                self.assertFalse(selection_flags(p)&16)


class AlcoholFilterTests(unittest.TestCase):
    tearDown=test_catalog.PersistenceTests.tearDown
    row=test_catalog.PersistenceTests.row
    def setUp(self):
        test_catalog.PersistenceTests.setUp(self)
        app.save_page('spar',[
            self.row('beer',name='Gösser Märzen',category='Bier',unit='0.5 liter',regular_price=2.5),
            self.row('wine',name='Grüner Veltliner',category='Weißwein',unit='0.75 liter'),
            self.row('free',name='Gösser alkoholfrei',category='Bier',unit='0.5 liter'),
            self.row('old',name='Gösser Märzen',category='Bier',unit='0.5 liter',valid_to='2000-01-01'),
        ],'a','https://www.spar.at')

    def test_filters_and_comparison(self):
        self.assertEqual(app.products({'category':['alcohol']})['total'],2)
        self.assertEqual(app.products({'selection':['alcohol']})['total'],2)
        result=app.products({'category':['alcohol'],'alcohol_kind':['beer'],'price_basis':['l'],'package_size':['l:500'],'discount':['1']})
        self.assertEqual([p['id'] for p in result['items']],['beer'])
        self.assertEqual(result['items'][0]['quantity']['unit_price'],3.98)
        self.assertEqual(app.products({'category':['drinks']})['items'][0]['id'],'free')
        result=app.products({'selection':['alcohol'],'alcohol_kind':['beer'],'price_basis':['l']},comparison=True)
        self.assertEqual(result['stores'][0]['product']['id'],'beer')
        self.assertEqual(result['total'],1)

    def test_migration_preserves_price_and_check_time(self):
        before=app.products({'category':['alcohol'],'alcohol_kind':['wine']})['items'][0]
        with app.connect() as db:
            db.execute("UPDATE products SET group_id='drinks',selection_flags=0,details='{}'")
            db.execute("DELETE FROM app_meta WHERE key IN ('category_version','selection_version')")
        app.initialize()
        self.assertEqual(app.products({'selection':['alcohol'],'alcohol_kind':['wine']})['items'][0],before)


if __name__=='__main__':unittest.main()
