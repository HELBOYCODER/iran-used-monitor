#!/usr/bin/env python3
"""Read-only JSON bridge over iran_monitor.sources (Python standard library only)."""
import argparse
import contextlib
import importlib
import io
import json
import re
import sys
from pathlib import Path

VERSION = '1'
SOURCE_INFO = {
    'divar': {'mode': 'public_html', 'city_filter': True, 'experimental': False},
    'sheypoor': {'mode': 'public_html', 'city_filter': True, 'experimental': False},
    'feed': {'mode': 'operator_feed', 'city_filter': False, 'experimental': False},
    'esam': {'mode': 'sampled_public_json', 'city_filter': False, 'experimental': True},
    'komodaa': {'mode': 'sampled_public_json', 'city_filter': False, 'experimental': True},
}
# Never forward arbitrary backend fields (seller identities, phone, raw payloads).
PUBLIC_FIELDS = ('source', 'title', 'price', 'url', 'image', 'city', 'description')


class BridgeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BridgeError('invalid_arguments', message)


def parser():
    p = Parser(description=__doc__)
    p.add_argument('--backend-root', type=Path, help='Explicit trusted checkout containing iran_monitor')
    sub = p.add_subparsers(dest='command', required=True, parser_class=Parser)
    sub.add_parser('sources', help='List adapter capabilities; does not probe availability')
    search = sub.add_parser('search', help='One bounded read; locally filter public listing cards')
    search.add_argument('--source', required=True, choices=sorted(SOURCE_INFO))
    search.add_argument('--query', required=True)
    search.add_argument('--city', default='tehran', help='City slug for HTML adapters; ignored by sampled feeds')
    search.add_argument('--min-price', type=int)
    search.add_argument('--max-price', type=int)
    search.add_argument('--limit', type=int, default=20)
    search.add_argument('--input-json', type=Path, help='Parse a locally captured public Esam/Komodaa response instead of fetching; never a live availability claim')
    search.add_argument('--count-only', action='store_true', help='Omit listing details for privacy-safe live smoke tests')
    return p


def load_backend(root=None):
    # No automatic sibling discovery: avoids accidentally importing another worktree.
    root = root or Path(__file__).resolve().parents[1]
    if not (root / 'iran_monitor' / 'sources.py').is_file():
        raise BridgeError('backend_unavailable', 'Merge the iran_monitor backend or pass --backend-root to a trusted checkout')
    sys.path.insert(0, str(root.resolve()))
    try:
        return importlib.import_module('iran_monitor.sources'), importlib.import_module('iran_monitor.core')
    except ImportError:
        raise BridgeError('backend_unavailable', 'iran_monitor backend could not be imported') from None


def search(args, sources, core):
    if not 1 <= args.limit <= 100:
        raise BridgeError('invalid_arguments', 'limit must be between 1 and 100')
    if not args.query.strip() or len(args.query) > 200:
        raise BridgeError('invalid_arguments', 'query must contain 1..200 characters')
    if not re.fullmatch('[a-z][a-z0-9-]{0,79}', args.city):
        raise BridgeError('invalid_arguments', 'city must be a lowercase city slug')
    for value in (args.min_price, args.max_price):
        if value is not None and not 0 <= value <= 10**15:
            raise BridgeError('invalid_arguments', 'prices must be nonnegative integer toman, at most 10^15')
    if args.min_price is not None and args.max_price is not None and args.min_price > args.max_price:
        raise BridgeError('invalid_arguments', 'min-price must not exceed max-price')
    watch = {'source': args.source, 'query': args.query, 'city': args.city,
             'min_price': args.min_price, 'max_price': args.max_price}
    try:
        if args.input_json:
            if args.source not in ('esam', 'komodaa'):
                raise BridgeError('invalid_arguments', 'input-json supports only Esam and Komodaa public response formats')
            try:
                with args.input_json.open('rb') as captured:
                    raw = captured.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise BridgeError('invalid_arguments', 'input-json exceeds 2 MiB')
                rows = sources.parse_market_json(raw.decode('utf-8'), args.source)
            except (OSError, UnicodeError):
                raise BridgeError('invalid_arguments', 'Cannot read UTF-8 public JSON capture') from None
        else:
            rows = sources.scan_source(watch)
    except sources.FetchError as exc:
        # Backend messages are controlled constants; never echo remote response bodies.
        raise BridgeError(exc.status, exc.detail) from None
    if not isinstance(rows, list):
        raise BridgeError('invalid_backend_response', 'Expected a list of public listing cards')
    matched = []
    seen = set()
    for row in rows[:100]:
        if not isinstance(row, dict) or not isinstance(row.get('title'), str) or not isinstance(row.get('url'), str):
            continue
        if row['url'] in seen or not core.matches(watch, row):
            continue
        seen.add(row['url'])
        matched.append({key: row.get(key) for key in PUBLIC_FIELDS})
    info = SOURCE_INFO[args.source]
    warnings = []
    if info['experimental']:
        warnings.append('First-page sample only; query is matched locally, not a complete marketplace search; city is unknown.')
    elif args.source == 'feed':
        warnings.append('Only the operator-approved feed is searched; city is not independently verified.')
    return {'ok': True, 'schema_version': VERSION, 'source': args.source,
            'mode': info['mode'], 'transport': 'local_capture' if args.input_json else 'backend_live',
            'query': args.query, 'requested_city': args.city,
            'city_filter_applied': info['city_filter'], 'currency': 'TMN',
            'fetched_count': len(rows), 'matched_count': len(matched),
            'returned_count': 0 if args.count_only else min(len(matched), args.limit),
            'items': [] if args.count_only else matched[:args.limit], 'warnings': warnings}


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.command == 'sources':
            result = {'ok': True, 'schema_version': VERSION,
                      'sources': [dict(id=key, **value) for key, value in SOURCE_INFO.items()],
                      'note': 'Capabilities only, not live availability. Experimental feeds require IRAN_MONITOR_EXPERIMENTAL_SOURCES=1.'}
        else:
            # stdout is a machine-readable channel even if backend logs accidentally.
            with contextlib.redirect_stdout(io.StringIO()):
                sources, core = load_backend(args.backend_root)
                result = search(args, sources, core)
        code = 0
    except BridgeError as exc:
        result = {'ok': False, 'schema_version': VERSION,
                  'error': {'code': exc.code, 'message': exc.message}}
        code = 2
    except Exception:
        result = {'ok': False, 'schema_version': VERSION,
                  'error': {'code': 'internal_error', 'message': 'Unexpected backend failure; no response body or secrets exposed'}}
        code = 3
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
