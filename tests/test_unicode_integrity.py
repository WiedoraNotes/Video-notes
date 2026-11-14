"""Synthetic Unicode integrity regressions across offline KWN data boundaries.

Escaped lone surrogates are technically accepted by Python json.loads, but
are not valid Unicode scalar values; they must not silently corrupt a transcript
or provoke uncaught UnicodeEncodeError during UTF-8 export.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_contracts import demo_project, demo_transcript
from videonotes.contracts import valid_unicode_text, validate_project
from videonotes.errors import VideoNotesError
from videonotes.exports import edit_segment
from videonotes.mobile_contract import parse_portable_export, validate_portable_export
from videonotes.mobile_corrections import parse_mobile_corrections, render_mobile_corrections
from videonotes.semantic_draft import _parse_response
from videonotes.storage import read_project, save_json
from videonotes.web_corrections import import_web_corrections


class UnicodeIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.doc = {
            "schema": "videonotes-export-v1", "project_id": "private-test",
            "language": "pl", "complete": False,
            "segments": [{"id": "s0", "start_ms": 0, "end_ms": 1500,
                          "text": "Zażółć 😀"}],
        }

    def test_unicode_scalar_validator_accepts_emoji_and_blocks_nul_surrogates(self):
        for value in ("Zażółć 😀", "𐍈", "literal replacement \ufffd"):
            self.assertTrue(valid_unicode_text(value))
        for value in ("\x00", "\ud800", "\udc00", "prefix\ud800postfix"):
            self.assertFalse(valid_unicode_text(value))
        self.assertFalse(valid_unicode_text(None))

    def test_portable_transcript_rejects_escaped_unpaired_unicode(self):
        for bad in ("\ud800", "\udc00", "a\ud800b"):
            for field in ("project_id", "text"):
                with self.subTest(bad=ascii(bad), field=field):
                    doc = copy.deepcopy(self.doc)
                    if field == "project_id":
                        doc["project_id"] = bad
                    else:
                        doc["segments"][0]["text"] = bad
                    raw = json.dumps(doc, ensure_ascii=True).encode("ascii")
                    with self.assertRaises(VideoNotesError):
                        parse_portable_export(raw)
                    with self.assertRaises(VideoNotesError):
                        validate_portable_export(doc)
        self.assertEqual(parse_portable_export(
            json.dumps(self.doc, ensure_ascii=True).encode("ascii")
        )["segments"][0]["text"], "Zażółć 😀")

    def test_mobile_corrections_refuse_unpaired_surrogate_before_encode(self):
        for bad in ("\ud800", "\udc00"):
            with self.subTest(char=ascii(bad)):
                with self.assertRaises(VideoNotesError):
                    render_mobile_corrections(self.doc, {"s0": "Bad" + bad})
                patch = {
                    "schema": "videonotes-web-corrections-v1",
                    "project_id": "private-test",
                    "changes": [{
                        "id": "s0", "start_ms": 0, "end_ms": 1500,
                        "before": "Zażółć 😀", "after": "Bad" + bad,
                    }],
                }
                with self.assertRaises(VideoNotesError):
                    parse_mobile_corrections(
                        self.doc, json.dumps(patch, ensure_ascii=True).encode("ascii")
                    )

    def test_desktop_web_patch_rejects_surrogates_without_writes(self):
        project = self.root / "project"
        project.mkdir()
        save_json(project / "project.json", demo_project())
        save_json(project / "transcript.json", demo_transcript())
        original = (project / "transcript.json").read_bytes()
        payload = {
            "schema": "videonotes-web-corrections-v1", "project_id": "test-123",
            "changes": [{
                "id": "c0000000-s00000", "start_ms": 0, "end_ms": 500,
                "before": "Zażółć gęślą", "after": "Broken\ud800",
            }]
        }
        path = self.root / "patch.json"
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        with self.assertRaises(VideoNotesError):
            import_web_corrections(project, path, apply=True)
        self.assertEqual(original, (project / "transcript.json").read_bytes())
        self.assertFalse((project / "edits.json").exists())

    def test_desktop_project_validator_and_manual_edits_fail_closed(self):
        project = self.root / "project"
        project.mkdir()
        raw_project = demo_project()
        raw_project["id"] = "bad\ud800"
        with self.assertRaises(VideoNotesError):
            validate_project(raw_project)
        save_json(project / "project.json", demo_project())
        save_json(project / "transcript.json", demo_transcript())
        for bad in ("\ud800", "\udc00"):
            with self.subTest(bad=ascii(bad)):
                with self.assertRaises(VideoNotesError):
                    edit_segment(project, "c0000000-s00000", "Hello" + bad)
        self.assertFalse((project / "edits.json").exists())
        raw = demo_transcript()
        raw["segments"][0]["text"] = "Broken\ud800"
        (project / "transcript.json").write_text(
            json.dumps(raw, ensure_ascii=True), encoding="utf-8"
        )
        with self.assertRaises(VideoNotesError):
            read_project(project)

    def test_semantic_model_json_rejects_surrogate_in_heading_and_claim(self):
        allowed = {"s0": "Zażółć 😀"}
        for record in (
            {"heading": "Broken\ud800", "claims": [
                {"text": "Valid", "source_ids": ["s0"]}]},
            {"heading": "Notatka", "claims": [
                {"text": "Broken\udc00", "source_ids": ["s0"]}]},
        ):
            with self.subTest(record=ascii(record)):
                payload = json.dumps(record, ensure_ascii=True).encode("ascii")
                with self.assertRaises(VideoNotesError):
                    _parse_response(payload, allowed, limit=3)


if __name__ == "__main__":
    unittest.main()
