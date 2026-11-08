"""Validated domain types and SQLite persistence. Prices are integer toman."""
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

SOURCES = {'divar', 'sheypoor', 'feed', 'esam', 'komodaa'}
WATCH_FIELDS = {'id','name','source','query','city','min_price','max_price','interval_minutes','enabled'}
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك', '01234567890123456789یک')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize(value):
    return ' '.join(str(value).translate(DIGITS).replace('\u200c',' ').split())


def price_toman(value):
    if value is None or isinstance(value, bool): return None
    if isinstance(value, (int, float)):
        return int(value) if 0 <= value <= 10**15 else None
    text = normalize(value).lower()
    if 'رایگان' in text: return 0
    if any(x in text for x in ('توافق','تماس','نامشخص')): return None
    text = text.replace('٬','').replace(',','').replace('٫','.')
    match = re.search(r'(?<![\d.])(\d+(?:\.\d+)?)',text)
    if not match: return None
    number = float(match.group(1))
    number *= 10**9 if 'میلیارد' in text else 10**6 if 'میلیون' in text else 1000 if 'هزار' in text else 1
    if 'ریال' in text or 'irr' in text: number /= 10
    return int(number) if 0 <= number <= 10**15 else None


def integer(value, name, low=0, high=10**15):
    if isinstance(value, bool): raise ValueError(name + ' must be an integer')
    text = normalize(value).replace(',','').replace('٬','')
    if not re.fullmatch(r'\d+', text): raise ValueError(name + ' must be an integer')
    result = int(text)
    if not low <= result <= high: raise ValueError(name + ' out of range')
    return result


def validate_watch(data):
    if not isinstance(data, dict) or set(data) - WATCH_FIELDS: raise ValueError('Unknown watch fields')
    result = dict(data)
    for field, default, maximum in [('name','',120),('query','',200),('city','tehran',80)]:
        value = result.get(field,default)
        if not isinstance(value,str) or len(value) > maximum: raise ValueError('Invalid '+field)
        result[field] = normalize(value)
    if not result['name'] or not result['query']: raise ValueError('name and query are required')
    if not re.fullmatch('[a-z][a-z0-9-]{0,79}',result['city']): raise ValueError('city must be a city slug')
    if result.get('source') not in SOURCES: raise ValueError('Unknown source')
    result['enabled'] = result.get('enabled',True)
    if not isinstance(result['enabled'],bool): raise ValueError('enabled must be boolean')
    result['interval_minutes'] = integer(result.get('interval_minutes',30),'interval_minutes',1,10080)
    for field in ('min_price','max_price'):
        value = result.get(field)
        result[field] = None if value is None or value == '' else integer(value,field)
    if result['min_price'] is not None and result['max_price'] is not None and result['min_price'] > result['max_price']:
        raise ValueError('min_price exceeds max_price')
    return result


def matches(watch, item):
    text = normalize(item['title'] + ' ' + item.get('description','')).casefold()
    if not all(word in text for word in normalize(watch['query']).casefold().split()): return False
    price = item.get('price')
    if watch['min_price'] is not None and (price is None or price < watch['min_price']): return False
    if watch['max_price'] is not None and (price is None or price > watch['max_price']): return False
    return True


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS watches(id TEXT PRIMARY KEY, data TEXT NOT NULL, next_scan REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, source TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS matches(watch_id TEXT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
                item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE, PRIMARY KEY(watch_id,item_id));
            CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
                item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE, created_at TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source_status(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            try:
                with db: yield db
            finally: db.close()

    def list_watches(self, due=False):
        with self.connection() as db:
            rows = db.execute('SELECT data FROM watches' + (' WHERE next_scan <= ?' if due else '') + ' ORDER BY rowid', (time.time(),) if due else ()).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_watch(self, identity):
        with self.connection() as db:
            row = db.execute('SELECT data FROM watches WHERE id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def create_watch(self, data):
        if 'id' in data: raise ValueError('id is server assigned')
        watch = validate_watch(data)
        watch['id'] = uuid.uuid4().hex
        with self.connection() as db:
            if db.execute('SELECT count(*) FROM watches').fetchone()[0] >= 100: raise ValueError('Maximum 100 watches')
            db.execute('INSERT INTO watches(id,data) VALUES(?,?)',(watch['id'],json.dumps(watch,ensure_ascii=False)))
        return watch

    def update_watch(self, identity, patch):
        if not isinstance(patch,dict) or 'id' in patch: raise ValueError('id is immutable')
        with self.lock:
            old = self.get_watch(identity)
            if old is None: return None
            watch = validate_watch(dict(old,**patch))
            with self.connection() as db:
                db.execute('UPDATE watches SET data=?,next_scan=0 WHERE id=?',(json.dumps(watch,ensure_ascii=False),identity))
        return watch

    def delete_watch(self, identity):
        with self.connection() as db:
            return db.execute('DELETE FROM watches WHERE id=?',(identity,)).rowcount > 0

    def mark_scan(self, watch):
        with self.connection() as db:
            db.execute('UPDATE watches SET next_scan=? WHERE id=?',(time.time()+watch['interval_minutes']*60,watch['id']))

    def matched_before(self, watch, item):
        identity=hashlib.sha256((item['source']+'|'+item['url']).encode()).hexdigest()[:24]
        with self.connection() as db:
            return db.execute('SELECT 1 FROM matches WHERE watch_id=? AND item_id=?',(watch['id'],identity)).fetchone() is not None

    def save_item(self, watch, item):
        item = dict(item)
        identity = hashlib.sha256((item['source']+'|'+item['url']).encode()).hexdigest()[:24]
        item['id'] = identity
        with self.connection() as db:
            old = db.execute('SELECT created_at FROM items WHERE id=?',(identity,)).fetchone()
            item['created_at'] = old[0] if old else now_iso()
            db.execute('INSERT INTO items VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                       (identity,item['source'],json.dumps(item,ensure_ascii=False),item['created_at']))
            fresh = db.execute('INSERT OR IGNORE INTO matches VALUES(?,?)',(watch['id'],identity)).rowcount > 0
            if fresh:
                db.execute('INSERT INTO notifications VALUES(?,?,?,?,0)',(uuid.uuid4().hex,watch['id'],identity,now_iso()))
        return fresh

    def list_items(self, filters):
        limit = integer(filters.get('limit',100),'limit',1,500)
        offset = integer(filters.get('offset',0),'offset',0,1000000)
        where, args = [], []
        if filters.get('watch_id'):
            where.append('EXISTS(SELECT 1 FROM matches m WHERE m.item_id=i.id AND m.watch_id=?)'); args.append(filters['watch_id'])
        if filters.get('source'):
            where.append('i.source=?'); args.append(filters['source'])
        with self.connection() as db:
            rows = db.execute('SELECT i.data FROM items i' + (' WHERE '+' AND '.join(where) if where else '') + ' ORDER BY i.created_at DESC,i.id',args).fetchall()
        items = [json.loads(row[0]) for row in rows]
        for key in ('city','q'):
            if filters.get(key):
                term = normalize(filters[key]).casefold()
                items = [i for i in items if term in normalize(i['city'] if key=='city' else i['title']+' '+i['description']).casefold()]
        for key, compare in [('min_price',lambda a,b:a>=b),('max_price',lambda a,b:a<=b)]:
            if filters.get(key) is not None:
                price = integer(filters[key],key)
                items = [i for i in items if i['price'] is not None and compare(i['price'],price)]
        return items[offset:offset+limit]

    def notifications(self, unread=False):
        with self.connection() as db:
            rows = db.execute('SELECT n.*,i.data AS item FROM notifications n JOIN items i ON i.id=n.item_id' + (' WHERE n.read=0' if unread else '') + ' ORDER BY n.created_at DESC LIMIT 200').fetchall()
        return [dict(id=r['id'],watch_id=r['watch_id'],item_id=r['item_id'],created_at=r['created_at'],read=bool(r['read']),item=json.loads(r['item'])) for r in rows]

    def read_notification(self, identity):
        with self.connection() as db:
            return db.execute('UPDATE notifications SET read=1 WHERE id=?',(identity,)).rowcount > 0

    def get_setting(self, key, default=None):
        with self.connection() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_settings(self, patch):
        if not isinstance(patch,dict) or set(patch)-{'ai_enabled','scheduler_enabled'}: raise ValueError('Unknown settings; secrets are environment-only')
        if any(not isinstance(v,bool) for v in patch.values()): raise ValueError('Settings must be boolean')
        with self.connection() as db:
            for key,value in patch.items():
                db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))

    def status(self, source, data=None):
        with self.connection() as db:
            if data is not None:
                db.execute('INSERT INTO source_status VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(source,json.dumps(data)))
            row = db.execute('SELECT data FROM source_status WHERE id=?',(source,)).fetchone()
        return json.loads(row[0]) if row else None
