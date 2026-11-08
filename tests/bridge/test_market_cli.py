import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('iran_market_cli', ROOT / 'tools/iran_market_cli.py')
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


class FetchError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


class BridgeTests(unittest.TestCase):
    def invoke(self, *args, rows=None, error=None):
        def scan(watch):
            print('backend log must not corrupt JSON')
            if error:
                raise error
            return rows if rows is not None else []
        sources = types.SimpleNamespace(scan_source=scan, FetchError=FetchError)
        core = types.SimpleNamespace(matches=lambda watch, item: watch['query'] in item['title'])
        output = io.StringIO()
        with patch.object(cli, 'load_backend', return_value=(sources, core)), contextlib.redirect_stdout(output):
            code = cli.main(list(args))
        return code, json.loads(output.getvalue())

    def test_sources_without_backend(self):
        code, data = self.invoke('sources')
        self.assertEqual(code, 0)
        self.assertEqual(len(data['sources']), 5)
        self.assertTrue(next(x for x in data['sources'] if x['id'] == 'esam')['experimental'])

    def test_private_fields_removed_and_deduplicated(self):
        row = dict(title='phone test', url='https://esam.ir/item/1', source='esam', price=50,
                   seller_phone='PRIVATE', user_id='PRIVATE')
        code, data = self.invoke('search', '--source', 'esam', '--query', 'phone', rows=[row, row])
        self.assertEqual(code, 0)
        self.assertEqual(data['matched_count'], 1)
        self.assertNotIn('PRIVATE', json.dumps(data))
        self.assertFalse(data['city_filter_applied'])
        self.assertTrue(data['warnings'])

    def test_count_only_omits_listings(self):
        _, data = self.invoke('search', '--source', 'komodaa', '--query', 'x', '--count-only',
                              rows=[dict(title='x', url='https://www.komodaa.com/product/1')])
        self.assertEqual(data['matched_count'], 1)
        self.assertEqual(data['returned_count'], 0)
        self.assertEqual(data['items'], [])

    def test_upstream_block_not_empty_success(self):
        code, data = self.invoke('search', '--source', 'divar', '--query', 'x',
                                 error=FetchError('blocked', 'HTTP 403; no bypass attempted'))
        self.assertEqual(code, 2)
        self.assertEqual(data['error']['code'], 'blocked')

    def test_validation(self):
        cases = [('--limit', '0'), ('--limit', '101'), ('--city', '../admin'),
                 ('--min-price', '-1'), ('--min-price', '2', '--max-price', '1')]
        for extra in cases:
            code, data = self.invoke('search', '--source', 'esam', '--query', 'x', *extra)
            self.assertEqual(code, 2)
            self.assertEqual(data['error']['code'], 'invalid_arguments')

    def test_unknown_source_is_json(self):
        code, data = self.invoke('search', '--source', 'evil', '--query', 'x')
        self.assertEqual(code, 2)
        self.assertEqual(data['error']['code'], 'invalid_arguments')

    def test_internal_error_redacted(self):
        code, data = self.invoke('search', '--source', 'esam', '--query', 'x', error=RuntimeError('SECRET'))
        self.assertEqual(code, 3)
        self.assertNotIn('SECRET', json.dumps(data))

    def test_capture_unsupported_source_rejected(self):
        code, data = self.invoke('search', '--source', 'divar', '--query', 'x', '--input-json', '/missing')
        self.assertEqual(code, 2)
        self.assertEqual(data['error']['code'], 'invalid_arguments')

    def test_capture_missing_file_rejected(self):
        code, data = self.invoke('search', '--source', 'esam', '--query', 'x', '--input-json', '/missing')
        self.assertEqual(code, 2)
        self.assertEqual(data['error']['code'], 'invalid_arguments')

    def test_capture_uses_parser_not_network(self):
        sources = types.SimpleNamespace(FetchError=FetchError,
            parse_market_json=lambda text, source: [dict(title='x', url='https://esam.ir/1')])
        core = types.SimpleNamespace(matches=lambda watch, row: True)
        args = cli.parser().parse_args(['search', '--source', 'esam', '--query', 'x', '--input-json', 'capture.json'])
        with patch.object(Path, 'open', return_value=io.BytesIO(b'{"data":{}}')):
            data = cli.search(args, sources, core)
        self.assertEqual(data['transport'], 'local_capture')
        self.assertEqual(data['matched_count'], 1)

    def test_actual_script_sources(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/iran_market_cli.py'), 'sources'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)['ok'])


if __name__ == '__main__':
    unittest.main()
