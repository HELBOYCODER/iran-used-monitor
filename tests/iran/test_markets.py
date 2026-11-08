import json
import unittest
from unittest.mock import patch
from iran_monitor.sources import parse_market_json, scan_source, FetchError


class MarketTests(unittest.TestCase):
    def test_esam_allowlist_fields_and_toman(self):
        raw={'data':{'items':[{'id':123,'item_name':'ساعت تست','price':11800000,'item_link':'/item/123/test','is_auction':True,'seller_id':999,'user_name':'private'}]}}
        item=parse_market_json(json.dumps(raw),'esam')[0]
        self.assertEqual(item['price'],11800000)
        self.assertEqual(item['city'],'unknown')
        self.assertIn('مزایده',item['description'])
        self.assertNotIn('seller_id',item)
        self.assertNotIn('private',str(item))

    def test_komodaa_allowlist_fields_and_toman(self):
        raw={'data':[{'product_id':'123','title':'مانتو','price':340000,'status':1,'user_id':999,'first_name':'private','description':'phone private'}]}
        item=parse_market_json(json.dumps(raw),'komodaa')[0]
        self.assertEqual(item['price'],340000)
        self.assertEqual(item['url'],'https://www.komodaa.com/product/123')
        self.assertEqual(item['description'],'')
        self.assertNotIn('private',str(item))

    def test_experimental_requires_operator_opt_in(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(FetchError) as context: scan_source({'source':'esam'})
            self.assertEqual(context.exception.status,'experimental_disabled')

if __name__=='__main__': unittest.main()
