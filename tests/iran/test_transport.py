import unittest
from unittest.mock import patch
from iran_monitor.sources import FetchError, fetch, parse_cards, validate_public_url


class TransportTests(unittest.TestCase):
    def test_synthetic_dns_requires_optin_and_fixed_host(self):
        records=[(2,1,6,'',('198.19.124.200',443)),(10,1,6,'',('2001:2::1',443,0,0))]
        with patch('socket.getaddrinfo',return_value=records),patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError): validate_public_url('https://api.esam.ir/x',{'api.esam.ir'})
            with patch.dict('os.environ',{'IRAN_MONITOR_TRUST_SYNTHETIC_DNS':'1'}):
                self.assertEqual(len(validate_public_url('https://api.esam.ir/x',{'api.esam.ir'})),2)
                with self.assertRaises(ValueError): validate_public_url('https://example.com/x',{'example.com'})
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch.dict('os.environ',{'IRAN_MONITOR_TRUST_SYNTHETIC_DNS':'1'}):
            with self.assertRaises(ValueError): validate_public_url('https://api.esam.ir/x',{'api.esam.ir'})

    def test_proxy_optin_still_checks_host_and_configuration(self):
        with patch.dict('os.environ',{'IRAN_MONITOR_USE_ENV_PROXY':'1'}),patch('urllib.request.getproxies',return_value={}):
            with self.assertRaises(FetchError): fetch('https://evil.example/x',{'api.esam.ir'})
            with self.assertRaises(FetchError) as context: fetch('https://api.esam.ir/x',{'api.esam.ir'})
            self.assertEqual(context.exception.status,'not_configured')

    def test_proxy_redirect_refused(self):
        class FakeOpener:
            def open(self,*args,**kwargs):
                return self.redirect.redirect_request(None,None,302,'redirect',{},'https://localhost/')
        def build(*handlers):
            opener=FakeOpener()
            opener.redirect=handlers[1]
            return opener
        with patch.dict('os.environ',{'IRAN_MONITOR_USE_ENV_PROXY':'1'}),patch('urllib.request.getproxies',return_value={'https':'http://trusted-proxy.invalid'}),patch('urllib.request.build_opener',side_effect=build):
            with self.assertRaises(FetchError) as context: fetch('https://api.esam.ir/x',{'api.esam.ir'})
            self.assertEqual(context.exception.status,'redirect')

    def test_system_dns_only_fixed_market_hosts(self):
        with patch.dict('os.environ',{'IRAN_MONITOR_TRUST_SYSTEM_DNS':'1'},clear=True),patch('iran_monitor.sources.fetch_trusted_proxy',return_value='ok') as trusted:
            self.assertEqual(fetch('https://api.esam.ir/x',{'api.esam.ir'}),'ok')
            self.assertTrue(trusted.call_args.kwargs['system_dns'])
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
                with self.assertRaises(FetchError): fetch('https://example.com/feed',{'example.com'})
            self.assertEqual(trusted.call_count,1)
        from iran_monitor.sources import fetch_trusted_proxy
        with self.assertRaises(FetchError): fetch_trusted_proxy('https://example.com/feed',{'example.com'},system_dns=True)

    def test_sheypoor_visual_toman_price(self):
        cards=parse_cards('<a href="/v/test"><h2>صندلی</h2><span>۴۰,۰۰۰,۰۰۰</span><span data-test-id="icon-toman"><svg></svg></span></a>','sheypoor','tehran')
        self.assertEqual(cards[0]['price'],40000000)
        self.assertIsNone(cards[0]['score'])

if __name__=='__main__': unittest.main()
