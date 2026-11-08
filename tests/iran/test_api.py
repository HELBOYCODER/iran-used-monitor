import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from iran_monitor.core import Store
from iran_monitor.engine import Engine, BusyError
from iran_monitor.server import MonitorServer
from iran_monitor.sources import FetchError, parse_feed, validate_public_url


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/'panel').mkdir()
        (self.root/'panel'/'index.html').write_text('<h1>panel</h1>')
        (self.root/'secret.txt').write_text('private')
        (self.root/'panel'/'leak.json').symlink_to(self.root/'secret.txt')
        self.store=Store(str(self.root/'test.db'))
        self.engine=Engine(self.store,scanner=lambda w:[dict(source=w['source'],title='لپ تاپ تست',price=12000,url='https://divar.ir/v/test/abc',image='',city=w['city'],description='',score=100,reason='local')])
        self.server=MonitorServer(('127.0.0.1',0),self.store,self.root/'panel',token='test-only-token',engine=self.engine)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.engine.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self,method,path,data=None,auth=True,headers=None,raw=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        h={'Content-Type':'application/json'}
        if auth: h['Authorization']='Bearer test-only-token'
        h.update(headers or {})
        conn.request(method,path,body=raw if raw is not None else json.dumps(data).encode() if data is not None else None,headers=h)
        response=conn.getresponse()
        body=response.read()
        status=response.status
        self.assertEqual(response.getheader('X-Content-Type-Options'),'nosniff')
        conn.close()
        try: return status,json.loads(body)
        except ValueError: return status,body

    def create(self,**patch):
        code,watch=self.request('POST','/api/watches',dict(name='لپ تاپ',query='لپ تاپ',source='divar',**patch))
        self.assertEqual(code,201)
        return watch

    def test_auth_failclosed_health_and_static(self):
        self.assertEqual(self.request('GET','/api/health',auth=False)[0],200)
        self.assertEqual(self.request('GET','/',auth=False)[0],200)
        for path in ['/api/watches','/api/settings','/api/items','/api/sources','/api/notifications']:
            self.assertEqual(self.request('GET',path,auth=False)[0],401)
        self.server.token=''
        self.assertEqual(self.request('GET','/api/watches')[0],503)
        self.assertEqual(self.request('POST','/api/scan',{})[0],503)

    def test_watch_crud(self):
        watch=self.create()
        path='/api/watches/'+watch['id']
        self.assertEqual(self.request('GET','/api/watches')[1],[watch])
        self.assertEqual(self.request('GET',path)[1],watch)
        self.assertFalse(self.request('PATCH',path,{'enabled':False})[1]['enabled'])
        self.assertEqual(self.request('DELETE',path)[0],200)
        self.assertEqual(self.request('GET',path)[0],404)
        self.assertEqual(self.request('DELETE',path)[0],404)

    def test_scan_dedup_filters_and_persisted_notifications(self):
        watch=self.create()
        code,result=self.request('POST','/api/scan',{'watch_id':watch['id']})
        self.assertEqual(code,200)
        self.assertEqual(result['new_items'],1)
        self.engine.last_source_call.clear()
        self.assertEqual(self.request('POST','/api/scan',{'watch_id':watch['id']})[1]['new_items'],0)
        items=self.request('GET','/api/items?watch_id='+watch['id'])[1]
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['price'],12000)
        self.assertEqual(self.request('GET','/api/items?max_price=100')[1],[])
        self.assertEqual(self.request('GET','/api/items?min_price=12000')[1],items)
        self.assertEqual(self.request('GET','/api/items?offset=1')[1],[])
        notifications=self.request('GET','/api/notifications?unread=true')[1]
        self.assertEqual(len(notifications),1)
        self.assertEqual(len(Store(str(self.root/'test.db')).notifications()),1)
        self.assertEqual(self.request('PATCH','/api/notifications/'+notifications[0]['id'],{'read':True})[0],200)
        self.assertEqual(self.request('GET','/api/notifications?unread=true')[1],[])
        self.assertEqual(self.request('GET','/api/sources')[1][0]['status'],'connected')

    def test_settings_secret_rejection_and_no_echo(self):
        self.assertEqual(self.request('PUT','/api/settings',{'OPENAI_API_KEY':'never-save'})[0],422)
        self.assertEqual(self.request('PATCH','/api/settings',{'ai_enabled':True})[0],200)
        settings=self.request('GET','/api/settings')[1]
        self.assertTrue(settings['ai_enabled'])
        self.assertNotIn('test-only-token',json.dumps(settings))
        self.assertEqual(self.request('PUT','/api/settings',{'scheduler_enabled':'false'})[0],422)

    def test_payload_and_traversal_rejection(self):
        for path in ['/../secret.txt','/%2e%2e/secret.txt','/leak.json','/.git/config','/iran_monitor/core.py']:
            self.assertEqual(self.request('GET',path,auth=False)[0],404)
        for data in [{'name':'x','query':'x','source':'evil'}, {'name':'x','query':'x','source':'divar','enabled':'false'}]:
            self.assertEqual(self.request('POST','/api/watches',data)[0],422)
        self.assertEqual(self.request('POST','/api/watches',raw=b'{')[0],400)
        self.assertEqual(self.request('POST','/api/watches',raw=b'[]')[0],422)
        self.assertEqual(self.request('POST','/api/watches',raw=b'x'*16385)[0],413)
        self.assertEqual(self.request('GET','/api/items?limit=99999')[0],422)
        self.assertEqual(self.request('GET','/api/items?url=http://localhost')[0],422)
        self.assertEqual(self.request('POST','/api/scan',{'url':'http://localhost'})[0],422)

    def test_disabled_and_busy_scan(self):
        watch=self.create(enabled=False)
        self.assertEqual(self.request('POST','/api/scan',{'watch_id':watch['id']})[1]['results'][0]['status'],'disabled')
        self.engine.scan_lock.acquire()
        try: self.assertEqual(self.request('POST','/api/scan',{})[0],409)
        finally: self.engine.scan_lock.release()

    def test_real_failure_status_not_connected(self):
        watch=self.create()
        def blocked(w): raise FetchError('blocked','HTTP 403; no bypass attempted')
        self.engine.scanner=blocked
        self.request('POST','/api/scan',{'watch_id':watch['id']})
        self.assertEqual(self.request('GET','/api/sources')[1][0]['status'],'blocked')
        self.assertEqual(self.request('GET','/api/items')[1],[])

    def test_rate_limit(self):
        self.server.rates['127.0.0.1']=(__import__('time').monotonic(),120)
        self.assertEqual(self.request('GET','/api/settings')[0],429)
        self.assertEqual(self.request('GET','/api/health',auth=False)[0],200)

    def test_due_scheduler_and_manual_share_lock(self):
        watch=self.create()
        self.engine.scan(due=True)
        self.assertEqual(self.store.list_watches(due=True),[])
        self.assertEqual(self.engine.scan(due=True)['results'],[])
        self.store.update_watch(watch['id'],{'name':'updated'})
        self.assertEqual(len(self.store.list_watches(due=True)),1)


class NetworkBoundaryTests(unittest.TestCase):
    def test_dns_private_rejected(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): validate_public_url('https://divar.ir/s/tehran',{'divar.ir'})

    def test_feed_json_and_rss(self):
        for text in ['[{"title":"تست","price":"۱۲۳ تومان","url":"https://example.com/item"}]','<rss><channel><item><title>تست</title><price>۱۲۳ تومان</price><link>https://example.com/item</link></item></channel></rss>']:
            items=parse_feed(text,'https://example.com/feed','tehran')
            self.assertEqual(items[0]['price'],123)
        with self.assertRaises(FetchError): parse_feed('<!DOCTYPE foo><rss/>','https://example.com/feed','tehran')

if __name__=='__main__': unittest.main()
