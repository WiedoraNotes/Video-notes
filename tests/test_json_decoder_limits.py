"""Regression: malformed deep/giant-int JSON must be an ordinary local error.

These are synthetic files, not human audio quality or mobile acceptance.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_contracts import demo_project, demo_transcript
from videonotes.cli import main
from videonotes.errors import VideoNotesError
from videonotes.mobile_contract import parse_portable_export
from videonotes.mobile_corrections import parse_mobile_corrections
from videonotes.mobile_import import read_mobile_edit_draft_file
from videonotes.semantic_draft import _parse_response
from videonotes.storage import load_json, save_json
from videonotes.web_corrections import import_web_corrections


DEEP = b"[" * 15000 + b"0" + b"]" * 15000
HUGE_INT = b"9" * 8000


class JsonDecoderLimitTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.document = {
            "schema": "videonotes-export-v1", "project_id": "private-unit-test",
            "language": "pl", "complete": False,
            "segments": [
                {"id": "s0", "start_ms": 0, "end_ms": 1200, "text": "private audio"},
            ],
        }

    def test_portable_and_patch_parsers_reject_deep_and_huge_integer_json(self):
        for raw in (DEEP, HUGE_INT):
            with self.subTest(size=len(raw)):
                with self.assertRaises(VideoNotesError):
                    parse_portable_export(raw)
                with self.assertRaises(VideoNotesError):
                    parse_mobile_corrections(self.document, raw)

    def test_mobile_draft_file_rejects_malicious_json_without_write(self):
        path = self.root / "draft.json"
        for raw in (DEEP, HUGE_INT):
            with self.subTest(size=len(raw)):
                path.write_bytes(raw)
                with self.assertRaises(VideoNotesError):
                    read_mobile_edit_draft_file(self.document, path, source_sha256="a"*64)
                self.assertEqual(path.read_bytes(), raw)

    def test_web_import_fails_before_edit_writes(self):
        project = self.root / "project"
        project.mkdir()
        save_json(project / "project.json", demo_project())
        save_json(project / "transcript.json", demo_transcript())
        source = (project / "transcript.json").read_bytes()
        path = self.root / "patch.json"
        for raw in (DEEP, HUGE_INT):
            with self.subTest(size=len(raw)):
                path.write_bytes(raw)
                with self.assertRaises(VideoNotesError):
                    import_web_corrections(project, path, apply=True)
                self.assertFalse((project / "edits.json").exists())
                self.assertEqual((project / "transcript.json").read_bytes(), source)

    def test_project_json_reader_fails_cleanly(self):
        path = self.root / "project-file.json"
        for raw in (DEEP, HUGE_INT):
            with self.subTest(size=len(raw)):
                path.write_bytes(raw)
                with self.assertRaises(VideoNotesError):
                    load_json(path)
                self.assertEqual(path.read_bytes(), raw)

    def test_private_semantic_model_reply_is_rejected(self):
        for raw in (DEEP, HUGE_INT):
            with self.subTest(size=len(raw)):
                with self.assertRaises(VideoNotesError):
                    _parse_response(raw, {"s0": "source"}, limit=2)

    def test_cli_reports_regular_error_without_private_json_or_traceback(self):
        path = self.root / "unsafe.json"
        path.write_bytes(DEEP)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(["mobile-import-check", str(path)])
        self.assertEqual(result, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Video Notes:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertNotIn(str(path), err.getvalue())


if __name__ == "__main__":
    unittest.main()
