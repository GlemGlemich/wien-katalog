import gzip
import json
import sqlite3
import tempfile
import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import offers
from offer_model import calculate, measure, matches, drink_kind, make_offer
from offer_pdf import parse_pages, page_dates


def fixture(store):
    with gzip.open(Path(__file__).parent/'fixtures'/(store+'-leaflet.json.gz'),'rt',encoding='utf-8') as file:
        return json.load(file)


def leaflet(store):
    return {'store':store,'id':'test-'+store,'url':'https://example.com/'+store,
            'valid_from':'2026-10-02' if store=='hofer' else '2026-10-01',
            'valid_to':'2026-10-08' if store=='hofer' else '2026-10-07'}


class OfferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows={s:parse_pages(fixture(s),s,leaflet(s))[0] for s in ('billa','hofer','lidl','spar')}

    def test_bulk_advertised_price_not_discounted_twice(self):
        row=next(r for r in self.rows['billa'] if r['name']=='Coca-Cola Limonaden')
        self.assertEqual((row['price_cents'],row['deal'],row['min_quantity'],row['total_cents']),(99,'3+3',6,594))
        self.assertAlmostEqual(row['unit_price'],.99)
        self.assertEqual(calculate(199,basis='single_before_free',paid=3,received=6)['total_cents'],597)

    def test_hofer_brand_volume_and_weekend(self):
        row=next(r for r in self.rows['hofer'] if 'COCA-COLA' in r['name'])
        self.assertEqual((row['price_cents'],row['min_quantity'],row['amount']),(124,6,1.5))
        self.assertEqual((row['valid_from'],row['valid_to']),('2026-10-02','2026-10-03'))
        self.assertAlmostEqual(row['unit_price'],1.24/1.5)
        self.assertTrue(offers.valid(row,'2026-10-03'))
        self.assertFalse(offers.valid(row,'2026-10-04'))

    def test_regular_and_member_prices_are_distinct(self):
        rows=[r for r in self.rows['lidl'] if 'PEPSI' in r['name']]
        self.assertEqual({(r['price_cents'],r['membership_required']) for r in rows},{(99,True),(119,False)})
        self.assertTrue(all('Zero Lemon' in r['name'] for r in rows))
        self.assertTrue(all(r['amount']==1.5 for r in rows))
        fish=[r for r in self.rows['lidl'] if 'Ofenbackfisch' in r['name']]
        self.assertTrue(all(r['min_quantity']==2 for r in fish))

    def test_package_and_reference_sizes_not_mixed(self):
        self.assertEqual(measure('Je 250 ml; 1 l = 3.80')[:2],(.25,'l'))
        self.assertEqual(measure('zzgl. Pfand € 0,25 1,5 l')[:2],(1.5,'l'))
        self.assertEqual(measure('zzgl. Pfand 8 x € 0,25 = € 2 8 x 330 ml')[:2],(2.64,'l'))
        self.assertIsNone(measure('0,75/1 Liter (1 l 1.85/1.22)')[0])
        self.assertIsNone(measure('ca. 499 g (per Kilo 9.99)')[0])

    def test_weight_condition_is_not_hundred_packages(self):
        row=next(r for r in self.rows['billa'] if r['name']=='Praga Schinken')
        self.assertEqual((row['min_quantity'],row['amount']),(1,.1))

    def test_spatial_reference_rejects_wrong_meat_price(self):
        self.assertFalse(any('EXQUISITE' in r['name'] and r['price_cents']==1199 for r in self.rows['hofer']))

    def test_spar_syrup_and_original_provenance(self):
        row=next(r for r in self.rows['spar'] if 'Sirup' in r['name'])
        self.assertEqual((row['price_cents'],row['amount'],row['page']),(269,1.5,12))
        self.assertEqual(row['flyer_id'],'test-spar')
        self.assertIn('per Liter',row['evidence'])
        vitamin=next(r for r in self.rows['spar'] if r['name']=='Vitamin Well')
        self.assertEqual((vitamin['deal'],vitamin['min_quantity']),('2+1',3))

    def test_beverage_names_not_meat_or_candy(self):
        self.assertEqual(drink_kind('saftig Schweinefleisch'),'')
        self.assertEqual(drink_kind('Kastner Weinbeisser'),'')
        cola=next(r for r in self.rows['hofer'] if 'COCA-COLA' in r['name'])
        self.assertTrue(matches(cola,'кола'))
        self.assertFalse(matches(cola,'соки'))

    def test_holidays_and_validity(self):
        self.assertTrue(offers.billa_closed(date(2026,10,4)))
        self.assertTrue(offers.billa_closed(date(2026,10,26)))
        self.assertTrue(offers.billa_closed(date(2026,4,6)))
        self.assertFalse(offers.billa_closed(date(2026,10,3)))
        row=self.rows['billa'][0]
        self.assertFalse(offers.valid(row,'2026-10-04'))
        self.assertFalse(offers.valid(row,'2026-09-30'))
        self.assertFalse(offers.valid(row,'2026-10-08'))

    def test_future_page_is_not_current(self):
        page=next(p for p in fixture('lidl') if p['number']==41)
        start,end=page_dates(page,'lidl',leaflet('lidl'))
        self.assertEqual((start,end),('2026-10-05','2026-10-07'))
        row=dict(self.rows['lidl'][0],valid_from=start,valid_to=end)
        self.assertFalse(offers.valid(row,'2026-10-03'))
        self.assertTrue(offers.valid(row,'2026-10-05'))

    def database(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;offers.initialize(db)
        for s,rows in self.rows.items(): offers.save(db,s,rows,1,'2026-10-03T09:00:00Z')
        return db

    def test_ranking_card_filter_and_quantity(self):
        with self.database() as db:
            result=offers.query(db,{'drink':['cola']},'2026-10-03')
            self.assertEqual((result['best']['store'],result['best']['price_cents']),('lidl',99))
            result=offers.query(db,{'drink':['cola'],'membership':['no']},'2026-10-03')
            self.assertEqual((result['best']['store'],result['best']['price_cents']),('lidl',119))
            self.assertFalse(any(r['membership_required'] for r in result['items']))
            result=offers.query(db,{'drink':['cola'],'quantity':['1']},'2026-10-03')
            self.assertTrue(all(r['min_quantity']==1 for r in result['items']))
            self.assertIsNone(offers.query(db,{},'2026-10-03')['best'])

    def test_failed_extraction_preserves_prices(self):
        with self.database() as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM flyer_offers')]
            with self.assertRaises(ValueError):offers.save(db,'billa',[],999,'2026-10-04T09:00:00Z')
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM flyer_offers')])
            self.assertEqual(db.execute("SELECT checked_at FROM offer_imports WHERE store='billa'").fetchone()[0],'2026-10-03T09:00:00Z')

    def test_protein_drink_visible_in_saved_leaflets_and_selection(self):
        row=make_offer(store='billa',flyer=leaflet('billa'),page=11,
                       name='Nöm PRO Proteindrink',price=114,size='330 ml (1 l 6.94/3.45)',
                       promo='1+1',minimum=2)
        self.assertEqual((row['group_id'],row['drink_kind']),('drinks','protein'))
        # Old saved data must be repaired when read, without a network refresh.
        row.update(id='protein-test',group_id='other',drink_kind='')
        with self.database() as db:
            offers.save(db,'billa',[row],0,'2026-10-06T09:00:00Z')
            result=offers.query(db,{'store':['billa'],'selection':['protein'],'category':['drinks'],'drink':['protein'],'q':['протеин']},'2026-10-06')
            self.assertEqual(result['total'],1)
            self.assertEqual((result['items'][0]['price_cents'],result['items'][0]['min_quantity']),(114,2))
            self.assertEqual(offers.query(db,{'selection':['protein']},'2026-10-08')['total'],0)
            self.assertEqual(offers.query(db,{'store':['billa'],'selection':['protein']},'2026-10-04')['total'],0)

    def test_previews_share_page_cache_and_reject_unknown_offers(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder, patch.object(offers,'CACHE',Path(folder)), self.database() as db:
            row=json.loads(db.execute("SELECT payload FROM flyer_offers WHERE store='billa' LIMIT 1").fetchone()[0])
            self.assertIsNone(offers.page_preview(db,'billa','../../missing'))
            self.assertIsNone(offers.page_preview(db,'billa',row['id']))
            path=offers.cache_path({'id':row['flyer_id']});path.write_bytes(b'fake-pdf')
            with patch('pdfplumber.open') as opened:
                pages=opened.return_value.__enter__.return_value.pages
                pages.__len__.return_value=160
                pages.__getitem__.return_value.to_image.return_value.original=Image.new('RGB',(400,600),'white')
                first=offers.page_preview(db,'billa',row['id'])
                self.assertTrue(first.startswith(b'\xff\xd8'))
                self.assertEqual(first,offers.page_preview(db,'billa',row['id']))
                self.assertEqual(opened.call_count,1)
                stat=path.stat();os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
                offers.page_preview(db,'billa',row['id'])
                self.assertEqual(opened.call_count,2)


if __name__=='__main__':unittest.main()
