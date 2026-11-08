"""Local single-user API. All /api routes except health require Bearer auth."""
import hmac
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from .core import Store
from .engine import BusyError, Engine

LOG=logging.getLogger('iran_monitor')
MAX_BODY=16384


class APIError(Exception):
    def __init__(self, code, message): self.code,self.message=code,message


class MonitorServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    request_queue_size=32

    def __init__(self, address, store, static_dir=None, token=None, engine=None):
        self.store=store
        self.engine=engine or Engine(store)
        self.static_dir=Path(static_dir or Path(__file__).resolve().parent.parent/'iran_web').resolve()
        self.token=os.environ.get('IRAN_MONITOR_TOKEN','') if token is None else token
        self.rate_lock=threading.Lock()
        self.rates={}
        self.worker_slots=threading.BoundedSemaphore(32)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.worker_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request,client_address)
        except BaseException:
            self.worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request,client_address)
        finally: self.worker_slots.release()

    def allowed_rate(self, address):
        with self.rate_lock:
            now=time.monotonic()
            if len(self.rates)>1024:
                self.rates={k:v for k,v in self.rates.items() if now-v[0]<60}
                if len(self.rates)>1024: return False
            start,count=self.rates.get(address,(now,0))
            if now-start>=60: start,count=now,0
            self.rates[address]=(start,count+1)
            return count<120


class Handler(BaseHTTPRequestHandler):
    server_version='IranMonitor/1.0'
    sys_version=''

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Never log URL queries, headers, payloads or untrusted upstream content.
        pass

    def send_data(self, status, data, content_type='application/json; charset=utf-8'):
        if isinstance(data,(dict,list)):
            data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        elif isinstance(data,str): data=data.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Connection','close')
        if status==401: self.send_header('WWW-Authenticate','Bearer')
        if status==429: self.send_header('Retry-After','60')
        self.end_headers()
        self.close_connection=True
        if self.command!='HEAD': self.wfile.write(data)

    def read_json(self):
        if self.headers.get('Transfer-Encoding'): raise APIError(400,'Transfer-Encoding is not supported')
        if len(self.headers.get_all('Content-Length',[]))>1: raise APIError(400,'Ambiguous content length')
        raw=self.headers.get('Content-Length','0')
        if not raw.isdigit(): raise APIError(400,'Invalid Content-Length')
        size=int(raw)
        if size>MAX_BODY: raise APIError(413,'Body exceeds 16 KiB')
        if not size: return {}
        if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json': raise APIError(415,'Use application/json')
        try:
            data=json.loads(self.rfile.read(size),parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError,UnicodeDecodeError): raise APIError(400,'Invalid JSON') from None
        if not isinstance(data,dict): raise APIError(422,'Expected JSON object')
        return data

    def authenticate(self):
        if not self.server.token: raise APIError(503,'Authentication not configured: set IRAN_MONITOR_TOKEN')
        if len(self.headers.get_all('Authorization',[]))!=1: raise APIError(401,'Bearer token required')
        value=self.headers.get('Authorization','')
        if not value.startswith('Bearer ') or not hmac.compare_digest(value[7:].encode(),self.server.token.encode()):
            raise APIError(401,'Invalid Bearer token')

    def do_GET(self): self.dispatch()
    def do_HEAD(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def do_PUT(self): self.dispatch()
    def do_PATCH(self): self.dispatch()
    def do_DELETE(self): self.dispatch()
    def do_OPTIONS(self): self.dispatch()

    def dispatch(self):
        try:
            if len(self.path)>4096: raise APIError(414,'URI too long')
            parsed=urlsplit(self.path)
            path=unquote(parsed.path)
            if path=='/api/health' and self.command in ('GET','HEAD'):
                return self.send_data(200,{'ok':True,'service':'iran-monitor','version':'1.0.0','auth_configured':bool(self.server.token),'scheduler_running':bool(self.server.engine.thread and self.server.engine.thread.is_alive())})
            if path=='/api' or path.startswith('/api/'):
                if not self.server.allowed_rate(self.client_address[0]): raise APIError(429,'Rate limit exceeded')
                self.authenticate()
                query={key:values[-1] for key,values in parse_qs(parsed.query,max_num_fields=20).items()}
                return self.api(path,query)
            if self.command not in ('GET','HEAD'): raise APIError(405,'Method not allowed')
            self.static(path)
        except APIError as error: self.send_data(error.code,{'error':error.message})
        except (ValueError,TypeError): self.send_data(422,{'error':'Invalid input'})
        except (BrokenPipeError,ConnectionResetError,TimeoutError): self.close_connection=True
        except Exception:
            LOG.error('Request failed safely (%s)',self.command)
            self.send_data(500,{'error':'Internal server error'})

    def api(self,path,query):
        method='GET' if self.command=='HEAD' else self.command
        store,engine=self.server.store,self.server.engine
        if path=='/api/sources' and method=='GET': return self.send_data(200,engine.sources())
        if path=='/api/settings':
            if method=='GET': return self.send_data(200,engine.settings())
            if method in ('PUT','PATCH'):
                store.set_settings(self.read_json())
                return self.send_data(200,engine.settings())
            raise APIError(405,'Method not allowed')
        if path=='/api/watches':
            if method=='GET': return self.send_data(200,store.list_watches())
            if method=='POST': return self.send_data(201,store.create_watch(self.read_json()))
            raise APIError(405,'Method not allowed')
        match=re.fullmatch('/api/watches/([a-f0-9]{32})',path)
        if match:
            identity=match.group(1)
            if method=='GET': result=store.get_watch(identity)
            elif method in ('PATCH','PUT'): result=store.update_watch(identity,self.read_json())
            elif method=='DELETE': result={'ok':True} if store.delete_watch(identity) else None
            else: raise APIError(405,'Method not allowed')
            if result is None: raise APIError(404,'Watch not found')
            return self.send_data(200,result)
        if path=='/api/items' and method=='GET':
            if set(query)-{'watch_id','source','q','city','min_price','max_price','limit','offset'}: raise APIError(422,'Unknown item filters')
            return self.send_data(200,store.list_items(query))
        if path=='/api/scan' and method=='POST':
            data=self.read_json()
            if set(data)-{'watch_id'} or ('watch_id' in data and (not isinstance(data['watch_id'],str) or not re.fullmatch('[a-f0-9]{32}',data['watch_id']))): raise APIError(422,'Invalid watch_id')
            try: result=engine.scan(data.get('watch_id'))
            except BusyError: raise APIError(409,'Scan already running') from None
            except KeyError: raise APIError(404,'Watch not found') from None
            return self.send_data(200,result)
        if path=='/api/notifications' and method=='GET':
            return self.send_data(200,store.notifications(query.get('unread')=='true'))
        match=re.fullmatch('/api/notifications/([a-f0-9]{32})',path)
        if match and method=='PATCH':
            if self.read_json()!={'read':True}: raise APIError(422,'Use {"read":true}')
            if not store.read_notification(match.group(1)): raise APIError(404,'Notification not found')
            return self.send_data(200,{'ok':True})
        raise APIError(404,'API route not found')

    def static(self,path):
        if '\x00' in path or '\\' in path: raise APIError(404,'Not found')
        root=self.server.static_dir
        target=(root/path.lstrip('/')).resolve()
        if not target.is_relative_to(root): raise APIError(404,'Not found')
        if target.is_dir(): target=(target/'index.html').resolve()
        if not target.is_relative_to(root) or not target.is_file(): raise APIError(404,'Panel file not found')
        if target.name.startswith('.') or target.suffix.lower() not in {'.html','.js','.css','.svg','.png','.jpg','.jpeg','.webp','.ico','.woff','.woff2','.json'}:
            raise APIError(404,'Not found')
        if target.stat().st_size>4*1024*1024: raise APIError(413,'Static file too large')
        mime=mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        self.send_data(200,target.read_bytes(),mime)


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Iran used-market monitor (stdlib only)')
    parser.add_argument('--host',default=os.environ.get('IRAN_MONITOR_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('IRAN_MONITOR_PORT','8000')))
    parser.add_argument('--db',default=os.environ.get('IRAN_MONITOR_DB',str(Path(__file__).resolve().parent.parent/'data'/'iran-monitor.sqlite3')))
    parser.add_argument('--static-dir',default=os.environ.get('IRAN_MONITOR_STATIC_DIR'))
    args=parser.parse_args()
    Path(args.db).expanduser().resolve().parent.mkdir(parents=True,exist_ok=True)
    store=Store(str(Path(args.db).expanduser()))
    server=MonitorServer((args.host,args.port),store,args.static_dir)
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    if not server.token: LOG.warning('API is fail-closed: configure IRAN_MONITOR_TOKEN')
    # No background network requests without authentication configured.
    if server.token: server.engine.start()
    LOG.info('Iran monitor listening on %s:%s',args.host,args.port)
    try: server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt: pass
    finally:
        server.engine.stop()
        server.server_close()
