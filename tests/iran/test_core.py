import tempfile
import unittest
from pathlib import Path
from iran_monitor.core import Store, normalize, price_toman, validate_watch
from iran_monitor.sources import parse_cards, validate_public_url


class CoreTests(unittest.TestCase):
    def test_persian_normalization(self):
        self.assertEqual(normalize('كيبورد ۱۲٣'), 'کیبورد 123')

    def test_prices(self):
        for raw, expected in [('۱۲٬۵۰۰٬۰۰۰ تومان',12500000), ('۲.۵ میلیون تومان',2500000), ('۱۰۰ هزار تومان',100000), ('۱۲۰٬۰۰۰ ریال',12000), ('توافقی',None), ('رایگان',0)]:
            with self.subTest(raw=raw): self.assertEqual(price_toman(raw), expected)

    def test_watch_validation(self):
        watch = validate_watch({'name':'لپ تاپ','source':'divar','query':'لپ تاپ'})
        self.assertEqual(watch['city'], 'tehran')
        self.assertEqual(watch['interval_minutes'], 30)
        for patch in [{'source':'http://localhost'}, {'enabled':'false'}, {'interval_minutes':0}, {'min_price':100,'max_price':1}, {'city':'../x'}, {'url':'http://x'}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_watch(dict(watch, **patch))

    def test_store_persistence_and_crud(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'db.sqlite3')
            store = Store(path)
            watch = store.create_watch({'name':'x','source':'divar','query':'x'})
            self.assertEqual(Store(path).get_watch(watch['id'])['name'], 'x')
            self.assertFalse(store.update_watch(watch['id'], {'enabled':False})['enabled'])
            store.delete_watch(watch['id'])
            self.assertIsNone(store.get_watch(watch['id']))

    def test_ssrf(self):
        for url in ['http://divar.ir/s/tehran','https://127.0.0.1','https://divar.ir@localhost/','https://divar.ir.evil.test','https://divar.ir:444/']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url(url, {'divar.ir'}, resolve=False)

    def test_public_card_parser(self):
        html = '<a href="/v/example/abc"><h2>لپ تاپ</h2><div>۱۲٬۰۰۰ تومان</div><img src="https://s100.divarcdn.com/x.webp"></a>'
        cards = parse_cards(html, 'divar', 'tehran')
        self.assertEqual(len(cards),1)
        self.assertEqual(cards[0]['price'],12000)
        self.assertEqual(cards[0]['title'],'لپ تاپ')

if __name__ == '__main__': unittest.main()
