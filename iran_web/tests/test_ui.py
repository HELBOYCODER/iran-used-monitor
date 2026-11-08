"""Dependency-free UI contract checks: python3 -m unittest discover -s iran_web/tests"""
import re
import unittest
from pathlib import Path
from html.parser import HTMLParser
ROOT = Path(__file__).resolve().parents[1]
class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids = []; self.resources = []; self.inline = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a: self.ids.append(a['id'])
        if 'style' in a or any(k.startswith('on') for k in a): self.inline.append(tag)
        if tag == 'script' and 'src' in a: self.resources.append(a['src'])
        if tag == 'link' and 'href' in a: self.resources.append(a['href'])
class UITest(unittest.TestCase):
    def setUp(self):
        self.js = (ROOT/'app.js').read_text(); self.html = (ROOT/'index.html').read_text()
        self.page = PageParser(); self.page.feed(self.html)
    def test_local_assets_and_csp(self):
        self.assertFalse(self.page.inline)
        for resource in self.page.resources:
            self.assertTrue((ROOT/resource).is_file())
            self.assertNotIn('://', resource)
    def test_safe_dom_and_memory_only_bearer(self):
        for unsafe in ['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'localStorage', 'sessionStorage', 'eval(']:
            self.assertNotIn(unsafe, self.js)
        self.assertIn("['http:','https:']", self.js)
        self.assertIn('textContent=text', self.js)
        self.assertIn("let bearer = ''", self.js)
    def test_unique_ids_and_js_targets(self):
        self.assertEqual(len(self.page.ids),len(set(self.page.ids)))
        for ident in re.findall(r"\$\('#([a-z-]+)'\)", self.js):
            self.assertIn(ident, self.page.ids)
    def test_api_contract(self):
        for endpoint in ['health','sources','watches','items','notifications','settings','scan']:
            self.assertIn("'"+endpoint+"'", self.js)
        self.assertIn("method:'PATCH'", self.js)
        self.assertIn('scheduler_enabled', self.js)
        self.assertIn('read:true', self.js)
        self.assertIn("dir=\"rtl\"", self.html)
        self.assertIn("Intl.NumberFormat('fa-IR')", self.js)
    def test_no_fake_app_data(self):
        self.assertNotIn('دوچرخه شهری <img', self.js)
        self.assertNotIn('4500000', self.js)
if __name__ == '__main__': unittest.main()
