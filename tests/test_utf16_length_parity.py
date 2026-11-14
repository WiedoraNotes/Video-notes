"""Regression: desktop, mobile and JS export limits share UTF-16 code-unit counting.

Synthetic emoji are used to exercise an actual portable-contract mismatch:
5001 emoji are 5001 Python code points but 10002 JavaScript UTF-16 units.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_contracts import demo_project, demo_transcript
from videonotes.contracts import (
    utf16_code_units, validate_project, validate_transcript,
)
from videonotes.errors import VideoNotesError
from videonotes.exports import edit_segment, export_project
from videonotes.mobile_contract import validate_portable_export, parse_portable_export
from videonotes.semantic_draft import _safe_text
from videonotes.storage import read_project, save_json
from videonotes.web_corrections import import_web_corrections


class Utf16LengthParityTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        save_json(self.project / "project.json", demo_project())
        save_json(self.project / "transcript.json", demo_transcript())

    def test_codeunit_counts_match_js_length_for_astral_and_bmp_text(self):
        self.assertEqual(utf16_code_units("Zażółć"), 6)
        self.assertEqual(utf16_code_units("😀" * 5000), 10000)
        self.assertEqual(utf16_code_units("😀" * 5001), 10002)
        self.assertTrue(_safe_text("😀" * 80, 160))
        self.assertFalse(_safe_text("😀" * 81, 160))

    def test_raw_asr_accepts_5000_emojis_but_rejects_5001(self):
        project = demo_project()
        transcript = demo_transcript()
        transcript["segments"][0]["text"] = "😀" * 5000
        validate_transcript(transcript, project)
        transcript["segments"][0]["text"] = "😀" * 5001
        with self.assertRaises(VideoNotesError):
            validate_transcript(transcript, project)

    def test_desktop_edit_exceeding_browser_limit_fails_before_write(self):
        original = (self.project / "transcript.json").read_bytes()
        edit_segment(self.project, "c0000000-s00000", "😀" * 5000)
        edits_before = (self.project / "edits.json").read_bytes()
        self.assertEqual(read_project(self.project)[2]["edits"]["c0000000-s00000"], "😀" * 5000)
        with self.assertRaises(VideoNotesError):
            edit_segment(self.project, "c0000000-s00000", "😀" * 5001)
        self.assertEqual((self.project / "edits.json").read_bytes(), edits_before)
        self.assertEqual((self.project / "transcript.json").read_bytes(), original)
        exported = export_project(self.project)
        portable = self.project / "exports" / "transcript.json"
        doc = parse_portable_export(portable.read_bytes())
        self.assertEqual(doc["segments"][0]["text"], "😀" * 5000)
        self.assertEqual(len(exported), 4)

    def test_project_identifier_bound_matches_portable_128_codeunits(self):
        project = demo_project()
        project["id"] = "😀" * 64
        validate_project(project)
        project["id"] += "😀"
        with self.assertRaises(VideoNotesError):
            validate_project(project)

    def test_mobile_and_portable_checks_consistently_enforce_limit(self):
        original = {
            "schema": "videonotes-export-v1", "project_id": "local",
            "language": "en", "complete": True,
            "segments": [{"id": "s0", "start_ms": 0, "end_ms": 1000,
                          "text": "😀" * 5000}],
        }
        validate_portable_export(original)
        changed = copy.deepcopy(original)
        changed["segments"][0]["text"] += "😀"
        with self.assertRaises(VideoNotesError):
            validate_portable_export(changed)

    def test_desktop_patch_over_browser_limit_cannot_mutate_project(self):
        raw = (self.project / "transcript.json").read_bytes()
        patch = {
            "schema": "videonotes-web-corrections-v1", "project_id": "test-123",
            "changes": [{
                "id": "c0000000-s00000", "start_ms": 0, "end_ms": 500,
                "before": "Zażółć gęślą", "after": "😀" * 5001,
            }],
        }
        file = self.root / "patch.json"
        file.write_text(json.dumps(patch, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(VideoNotesError):
            import_web_corrections(self.project, file, apply=True)
        self.assertFalse((self.project / "edits.json").exists())
        self.assertEqual((self.project / "transcript.json").read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
