from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.diff_utils import build_related_call_sites, extract_changed_blocks_from_patch, infer_file_role


class SnapshotV5Tests(unittest.TestCase):
    def test_extract_changed_blocks_from_python_patch(self) -> None:
        patch = "\n".join(
            [
                "@@ -10,4 +10,6 @@",
                " def get_summary(site=None):",
                "-    return cache.get(KEY)",
                "+    cache_key = build_summary_cache_key(site)",
                "+    cached = cache.get(cache_key)",
                "+    return cached",
            ]
        )
        blocks = extract_changed_blocks_from_patch(patch, "src/opsmonitor/services/device_service.py")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["symbol"], "get_summary")
        self.assertEqual(blocks[0]["kind"], "function")
        self.assertIn("cache_key = build_summary_cache_key(site)", blocks[0]["afterSnippet"])

    def test_build_related_call_sites_links_changed_symbol_to_other_changed_file(self) -> None:
        service_file = {
            "path": "src/opsmonitor/services/device_service.py",
            "changedSymbols": ["get_summary"],
            "surroundingCode": [
                {"lineNumber": 12, "text": "def get_summary(site=None):"},
            ],
            "relatedCallSites": [],
        }
        route_file = {
            "path": "src/opsmonitor/api/routes/devices.py",
            "changedSymbols": [],
            "surroundingCode": [
                {"lineNumber": 8, "text": "return device_service.get_summary()"},
            ],
            "relatedCallSites": [],
        }
        build_related_call_sites([service_file, route_file])
        self.assertEqual(len(service_file["relatedCallSites"]), 1)
        self.assertEqual(service_file["relatedCallSites"][0]["filePath"], "src/opsmonitor/api/routes/devices.py")
        self.assertEqual(service_file["relatedCallSites"][0]["symbol"], "get_summary")

    def test_infer_file_role_marks_routes_as_api(self) -> None:
        self.assertEqual(infer_file_role("src/opsmonitor/api/routes/devices.py"), "api")


if __name__ == "__main__":
    unittest.main()
