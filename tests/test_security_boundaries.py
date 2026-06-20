import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_security_boundary_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class SecurityBoundaryTests(unittest.TestCase):
    def test_host_helpers_match_legacy_wrappers(self):
        from acg import security_boundaries

        legacy = worker._legacy_worker
        hosts = [
            "",
            "localhost",
            "localhost.localdomain",
            "127.0.0.1",
            "::1",
            "[::1]",
            "192.168.1.10",
            "10.0.0.2",
            "169.254.1.1",
            "metadata.google.internal",
            "www.youtube.com",
            "example.local",
            "8.8.8.8",
        ]
        for host in hosts:
            with self.subTest(host=host):
                self.assertEqual(security_boundaries.parsed_url_host(f"https://{host}/x"), legacy.parsed_url_host(f"https://{host}/x"))
                self.assertEqual(security_boundaries.host_is_loopback(host), legacy.host_is_loopback(host))
                self.assertEqual(security_boundaries.host_is_private_or_local(host), legacy.host_is_private_or_local(host))

    def test_source_url_validation_matches_legacy_wrappers(self):
        from acg import security_boundaries

        legacy = worker._legacy_worker
        safe_payloads = [
            {"source_url": "https://www.youtube.com/watch?v=test"},
            {"source_url": "http://127.0.0.1:8080/video.mp4", "allow_private_network_url": True},
        ]
        blocked_payloads = [
            {"source_url": ""},
            {"source_url": "ftp://example.com/video.mp4"},
            {"source_url": "http://127.0.0.1:8080/video.mp4"},
            {"source_url": "http://192.168.1.10/video.mp4"},
        ]
        for payload in safe_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(security_boundaries.validate_source_url_for_import(payload), legacy.validate_source_url_for_import(payload))
        for payload in blocked_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(SystemExit):
                    security_boundaries.validate_source_url_for_import(payload)
                with self.assertRaises(SystemExit):
                    legacy.validate_source_url_for_import(payload)

    def test_anki_connect_and_local_path_confirmation_match_legacy_wrappers(self):
        from acg import security_boundaries

        legacy = worker._legacy_worker
        for url in ["http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"]:
            with self.subTest(url=url):
                self.assertIsNone(security_boundaries.validate_anki_connect_url(url))
                self.assertIsNone(legacy.validate_anki_connect_url(url))
        for url in ["http://192.168.1.10:8765", "http://user:pass@127.0.0.1:8765", "file:///tmp/anki"]:
            with self.subTest(blocked_url=url):
                with self.assertRaises(SystemExit):
                    security_boundaries.validate_anki_connect_url(url)
                with self.assertRaises(SystemExit):
                    legacy.validate_anki_connect_url(url)

        allowed_payloads = [{}, {"local_path_access_confirmed": True}]
        for payload in allowed_payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(security_boundaries.require_confirmed_local_path_access(payload, stage="source"))
                self.assertIsNone(legacy.require_confirmed_local_path_access(payload, stage="source"))
        with self.assertRaises(SystemExit):
            security_boundaries.require_confirmed_local_path_access({"local_path_access_confirmed": False}, stage="source")
        with self.assertRaises(SystemExit):
            legacy.require_confirmed_local_path_access({"local_path_access_confirmed": False}, stage="source")


if __name__ == "__main__":
    unittest.main()
