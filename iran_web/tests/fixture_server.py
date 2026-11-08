"""Local browser fixture; never used by the application. python3 tests/fixture_server.py"""
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os
os.chdir(Path(__file__).resolve().parents[1])
WATCHES = []
NOTIFICATIONS = [{'id': 1, 'watch_id': 1, 'item_id': 1, 'read': False, 'created_at': '2026-11-08T10:00:00Z', 'item': {'title': 'تطبیق آزمایشی دوچرخه', 'price': 4500000}}]
class Handler(SimpleHTTPRequestHandler):
    def send_json(self, value, code=200):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        data = {'/api/health': {'ok': True}, '/api/sources': {'sources': [{'id': 'divar', 'name': 'دیوار', 'status': 'not_configured', 'detail': 'نیازمند پیکربندی'}]}, '/api/watches': {'watches': WATCHES}, '/api/items': {'items': [{'id': 1, 'source': 'divar', 'title': 'دوچرخه شهری <img src=x onerror=alert(1)>', 'price': 4500000, 'city': 'تهران', 'description': 'آگهی آزمایشی برای آزمون رابط؛ داده واقعی نیست.', 'url': 'javascript:alert(1)', 'score': 78, 'reason': 'داده آزمون', 'created_at': '2026-11-08T10:00:00Z'}]}, '/api/settings': {'fixture': True}}
        data['/api/notifications'] = {'notifications': NOTIFICATIONS}
        if self.path in data: self.send_json(data[self.path])
        else: super().do_GET()
    def payload(self): return json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
    def do_POST(self):
        data = self.payload()
        if self.path == '/api/watches':
            data['id'] = max([w['id'] for w in WATCHES], default=0)+1
            WATCHES.append(data)
        self.send_json(data, 201)
    def do_PATCH(self):
        data = self.payload()
        if self.path.startswith('/api/notifications/'):
            ident = int(self.path.rsplit('/', 1)[1])
            for n in NOTIFICATIONS:
                if n['id'] == ident: n.update(data)
        self.send_json(data)
    def do_PUT(self):
        data = self.payload(); ident = int(self.path.rsplit('/', 1)[1])
        for w in WATCHES:
            if w['id'] == ident: w.update(data)
        self.send_json(data)
    def do_DELETE(self):
        ident = int(self.path.rsplit('/', 1)[1]); WATCHES[:] = [w for w in WATCHES if w['id'] != ident]
        self.send_json(None)
if __name__ == '__main__': ThreadingHTTPServer(('127.0.0.1', 8768), Handler).serve_forever()
