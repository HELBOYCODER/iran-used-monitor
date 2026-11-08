"""Public listing cards only. No login, contact endpoint, browser or captcha bypass."""
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit
from .core import normalize, price_toman

MAX_RESPONSE = 2 * 1024 * 1024


class FetchError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


def validate_public_url(url, hosts, resolve=True):
    parts = urlsplit(url)
    try: port = parts.port
    except ValueError: raise ValueError('Invalid port') from None
    if parts.scheme != 'https' or parts.hostname not in hosts or parts.username or parts.password or port not in (None,443) or parts.fragment:
        raise ValueError('URL is not an approved HTTPS endpoint')
    if not resolve: return []
    records = socket.getaddrinfo(parts.hostname,443,type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(r[4][0] for r in records))
    synthetic_hosts={'divar.ir','www.sheypoor.com','api.esam.ir','search.komodaa.com'}
    synthetic_opt_in=os.environ.get('IRAN_MONITOR_TRUST_SYNTHETIC_DNS','')=='1' and parts.hostname in synthetic_hosts
    def approved(ip):
        address=ipaddress.ip_address(ip)
        return address.is_global or (synthetic_opt_in and ((address.version==4 and address in ipaddress.ip_network('198.18.0.0/15')) or (address.version==6 and address in ipaddress.ip_network('2001:2::/48'))))
    if not addresses or any(not approved(ip) for ip in addresses):
        raise ValueError('Non-public network destination refused')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        sock = socket.create_connection((self.ip,443),self.timeout)
        try: self.sock = self._context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def fetch(url, hosts, method='GET', payload=None, headers=None):
    """Pin validated DNS address; no proxies, cookies, redirects or decompression."""
    try:
        if os.environ.get('IRAN_MONITOR_TRUST_SYSTEM_DNS','')=='1' and urlsplit(url).hostname in {'divar.ir','www.sheypoor.com','api.esam.ir','search.komodaa.com'}:
            return fetch_trusted_proxy(url,hosts,method,payload,headers,system_dns=True)
        if os.environ.get('IRAN_MONITOR_USE_ENV_PROXY','')=='1':
            return fetch_trusted_proxy(url,hosts,method,payload,headers)
        addresses = validate_public_url(url, hosts)
        parts = urlsplit(url)
        connection = PinnedHTTPS(parts.hostname,addresses[0],8)
        deadline = time.monotonic()+15
        request_headers = {'User-Agent':'IranUsedMonitor/1.0 (public listing monitor)', 'Accept':'text/html, application/json, application/rss+xml', 'Accept-Encoding':'identity'}
        request_headers.update(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        if body is not None: request_headers['Content-Type']='application/json'
        try:
            connection.request(method,parts.path+('?' + parts.query if parts.query else ''),body=body,headers=request_headers)
            response = connection.getresponse()
            if response.status in (401,403,429): raise FetchError('blocked', 'HTTP '+str(response.status)+'; no bypass attempted')
            if 300 <= response.status < 400: raise FetchError('redirect','Redirect refused; approved URL must be direct')
            if response.status != 200: raise FetchError('error','HTTP '+str(response.status))
            if response.getheader('Content-Encoding','identity') not in ('identity',''): raise FetchError('error','Compressed response refused')
            chunks, size = [], 0
            while True:
                if time.monotonic() > deadline: raise FetchError('timeout','Response deadline exceeded')
                chunk = response.read1(min(65536,MAX_RESPONSE+1-size))
                if not chunk: break
                size += len(chunk)
                if size > MAX_RESPONSE: raise FetchError('error','Response exceeds 2 MiB limit')
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8','replace')
        finally: connection.close()
    except FetchError: raise
    except (OSError, ValueError, http.client.HTTPException):
        raise FetchError('unreachable','Network, TLS or public-destination validation failed') from None


def safe_link(url, base, image=False):
    absolute = urljoin(base,url)
    parts = urlsplit(absolute)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password: return ''
    try:
        if parts.port not in (None,443): return ''
        if not ipaddress.ip_address(parts.hostname).is_global: return ''
    except ValueError: pass
    if parts.hostname == 'localhost' or parts.hostname.endswith(('.localhost','.local','.internal')): return ''
    if not image and parts.hostname != urlsplit(base).hostname: return ''
    return absolute.split('#')[0].split('?')[0]


class Cards(HTMLParser):
    def __init__(self, source, city):
        super().__init__(convert_charrefs=True)
        self.source, self.city = source, city
        self.base = 'https://divar.ir' if source=='divar' else 'https://www.sheypoor.com'
        self.cards, self.card, self.capture_title = [], None, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag=='a' and attrs.get('href','').startswith('/v/'):
            self.card = {'source':self.source,'title':'','price':None,'url':safe_link(attrs['href'],self.base),'image':'','city':self.city,'description':'','score':None,'ai_evaluated':False,'reason':'تطبیق واژه‌ها و محدوده قیمت','texts':[]}
        if self.card is None: return
        if attrs.get('data-test-id')=='icon-toman' and self.card['texts']:
            self.card['_price_text']=self.card['texts'][-1]+' تومان'
        if tag in ('h2','h3'): self.capture_title = True
        if tag=='img' and not self.card['image']:
            self.card['image']=safe_link(attrs.get('src',attrs.get('data-src','')),self.base,True)
            if not self.card['title']: self.card['title']=normalize(attrs.get('alt',''))

    def handle_data(self, data):
        if self.card is not None:
            text = normalize(data)
            if text:
                self.card['texts'].append(text)
                if self.capture_title: self.card['title'] = (self.card['title']+' '+text).strip() if self.card.get('_heading') else text
                if self.capture_title: self.card['_heading']=True

    def handle_endtag(self, tag):
        if tag in ('h2','h3'): self.capture_title=False
        if tag=='a' and self.card is not None:
            card = self.card
            texts = card.pop('texts')
            card.pop('_heading',None)
            # Only price-labelled card text, never model numbers or relative dates.
            price_text = next((t for t in texts if any(x in t for x in ('تومان','ریال','توافق','رایگان'))),None)
            card['price']=price_toman(card.pop('_price_text',price_text))
            card['title']=card['title'][:300]
            # Public listing-card snippets only; never request detailed/contact pages.
            card['description']=' | '.join(t for t in texts if t != card['title'])[:1000]
            if card['url'] and card['title'] and len(self.cards)<100: self.cards.append(card)
            self.card=None


def parse_cards(html, source, city):
    parser = Cards(source,city)
    parser.feed(html)
    return list({c['url']:c for c in parser.cards}.values())


def feed_config():
    """Operator-approved feed URL; never accepted from the API."""
    url = os.environ.get('IRAN_MONITOR_FEED_URL','')
    hosts = {h.strip().lower() for h in os.environ.get('IRAN_MONITOR_FEED_HOSTS','').split(',') if h.strip()}
    return url, hosts


def parse_feed(text, url, city):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper(): raise FetchError('parse_error','XML declarations refused')
    try:
        if text.lstrip().startswith(('[','{')):
            data = json.loads(text)
            rows = data if isinstance(data,list) else data.get('items',[])
        else:
            root = ET.fromstring(text)
            rows=[]
            for node in list(root.findall('.//item'))[:100]:
                rows.append({'title':node.findtext('title',''),'url':node.findtext('link',''),'description':node.findtext('description',''),'price':node.findtext('price')})
        if not isinstance(rows,list): raise ValueError()
        items=[]
        for row in rows[:100]:
            if not isinstance(row,dict): continue
            title = normalize(row.get('title',''))[:300]
            link = safe_link(str(row.get('url',row.get('link',''))),url)
            if title and link:
                # Feed markup is not rendered; description deliberately omitted for privacy.
                items.append(dict(source='feed',title=title,price=price_toman(row.get('price')),url=link,image=safe_link(str(row.get('image','')),url,True) if row.get('image') else '',city=city,description='',score=None,ai_evaluated=False,reason='تطبیق واژه‌ها و محدوده قیمت'))
        return items
    except (ValueError,TypeError,ET.ParseError): raise FetchError('parse_error','Invalid JSON/RSS feed') from None


def scan_source(watch):
    source=watch['source']
    if source in ('esam','komodaa'):
        if os.environ.get('IRAN_MONITOR_EXPERIMENTAL_SOURCES','').lower() not in ('1','true'):
            raise FetchError('experimental_disabled','Experimental sampled public feeds require IRAN_MONITOR_EXPERIMENTAL_SOURCES=1; no keyword or city search guaranteed')
        url = 'https://api.esam.ir/api/items/v2/GetItemList?pageNumber=1' if source=='esam' else 'https://search.komodaa.com/api/v2.6/search/products'
        return parse_market_json(fetch(url,{urlsplit(url).hostname}),source)
    if source=='feed':
        url,hosts=feed_config()
        if not url or not hosts: raise FetchError('not_configured','Set operator-approved IRAN_MONITOR_FEED_URL and IRAN_MONITOR_FEED_HOSTS')
        return parse_feed(fetch(url,hosts),url,watch['city'])
    base = 'https://divar.ir' if source=='divar' else 'https://www.sheypoor.com'
    # Sheypoor can ignore search query server-side: local matching remains mandatory.
    url = base+'/s/'+watch['city']+'?'+urlencode({'q' if source=='divar' else 'keyword':watch['query']})
    text=fetch(url,{urlsplit(base).hostname})
    cards=parse_cards(text,source,watch['city'])
    if not cards:
        lower=text.lower()
        if any(x in lower for x in ('captcha','access denied','verify you are human')):
            raise FetchError('blocked','Challenge or denied page; no bypass attempted')
        raise FetchError('no_cards','HTTP 200 but no public listing cards parsed (empty results or changed markup)')
    return cards


def parse_market_json(text, source):
    """Experimental first-page feeds, not full search. API prices verified against UI as TMN.

    Esam UI 11,800,000 toman corresponds to API 11800000 and schema IRR 118000000.
    Komodaa UI product:price:currency TMN corresponds to API numeric price directly.
    Seller/user identifiers, names, descriptions and avatars are never persisted.
    """
    try:
        data=json.loads(text)['data']
        rows=data['items'] if source=='esam' else data
        if not isinstance(rows,list): raise ValueError()
        items=[]
        for row in rows[:100]:
            if not isinstance(row,dict): continue
            if source=='esam':
                if row.get('is_sold'): continue
                title=normalize(row.get('item_name',''))[:300]
                url=safe_link(str(row.get('item_link','')),'https://esam.ir')
                image=safe_link(str(row.get('item_small_thumb_url','')),'https://esam.ir',True) if row.get('item_small_thumb_url') else ''
                description='مزایده؛ قیمت پیشنهادی فعلی است، نه قیمت خرید قطعی' if row.get('is_auction') else ''
            else:
                identity=str(row.get('product_id',''))
                if not identity.isdigit(): continue
                title=normalize(row.get('title',''))[:300]
                url='https://www.komodaa.com/product/'+identity
                image=safe_link(str(row.get('media_full_path','')).split(',')[0],'https://www.komodaa.com',True) if row.get('media_full_path') else ''
                description=''
            if not title or not url: continue
            items.append(dict(source=source,title=title,price=price_toman(row.get('price')),url=url,image=image,city='unknown',description=description,score=None,ai_evaluated=False,reason='تطبیق محلی خوراک نمونه آزمایشی؛ شهر نامشخص'))
        return items
    except (ValueError,TypeError,KeyError):
        raise FetchError('parse_error','Invalid experimental market feed') from None


def fetch_trusted_proxy(url, hosts, method='GET', payload=None, headers=None, system_dns=False):
    """Explicit operator trust boundary: proxy resolves DNS; no IP pinning in this mode."""
    import urllib.request
    import urllib.error
    validate_public_url(url,hosts,resolve=False)
    # Even a configured feed/AI host cannot name a private literal in proxy mode.
    hostname=urlsplit(url).hostname
    try:
        if not ipaddress.ip_address(hostname).is_global: raise FetchError('unreachable','Private destination refused')
    except ValueError: pass
    if hostname=='localhost' or hostname.endswith(('.local','.internal','.localhost')):
        raise FetchError('unreachable','Private destination refused')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise FetchError('redirect','Redirect refused; approved URL must be direct')
    request_headers={'User-Agent':'IranUsedMonitor/1.0 (public listing monitor)','Accept-Encoding':'identity'}
    request_headers.update(headers or {})
    body=json.dumps(payload).encode() if payload is not None else None
    if body is not None: request_headers['Content-Type']='application/json'
    if system_dns and hostname not in {'divar.ir','www.sheypoor.com','api.esam.ir','search.komodaa.com'}:
        raise FetchError('unreachable','System DNS trust limited to fixed market hosts')
    proxies={} if system_dns else urllib.request.getproxies()
    if not system_dns and not proxies.get('https'):
        raise FetchError('not_configured','Trusted proxy mode requires an HTTPS_PROXY environment setting')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler(proxies),NoRedirect())
    try:
        with opener.open(urllib.request.Request(url,data=body,headers=request_headers,method=method),timeout=8) as response:
            if response.status!=200: raise FetchError('error','Unexpected HTTP status')
            if response.headers.get('Content-Encoding','identity') not in ('','identity'): raise FetchError('error','Compressed response refused')
            deadline=time.monotonic()+15
            size=0; chunks=[]
            while True:
                if time.monotonic()>deadline: raise FetchError('timeout','Response deadline exceeded')
                chunk=response.read1(min(65536,MAX_RESPONSE+1-size))
                if not chunk: break
                size+=len(chunk)
                if size>MAX_RESPONSE: raise FetchError('error','Response exceeds 2 MiB limit')
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8','replace')
    except urllib.error.HTTPError as error:
        raise FetchError('blocked' if error.code in (401,403,429) else 'error','HTTP '+str(error.code)) from None
    except urllib.error.URLError:
        raise FetchError('unreachable','Trusted proxy transport failed') from None
