"""Release wiring checks; no external network or production database."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class ReleaseContractTests(unittest.TestCase):
    def test_container_copies_only_iran_runtime(self):
        text = (ROOT / 'Dockerfile.iran').read_text()
        self.assertIn('COPY --chown=monitor:monitor iran_monitor', text)
        self.assertIn('COPY --chown=monitor:monitor iran_web', text)
        self.assertIn('USER monitor', text)
        self.assertNotIn('pip install', text)

    def test_compose_requires_auth_and_local_bind(self):
        text = (ROOT / 'compose.iran.yaml').read_text()
        self.assertIn('${IRAN_MONITOR_TOKEN:?', text)
        self.assertIn('127.0.0.1:8000:8000', text)
        self.assertIn('IRAN_MONITOR_EXPERIMENTAL_SOURCES:', text)
        self.assertIn('read_only: true', text)

    def test_license_and_provenance_preserved(self):
        self.assertIn('Copyright (c) 2025 dingyufei615', (ROOT / 'LICENSE').read_text())
        self.assertTrue((ROOT / 'README_UPSTREAM_ZH.md').is_file())
        self.assertIn('Usagi-org/ai-goofish-monitor', (ROOT / 'README.md').read_text())

    def test_docs_do_not_confuse_docker_entrypoints(self):
        text = (ROOT / 'README.md').read_text()
        self.assertIn('docker compose -f compose.iran.yaml', text)
        self.assertIn('python3 -m iran_monitor', text)
        self.assertIn('همه بازارهای ایران', text)


if __name__ == '__main__':
    unittest.main()
